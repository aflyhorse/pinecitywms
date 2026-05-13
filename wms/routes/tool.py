"""Tool management routes: requisition, exchange/return, scrap, and print confirmation."""

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from wms import app, db
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
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
    User,
)
from datetime import datetime
from types import SimpleNamespace
from wms.utils import tool_receipt_view_required


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


def _resolve_warehouse_for_sku(sku_id: int, user_id: int | None = None) -> Warehouse:
    """Return warehouse for a SKU, preferring the scoped user's own warehouse."""
    if user_id is not None:
        user_owned = (
            WarehouseItemSKU.query.join(Warehouse)
            .filter(
                WarehouseItemSKU.itemSKU_id == sku_id,
                WarehouseItemSKU.count > 0,
                Warehouse.owner_id == user_id,
            )
            .first()
        )
        if user_owned:
            return user_owned.warehouse

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
    if not current_user.can_view_all_tool_groups:
        q = q.filter(Employee.user_id == current_user.id)
    return q.order_by(Employee.employee_id).all()


def _tool_scope_users(include_current_user: bool = False) -> list[User]:
    """Return users available for scoping tool pages."""
    if current_user.can_view_all_tool_groups:
        users = User.query.filter_by(is_auditor=False).order_by(User.nickname).all()
        if include_current_user and all(u.id != current_user.id for u in users):
            users.insert(0, current_user)
        return users
    return [current_user]


def _resolve_scope_user_id(
    source: str = "args", include_current_user: bool = False
) -> tuple[list[User], int]:
    """Resolve selected scoped user id from query/form with validation."""
    scope_users = _tool_scope_users(include_current_user=include_current_user)
    if not scope_users:
        return [], current_user.id

    allowed_ids = {u.id for u in scope_users}
    selected = (
        request.form.get("scope_user_id", type=int)
        if source == "form"
        else request.args.get("user_id", type=int)
    )
    if selected not in allowed_ids:
        selected = (
            current_user.id if current_user.id in allowed_ids else scope_users[0].id
        )
    return scope_users, selected


def _check_employee_access(emp: Employee) -> bool:
    """Return True if current user may manage this employee."""
    if current_user.can_view_all_tool_groups:
        return True
    if emp.user_id != current_user.id:
        flash("无权操作该员工。", "danger")
        return False
    return True


def _get_tool_inv(user_id: int, sku_id: int) -> "ToolInventory | None":
    """Return ToolInventory row for the given group user and SKU, or None."""
    return ToolInventory.query.filter_by(user_id=user_id, itemSKU_id=sku_id).first()

# use centralized helpers in `wms.utils` (user_can_view_tool_receipt, tool_receipt_view_required)


def _tool_receipt_scope_query(query, user_id: int):
    """Restrict tool receipts to those initiated by or targeted at the given user."""
    return query.filter(
        or_(
            ToolReceipt.operator_id == user_id,
            and_(
                ToolReceipt.type == ToolReceiptType.SCRAP,
                ToolReceipt.target_user_id == user_id,
            ),
        )
    )


# ---------------------------------------------------------------------------
# Tool requisition (工具领用)
# ---------------------------------------------------------------------------
@app.route("/tools/requisition", methods=["GET", "POST"])
@login_required
def tool_requisition():
    """Issue tools to an employee."""
    scope_users, scope_user_id = _resolve_scope_user_id(
        "form" if request.method == "POST" else "args"
    )

    if request.method == "POST":
        if current_user.is_auditor:
            flash("审核员仅可按用户查看工具领用数据，不可提交。", "danger")
            return redirect(url_for("tool_requisition", user_id=scope_user_id))

        employee_id = request.form.get("employee_id", type=int)
        selected_skus = request.form.getlist("sku_ids[]", type=int)
        quantities = {
            int(k.split("_")[1]): int(v)
            for k, v in request.form.items()
            if k.startswith("qty_") and v
        }

        if not employee_id:
            flash("请选择员工。", "danger")
            return redirect(url_for("tool_requisition", user_id=scope_user_id))

        if not selected_skus:
            flash("请至少选择一种工具。", "danger")
            return redirect(url_for("tool_requisition", user_id=scope_user_id))

        emp = db.session.get(Employee, employee_id)
        if not emp or not _check_employee_access(emp):
            return redirect(url_for("tool_requisition", user_id=scope_user_id))
        if emp.user_id != scope_user_id:
            flash("所选员工不属于当前查看用户，请切换用户后再提交。", "danger")
            return redirect(url_for("tool_requisition", user_id=scope_user_id))

        # Validate quantities and check stock
        errors = []
        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            if qty <= 0:
                sku = db.session.get(ItemSKU, sku_id)
                errors.append(
                    f"{sku.item.name} {sku.spec} 领用数量必须大于 0（当前: {qty}）"
                )
                continue
            ti = _get_tool_inv(scope_user_id, sku_id)
            if not ti or ti.count < qty:
                sku = db.session.get(ItemSKU, sku_id)
                errors.append(
                    f"{sku.item.name} {sku.spec} 库内余量不足（余量: {ti.count if ti else 0}，申领: {qty}）"
                )

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("tool_requisition", user_id=scope_user_id))

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
            ti = _get_tool_inv(scope_user_id, sku_id)
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
        return redirect(url_for("tool_print", user_id=scope_user_id))

    # GET: list tool inventory with available stock (scoped to current user's group)
    tool_inventory = (
        ToolInventory.query.join(ItemSKU)
        .join(Item)
        .filter(ToolInventory.user_id == scope_user_id, ToolInventory.count > 0)
        .order_by(Item.name)
        .all()
    )
    employees = [e for e in _accessible_employees() if e.user_id == scope_user_id]
    return render_template(
        "tool_requisition.html.jinja",
        tool_inventory=tool_inventory,
        employees=employees,
        can_operate=not current_user.is_auditor,
        scope_users=scope_users,
        selected_scope_user_id=scope_user_id,
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
        if current_user.is_auditor:
            flash("审核员仅可查看，不可执行更换/归还。", "danger")
            return redirect(url_for("tool_employee_detail", employee_id=employee_id))

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
        inv_user_id = emp.user_id
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
                ti = _get_tool_inv(inv_user_id, sku_id)
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
            target_user_id=emp.user_id,
            operator_id=current_user.id,
        )
        db.session.add(tool_receipt)
        db.session.flush()

        for sku_id in selected_skus:
            qty = quantities.get(sku_id, 1)
            ti = _get_tool_inv(inv_user_id, sku_id)
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
        return redirect(url_for("tool_print", user_id=emp.user_id))

    # GET: list employee's tool holdings
    holdings = (
        EmployeeToolHolding.query.filter_by(employee_id=employee_id)
        .filter(EmployeeToolHolding.count > 0)
        .join(ItemSKU)
        .join(Item)
        .all()
    )
    # Also attach current tool inventory count for reference (scoped to current user's group)
    # Prefetch ToolInventory rows to avoid N+1 queries
    sku_ids = [h.itemSKU_id for h in holdings]
    inv_rows = (
        ToolInventory.query.filter(
            ToolInventory.user_id == emp.user_id, ToolInventory.itemSKU_id.in_(sku_ids)
        ).all()
        if sku_ids
        else []
    )
    inv_map = {r.itemSKU_id: r.count for r in inv_rows}
    tool_counts = {h.itemSKU_id: inv_map.get(h.itemSKU_id, 0) for h in holdings}
    return render_template(
        "tool_employee_detail.html.jinja",
        employee=emp,
        holdings=holdings,
        tool_counts=tool_counts,
        can_operate=not current_user.is_auditor,
    )


# ---------------------------------------------------------------------------
# Tool scrap (工具报废)
# ---------------------------------------------------------------------------
@app.route("/tools/scrap", methods=["GET", "POST"])
@login_required
def tool_scrap():
    """Users submit scrap requests; auditors/admins review and confirm them."""
    # Auditor/admin review queue
    if current_user.is_auditor:
        if request.method == "POST":
            selected_request_ids = sorted(
                set(request.form.getlist("request_ids[]", type=int))
            )
            if not selected_request_ids:
                flash("请至少选择一张报废申请单。", "danger")
                return redirect(url_for("tool_scrap"))

            confirmed = 0
            for request_id in selected_request_ids:
                req = db.session.get(ToolReceipt, request_id)
                if (
                    not req
                    or req.type != ToolReceiptType.SCRAP
                    or req.receipt_id is not None
                ):
                    continue

                target_user_id = req.target_user_id or req.operator_id
                target_user = db.session.get(User, target_user_id)
                if not target_user:
                    continue

                area = _get_or_create_area("班组")
                dept = _get_or_create_department("设备管理科")
                location = target_user.nickname

                warehouse_transactions: dict[int, list[tuple[int, int]]] = {}
                valid = True
                # Prefetch ToolInventory and WarehouseItemSKU rows to avoid N+1 queries
                sku_ids = [tx.itemSKU_id for tx in req.transactions]
                ti_rows = (
                    ToolInventory.query.filter(
                        ToolInventory.user_id == target_user_id,
                        ToolInventory.itemSKU_id.in_(sku_ids),
                    ).all()
                    if sku_ids
                    else []
                )
                ti_map = {t.itemSKU_id: t for t in ti_rows}

                # Prefetch WarehouseItemSKU rows (include warehouse relationship)
                wis_rows = (
                    WarehouseItemSKU.query.options(
                        joinedload(WarehouseItemSKU.warehouse)
                    )
                    .filter(
                        WarehouseItemSKU.itemSKU_id.in_(sku_ids),
                        WarehouseItemSKU.count > 0,
                    )
                    .all()
                    if sku_ids
                    else []
                )
                wis_map: dict[int, list[WarehouseItemSKU]] = {}
                for w in wis_rows:
                    wis_map.setdefault(w.itemSKU_id, []).append(w)

                for tx in req.transactions:
                    ti = ti_map.get(tx.itemSKU_id)
                    if not ti or ti.pending_scrap < tx.count:
                        flash(
                            f"申请单 #{req.id} 的待报废数量发生变化，请让班组重新提交。",
                            "danger",
                        )
                        valid = False
                        break

                    # Resolve warehouse preferring user's owned warehouse
                    selected_wh = None
                    candidates = wis_map.get(tx.itemSKU_id, [])
                    for c in candidates:
                        if c.warehouse and c.warehouse.owner_id == target_user_id:
                            selected_wh = c.warehouse
                            break
                    if not selected_wh and candidates:
                        selected_wh = candidates[0].warehouse
                    if not selected_wh:
                        # fallback to current user's warehouse or public warehouse
                        if current_user.warehouse:
                            selected_wh = current_user.warehouse
                        else:
                            selected_wh = Warehouse.query.filter_by(
                                is_public=True
                            ).first()

                    if not selected_wh:
                        flash(f"申请单 #{req.id} 无法定位仓库。", "danger")
                        valid = False
                        break

                    warehouse_transactions.setdefault(selected_wh.id, []).append(
                        (tx.itemSKU_id, int(tx.count))
                    )

                if not valid:
                    continue

                last_receipt_id = None
                try:
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
                            note=f"工具报废（审核确认，申请单#{req.id}）",
                            is_tool=True,
                        )
                        db.session.add(wh_receipt)
                        db.session.flush()
                        last_receipt_id = wh_receipt.id

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
                            ti = _get_tool_inv(target_user_id, sku_id)
                            ti.pending_scrap -= scrap_count

                        db.session.commit()
                        wh_receipt.update_warehouse_item_skus()
                        db.session.commit()

                    req.receipt_id = last_receipt_id
                    req.confirmed_by_id = current_user.id
                    req.confirmed_at = datetime.now()
                    req.printed = True
                    db.session.commit()
                    confirmed += 1
                except ValueError as e:
                    db.session.rollback()
                    flash(f"申请单 #{req.id} 确认失败: {e}", "danger")

            if confirmed:
                flash(f"已确认 {confirmed} 张报废申请单。", "success")
            return redirect(url_for("tool_scrap"))

        pending_requests = (
            ToolReceipt.query.filter(
                ToolReceipt.type == ToolReceiptType.SCRAP,
                ToolReceipt.receipt_id.is_(None),
            )
            .order_by(ToolReceipt.date.desc())
            .all()
        )
        return render_template(
            "tool_scrap.html.jinja",
            pending=[],
            can_submit=False,
            scope_users=[],
            selected_scope_user_id=None,
            audit_mode=True,
            pending_requests=pending_requests,
        )

    # User/admin submit request (no immediate stockout here)
    scope_users, scope_user_id = _resolve_scope_user_id(
        "form" if request.method == "POST" else "args"
    )

    if request.method == "POST":
        selected_skus = sorted(set(request.form.getlist("sku_ids[]", type=int)))
        if not selected_skus:
            flash("请至少选择一种工具。", "danger")
            return redirect(url_for("tool_scrap", user_id=scope_user_id))

        lines: list[tuple[int, int]] = []
        for sku_id in selected_skus:
            ti = _get_tool_inv(scope_user_id, sku_id)
            pending_total = ti.pending_scrap if ti else 0
            if pending_total <= 0:
                continue
            lines.append((sku_id, int(pending_total)))

        if not lines:
            flash("所选工具均无待报废数量。", "warning")
            return redirect(url_for("tool_scrap", user_id=scope_user_id))

        tool_receipt = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            employee_id=None,
            target_user_id=scope_user_id,
            operator_id=current_user.id,
            printed=True,  # scrap receipts are considered non-print-needed; mark as printed
            receipt_id=None,
            confirmed_by_id=None,
            confirmed_at=None,
        )
        db.session.add(tool_receipt)
        db.session.flush()

        for sku_id, scrap_count in lines:
            db.session.add(
                ToolTransaction(
                    tool_receipt_id=tool_receipt.id,
                    itemSKU_id=sku_id,
                    count=scrap_count,
                    employee_id=None,
                )
            )

        db.session.commit()
        flash("报废申请已提交，等待审核员确认。", "success")
        return redirect(url_for("tool_scrap", user_id=scope_user_id))

    pending_rows = (
        ToolInventory.query.join(ItemSKU)
        .join(Item)
        .filter(
            ToolInventory.user_id == scope_user_id,
            ToolInventory.pending_scrap > 0,
        )
        .order_by(Item.name, ItemSKU.id)
        .all()
    )
    pending = [
        SimpleNamespace(itemSKU=row.itemSKU, pending_scrap=row.pending_scrap)
        for row in pending_rows
    ]

    my_pending_requests = (
        ToolReceipt.query.filter(
            ToolReceipt.type == ToolReceiptType.SCRAP,
            ToolReceipt.target_user_id == scope_user_id,
            ToolReceipt.receipt_id.is_(None),
        )
        .order_by(ToolReceipt.date.desc())
        .all()
    )

    return render_template(
        "tool_scrap.html.jinja",
        pending=pending,
        can_submit=True,
        scope_users=scope_users,
        selected_scope_user_id=scope_user_id,
        audit_mode=False,
        pending_requests=my_pending_requests,
    )


# ---------------------------------------------------------------------------
# Confirmation slip printing (确认单打印)
# ---------------------------------------------------------------------------
@app.route("/tools/print", methods=["GET", "POST"])
@login_required
def tool_print():
    """View and print tool confirmation slips."""
    scope_users, scope_user_id = _resolve_scope_user_id(
        "form" if request.method == "POST" else "args",
        include_current_user=True,
    )

    if request.method == "POST":
        if current_user.is_auditor:
            flash("审核员无权修改打印状态。", "danger")
            return redirect(url_for("tool_print", user_id=scope_user_id))

        selected_ids = request.form.getlist("receipt_ids[]", type=int)
        if selected_ids:
            q = _tool_receipt_scope_query(
                ToolReceipt.query.filter(ToolReceipt.id.in_(selected_ids)),
                scope_user_id,
            )
            q.update({"printed": True}, synchronize_session="fetch")
            db.session.commit()
            flash(f"已将 {len(selected_ids)} 张单据标记为已打印。", "success")
        return redirect(url_for("tool_print", user_id=scope_user_id))

    page = request.args.get("page", 1, type=int)
    q = _tool_receipt_scope_query(ToolReceipt.query, scope_user_id)
    pagination = q.order_by(ToolReceipt.date.desc()).paginate(page=page, per_page=20)
    return render_template(
        "tool_print.html.jinja",
        pagination=pagination,
        scope_users=scope_users,
        selected_scope_user_id=scope_user_id,
    )


@app.route("/tools/print/<int:receipt_id>")
@login_required
@tool_receipt_view_required
def tool_print_detail(receipt_id):
    """Preview a single tool confirmation slip."""
    tool_receipt = db.session.get(ToolReceipt, receipt_id)
    return render_template("tool_print_detail.html.jinja", tool_receipt=tool_receipt)


@app.route("/tools/print/<int:receipt_id>/toggle-printed", methods=["POST"])
@login_required
def tool_print_toggle_printed(receipt_id):
    """Toggle printed status for a single tool confirmation slip."""
    if current_user.is_auditor:
        flash("审核员无权修改打印状态。", "danger")
        return redirect(url_for("tool_print"))

    tool_receipt = db.session.get(ToolReceipt, receipt_id)
    if not tool_receipt:
        flash("单据不存在。", "danger")
        return redirect(url_for("tool_print"))
    if (
        not current_user.can_view_all_tool_groups
        and tool_receipt.operator_id != current_user.id
    ):
        flash("无权操作该单据。", "danger")
        return redirect(url_for("tool_print"))

    # Disallow toggling printed status for SCRAP receipts (treated as already "printed")
    if tool_receipt.type == ToolReceiptType.SCRAP:
        flash("报废申请的打印状态不可修改。", "warning")
        return redirect(url_for("tool_print_detail", receipt_id=tool_receipt.id))

    tool_receipt.printed = not tool_receipt.printed
    db.session.commit()
    if tool_receipt.printed:
        flash("已标记为已打印。", "success")
    else:
        flash("已取消“已打印”状态。", "success")
    return redirect(url_for("tool_print_detail", receipt_id=tool_receipt.id))
