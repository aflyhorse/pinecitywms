"""Tool management routes: requisition, exchange/return, scrap, and print confirmation."""

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from wms import app, db
from wms.models import (
    Employee,
    EmployeeToolHolding,
    ToolInventory,
    ToolReceipt,
    ToolReceiptType,
    ToolTransaction,
    ItemSKU,
    Item,
    Receipt,
    ReceiptType,
    Transaction,
    WarehouseItemSKU,
    Warehouse,
    Area,
    Department,
)
from datetime import datetime


def _get_or_create_area(name: str) -> Area:
    """Return existing Area by name, or create it."""
    area = Area.query.filter_by(name=name).first()
    if not area:
        area = Area(name=name)
        db.session.add(area)
        db.session.flush()
    return area


def _get_or_create_department(name: str) -> Department:
    """Return existing Department by name, or create it."""
    dept = Department.query.filter_by(name=name).first()
    if not dept:
        dept = Department(name=name)
        db.session.add(dept)
        db.session.flush()
    return dept


def _resolve_warehouse_for_sku(sku_id: int) -> Warehouse:
    """Return a warehouse that has the given SKU in stock; fall back to first public warehouse."""
    wis = (
        WarehouseItemSKU.query.filter_by(itemSKU_id=sku_id)
        .filter(WarehouseItemSKU.count > 0)
        .first()
    )
    if wis:
        return wis.warehouse
    if current_user.warehouse:
        return current_user.warehouse
    return Warehouse.query.filter_by(is_public=True).first()


def _accessible_employees():
    """Return active employees visible to the current user."""
    q = Employee.query.filter_by(is_resigned=False)
    if not current_user.is_admin:
        q = q.filter(Employee.user_id == current_user.id)
    return q.order_by(Employee.employee_id).all()


def _check_employee_access(emp: Employee) -> bool:
    """Return True if current user may manage this employee."""
    if current_user.is_admin:
        return True
    if emp.user_id != current_user.id:
        flash("无权操作该员工。", "danger")
        return False
    return True


def _get_tool_inv(user_id: int, sku_id: int) -> "ToolInventory | None":
    """Return ToolInventory row for the given group user and SKU, or None."""
    return ToolInventory.query.filter_by(user_id=user_id, itemSKU_id=sku_id).first()


# ---------------------------------------------------------------------------
# Tool requisition (工具领用)
# ---------------------------------------------------------------------------
@app.route("/tools/requisition", methods=["GET", "POST"])
@login_required
def tool_requisition():
    """Issue tools to an employee."""
    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        selected_skus = request.form.getlist("sku_ids[]", type=int)
        quantities = {
            int(k.split("_")[1]): int(v)
            for k, v in request.form.items()
            if k.startswith("qty_") and v
        }

        if not employee_id:
            flash("请选择员工。", "danger")
            return redirect(url_for("tool_requisition"))

        if not selected_skus:
            flash("请至少选择一种工具。", "danger")
            return redirect(url_for("tool_requisition"))

        emp = db.session.get(Employee, employee_id)
        if not emp or not _check_employee_access(emp):
            return redirect(url_for("tool_requisition"))

        # Validate quantities and check stock
        errors = []
        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            ti = _get_tool_inv(current_user.id, sku_id)
            if not ti or ti.count < qty:
                sku = db.session.get(ItemSKU, sku_id)
                errors.append(
                    f"{sku.item.name} {sku.spec} 库内余量不足（余量: {ti.count if ti else 0}，申领: {qty}）"
                )

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("tool_requisition"))

        # Create ToolReceipt
        tool_receipt = ToolReceipt(
            type=ToolReceiptType.REQUISITION,
            employee_id=employee_id,
            operator_id=current_user.id,
        )
        db.session.add(tool_receipt)
        db.session.flush()

        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            ti = _get_tool_inv(current_user.id, sku_id)
            # Deduct from tool inventory
            ti.count -= qty
            # Update employee holdings
            holding = EmployeeToolHolding.query.filter_by(
                employee_id=employee_id, itemSKU_id=sku_id
            ).first()
            if holding:
                holding.count += qty
            else:
                holding = EmployeeToolHolding(
                    employee_id=employee_id, itemSKU_id=sku_id, count=qty
                )
                db.session.add(holding)
            # Add transaction line
            db.session.add(
                ToolTransaction(
                    tool_receipt_id=tool_receipt.id,
                    itemSKU_id=sku_id,
                    count=qty,
                    employee_id=employee_id,
                )
            )

        db.session.commit()
        flash(f"已成功为员工 {emp.name} 办理工具领用。", "success")
        return redirect(url_for("tool_print"))

    # GET: list tool inventory with available stock (scoped to current user's group)
    tool_inventory = (
        ToolInventory.query.join(ItemSKU)
        .join(Item)
        .filter(ToolInventory.user_id == current_user.id, ToolInventory.count > 0)
        .order_by(Item.name)
        .all()
    )
    employees = _accessible_employees()
    return render_template(
        "tool_requisition.html.jinja",
        tool_inventory=tool_inventory,
        employees=employees,
    )


# ---------------------------------------------------------------------------
# Tool exchange / return for a specific employee (工具更换/归还)
# ---------------------------------------------------------------------------
@app.route("/tools/employee/<int:employee_id>", methods=["GET", "POST"])
@login_required
def tool_employee_detail(employee_id):
    """Exchange or return tools for a specific employee."""
    emp = db.session.get(Employee, employee_id)
    if not emp or not _check_employee_access(emp):
        return redirect(url_for("employees"))

    if request.method == "POST":
        action = request.form.get("action")  # "exchange" or "return"
        selected_skus = request.form.getlist("sku_ids[]", type=int)
        quantities = {
            int(k.split("_")[1]): int(v)
            for k, v in request.form.items()
            if k.startswith("qty_") and v
        }

        if action not in ("exchange", "return"):
            flash("无效的操作类型。", "danger")
            return redirect(url_for("tool_employee_detail", employee_id=employee_id))

        if not selected_skus:
            flash("请至少选择一种工具。", "danger")
            return redirect(url_for("tool_employee_detail", employee_id=employee_id))

        # Validate quantities against holdings
        errors = []
        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            holding = EmployeeToolHolding.query.filter_by(
                employee_id=employee_id, itemSKU_id=sku_id
            ).first()
            if not holding or holding.count < qty:
                sku = db.session.get(ItemSKU, sku_id)
                errors.append(
                    f"{sku.item.name} {sku.spec} 员工持有数量不足（持有: {holding.count if holding else 0}，操作: {qty}）"
                )
            if action == "exchange":
                ti = _get_tool_inv(current_user.id, sku_id)
                if not ti or ti.count < qty:
                    sku = db.session.get(ItemSKU, sku_id)
                    errors.append(
                        f"{sku.item.name} {sku.spec} 库内余量不足，无法更换（余量: {ti.count if ti else 0}，申请: {qty}）"
                    )

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("tool_employee_detail", employee_id=employee_id))

        receipt_type = (
            ToolReceiptType.EXCHANGE if action == "exchange" else ToolReceiptType.RETURN
        )
        tool_receipt = ToolReceipt(
            type=receipt_type,
            employee_id=employee_id,
            operator_id=current_user.id,
        )
        db.session.add(tool_receipt)
        db.session.flush()

        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            ti = _get_tool_inv(current_user.id, sku_id)
            holding = EmployeeToolHolding.query.filter_by(
                employee_id=employee_id, itemSKU_id=sku_id
            ).first()

            if action == "return":
                # Return to inventory, decrease employee holding
                ti.count += qty
                holding.count -= qty
            else:
                # Exchange: old tools go to pending_scrap, new from inventory
                ti.pending_scrap += qty
                ti.count -= qty
                # Employee still holds same count

            db.session.add(
                ToolTransaction(
                    tool_receipt_id=tool_receipt.id,
                    itemSKU_id=sku_id,
                    count=qty,
                    employee_id=employee_id,
                )
            )

        db.session.commit()
        flash(
            f"已成功为员工 {emp.name} 办理工具{'更换' if action == 'exchange' else '归还'}。",
            "success",
        )
        return redirect(url_for("tool_print"))

    # GET: list employee's tool holdings
    holdings = (
        EmployeeToolHolding.query.filter_by(employee_id=employee_id)
        .filter(EmployeeToolHolding.count > 0)
        .join(ItemSKU)
        .join(Item)
        .all()
    )
    # Also attach current tool inventory count for reference (scoped to current user's group)
    tool_counts = {
        h.itemSKU_id: (
            ti.count if (ti := _get_tool_inv(current_user.id, h.itemSKU_id)) else 0
        )
        for h in holdings
    }
    return render_template(
        "tool_employee_detail.html.jinja",
        employee=emp,
        holdings=holdings,
        tool_counts=tool_counts,
    )


# ---------------------------------------------------------------------------
# Tool scrap (工具报废)
# ---------------------------------------------------------------------------
@app.route("/tools/scrap", methods=["GET", "POST"])
@login_required
def tool_scrap():
    """Formally scrap tools that are pending scrap, generating a stockout receipt."""
    if request.method == "POST":
        selected_skus = request.form.getlist("sku_ids[]", type=int)
        if not selected_skus:
            flash("请至少选择一种工具。", "danger")
            return redirect(url_for("tool_scrap"))

        # Resolve area and department for the scrap receipt
        area = _get_or_create_area("班组")
        dept = _get_or_create_department("设备管理科")
        location = current_user.nickname  # 班组名

        # Group by warehouse: one receipt per warehouse
        warehouse_transactions: dict[int, list] = {}
        for sku_id in selected_skus:
            ti = _get_tool_inv(current_user.id, sku_id)
            if not ti or ti.pending_scrap <= 0:
                continue
            warehouse = _resolve_warehouse_for_sku(sku_id)
            if not warehouse:
                flash("无法找到工具所在仓库，跳过部分工具。", "warning")
                continue
            warehouse_transactions.setdefault(warehouse.id, []).append(
                (sku_id, ti.pending_scrap)
            )

        if not warehouse_transactions:
            flash("所选工具均无待报废数量。", "warning")
            return redirect(url_for("tool_scrap"))

        tool_receipt = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            employee_id=None,
            operator_id=current_user.id,
            printed=True,  # Scrap receipts are not meant to be printed
        )
        db.session.add(tool_receipt)
        db.session.flush()

        for warehouse_id, items in warehouse_transactions.items():
            refcode = f"SCRAP-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            wh_receipt = Receipt(
                operator_id=current_user.id,
                refcode=refcode,
                warehouse_id=warehouse_id,
                type=ReceiptType.STOCKOUT,
                area_id=area.id,
                department_id=dept.id,
                location=location,
                note="工具报废",
                is_tool=True,
            )
            db.session.add(wh_receipt)
            db.session.flush()

            for sku_id, scrap_count in items:
                wis = WarehouseItemSKU.query.filter_by(
                    warehouse_id=warehouse_id, itemSKU_id=sku_id
                ).first()
                price = wis.average_price if wis else 0
                db.session.add(
                    Transaction(
                        itemSKU_id=sku_id,
                        count=-scrap_count,
                        price=price,
                        receipt_id=wh_receipt.id,
                    )
                )
                db.session.add(
                    ToolTransaction(
                        tool_receipt_id=tool_receipt.id,
                        itemSKU_id=sku_id,
                        count=scrap_count,
                        employee_id=None,
                    )
                )
                # Clear pending_scrap
                ti = _get_tool_inv(current_user.id, sku_id)
                ti.pending_scrap = 0

            try:
                db.session.commit()
                wh_receipt.update_warehouse_item_skus()
                db.session.commit()
            except ValueError as e:
                db.session.rollback()
                flash(f"生成出库单时出错: {e}", "danger")
                return redirect(url_for("tool_scrap"))

        # Save receipt reference on tool_receipt
        tool_receipt.receipt_id = wh_receipt.id
        db.session.commit()

        flash("工具报废完成，出库单已生成。", "success")
        return redirect(url_for("tool_scrap"))

    # GET: show pending scrap inventory (each user only sees their own group's items)
    pending = (
        ToolInventory.query.join(ItemSKU)
        .join(Item)
        .filter(
            ToolInventory.user_id == current_user.id,
            ToolInventory.pending_scrap > 0,
        )
        .order_by(Item.name)
        .all()
    )
    return render_template("tool_scrap.html.jinja", pending=pending)


# ---------------------------------------------------------------------------
# Confirmation slip printing (确认单打印)
# ---------------------------------------------------------------------------
@app.route("/tools/print", methods=["GET", "POST"])
@login_required
def tool_print():
    """View and print tool confirmation slips."""
    if request.method == "POST":
        selected_ids = request.form.getlist("receipt_ids[]", type=int)
        if selected_ids:
            # Non-admins may only mark their own receipts as printed
            q = ToolReceipt.query.filter(ToolReceipt.id.in_(selected_ids))
            if not current_user.is_admin:
                q = q.filter(ToolReceipt.operator_id == current_user.id)
            q.update({"printed": True}, synchronize_session="fetch")
            db.session.commit()
            flash(f"已将 {len(selected_ids)} 张单据标记为已打印。", "success")
        return redirect(url_for("tool_print"))

    page = request.args.get("page", 1, type=int)
    q = ToolReceipt.query
    if not current_user.is_admin:
        q = q.filter(ToolReceipt.operator_id == current_user.id)
    pagination = q.order_by(ToolReceipt.date.desc()).paginate(page=page, per_page=20)
    return render_template("tool_print.html.jinja", pagination=pagination)


@app.route("/tools/print/<int:receipt_id>")
@login_required
def tool_print_detail(receipt_id):
    """Preview a single tool confirmation slip."""
    tool_receipt = db.session.get(ToolReceipt, receipt_id)
    if not tool_receipt:
        flash("单据不存在。", "danger")
        return redirect(url_for("tool_print"))
    if not current_user.is_admin and tool_receipt.operator_id != current_user.id:
        flash("无权查看该单据。", "danger")
        return redirect(url_for("tool_print"))
    return render_template("tool_print_detail.html.jinja", tool_receipt=tool_receipt)


@app.route("/tools/print/<int:receipt_id>/toggle-printed", methods=["POST"])
@login_required
def tool_print_toggle_printed(receipt_id):
    """Toggle printed status for a single tool confirmation slip."""
    tool_receipt = db.session.get(ToolReceipt, receipt_id)
    if not tool_receipt:
        flash("单据不存在。", "danger")
        return redirect(url_for("tool_print"))
    if not current_user.is_admin and tool_receipt.operator_id != current_user.id:
        flash("无权操作该单据。", "danger")
        return redirect(url_for("tool_print"))

    tool_receipt.printed = not tool_receipt.printed
    db.session.commit()
    if tool_receipt.printed:
        flash("已标记为已打印。", "success")
    else:
        flash("已取消“已打印”状态。", "success")
    return redirect(url_for("tool_print_detail", receipt_id=tool_receipt.id))
