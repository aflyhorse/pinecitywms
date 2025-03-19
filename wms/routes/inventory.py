from flask import render_template, url_for, redirect, flash, request, send_file
from flask_login import login_required, current_user
from wms import app, db
from wms.utils import admin_required
from wms.models import (
    ItemSKU,
    Item,
    Warehouse,
    Receipt,
    Transaction,
    ReceiptType,
    WarehouseItemSKU,
    Area,
    Department,
)
from wms.forms import StockInForm, ItemSearchForm, StockOutForm
from sqlalchemy import and_
from io import BytesIO
import pandas as pd
from datetime import datetime


@app.route("/inventory", methods=["GET", "POST"])
@login_required
def inventory():
    # Admin can see inventory of all warehouses
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        # Regular users can only see public warehouses and their own warehouses
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

    # Get selected warehouse from query params, default to first warehouse
    selected_warehouse_id = request.args.get("warehouse", type=int)
    selected_warehouse = None
    if selected_warehouse_id:
        selected_warehouse = next(
            (w for w in warehouses if w.id == selected_warehouse_id), warehouses[0]
        )
    else:
        selected_warehouse = warehouses[0] if warehouses else None

    page = request.args.get("page", 1, type=int)
    per_page = 20

    # Initialize search form
    form = ItemSearchForm()
    warehouse_items = {}
    pagination = None

    if selected_warehouse:
        query = (
            db.session.query(WarehouseItemSKU)
            .join(ItemSKU)
            .join(Item)
            .filter(
                and_(
                    WarehouseItemSKU.warehouse_id == selected_warehouse.id,
                    WarehouseItemSKU.count > 0,
                )
            )
        )

        if form.validate_on_submit():
            # Redirect to GET request with search parameters
            return redirect(
                url_for(
                    "inventory",
                    warehouse=selected_warehouse.id,
                    name=form.name.data,
                    brand=form.brand.data,
                    spec=form.spec.data,
                    page=1,  # Reset to page 1 when searching
                )
            )

        # Get search parameters from query string
        form.name.data = request.args.get("name", "")
        form.brand.data = request.args.get("brand", "")
        form.spec.data = request.args.get("spec", "")

        # Apply filters if there's search data
        if form.name.data:
            query = query.filter(Item.name.ilike(f"%{form.name.data}%"))
        if form.brand.data:
            query = query.filter(ItemSKU.brand.ilike(f"%{form.brand.data}%"))
        if form.spec.data:
            query = query.filter(ItemSKU.spec.ilike(f"%{form.spec.data}%"))

        # Add ordering
        query = query.order_by(Item.name, ItemSKU.brand, ItemSKU.spec)
        pagination = query.paginate(page=page, per_page=per_page)
        if pagination.items:
            warehouse_items[selected_warehouse] = pagination.items

    return render_template(
        "inventory.html.jinja",
        warehouse_items=warehouse_items,
        pagination=pagination,
        warehouses=warehouses,
        selected_warehouse=selected_warehouse,
        itemSearchForm=form,
    )


@app.route("/stockin", methods=["GET", "POST"])
@login_required
@admin_required
def stockin():
    form = StockInForm()
    # Get all items with their display text
    skus = db.session.query(ItemSKU).join(Item).all()
    items = [(sku.id, f"{sku.item.name} - {sku.brand} - {sku.spec}") for sku in skus]
    form.warehouse.choices = [(w.id, w.name) for w in Warehouse.query.all()]

    if form.validate_on_submit():
        receipt = Receipt(
            operator=current_user,
            refcode=form.refcode.data,
            warehouse_id=form.warehouse.data,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()

        for item_form in form.items:
            try:
                # Use the hidden item_sku_id field instead of item_id text field
                item_sku_id = item_form.item_sku_id.data
                if not item_sku_id:
                    # Fallback to the old method if hidden field is not populated
                    item_sku_id = item_form.item_id.data

                item_id = int(item_sku_id)

                # Validate the item exists
                item = db.session.get(ItemSKU, item_id)
                if not item:
                    raise ValueError("Invalid item ID")

                transaction = Transaction(
                    itemSKU_id=item_id,
                    count=item_form.quantity.data,
                    price=item_form.price.data,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
            except ValueError:
                flash("无效的物品", "danger")
                return render_template(
                    "inventory_stockin.html.jinja", form=form, items=items
                )

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()

        flash("入库成功。", "success")
        return redirect(url_for("inventory", warehouse=form.warehouse.data))
    else:
        if request.method == "POST":
            for field, errors in form.errors.items():  # pragma: no cover
                for error in errors:
                    flash(f"Error in {field}: {error}", "danger")

    return render_template("inventory_stockin.html.jinja", form=form, items=items)


@app.route("/stockout", methods=["GET", "POST"])
@login_required
def stockout():
    form = StockOutForm()

    # Get all areas and departments
    areas = Area.query.all()
    departments = Department.query.all()

    # Get warehouses accessible by the current user
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public) | (Warehouse.owner_id == current_user.id)
        ).all()

    # Populate form choices
    form.warehouse.choices = [(w.id, w.name) for w in warehouses]
    form.area.choices = [(a.id, a.name) for a in areas]
    form.department.choices = [(d.id, d.name) for d in departments]

    # Initialize items list
    items = []

    # Get selected warehouse - either from form data (POST) or query parameters (GET)
    selected_warehouse_id = None
    if request.method == "POST":
        selected_warehouse_id = form.warehouse.data
    else:
        selected_warehouse_id = request.args.get("warehouse", type=int)
        if selected_warehouse_id:
            form.warehouse.data = selected_warehouse_id  # pragma: no cover
        elif warehouses:
            # Default to first warehouse if not specified
            selected_warehouse_id = warehouses[0].id
            form.warehouse.data = selected_warehouse_id

    # If we have a selected warehouse, get its items
    if selected_warehouse_id:
        skus = (
            db.session.query(
                ItemSKU, WarehouseItemSKU.average_price, WarehouseItemSKU.count
            )
            .join(Item)
            .join(WarehouseItemSKU)
            .filter(
                WarehouseItemSKU.count > 0,
                WarehouseItemSKU.warehouse_id == selected_warehouse_id,
            )
            .distinct()
            .all()
        )

        items = [
            (
                sku.ItemSKU.id,
                f"{sku.ItemSKU.item.name} - {sku.ItemSKU.brand} - {sku.ItemSKU.spec}",
                float(sku.average_price),
                int(sku.count),  # Add stock count
            )
            for sku in skus
        ]

    # Create dictionary for item details
    items_dict = {
        id: {"name": name, "price": price, "count": count}
        for id, name, price, count in items
    }

    if form.validate_on_submit():
        # Find area and department by ID
        area = db.session.get(Area, form.area.data)
        if not area:
            flash("无效的区域选择", "danger")  # pragma: no cover
            return render_template(  # pragma: no cover
                "inventory_stockout.html.jinja",
                form=form,
                items=items,
            )

        # Find department by ID
        department = db.session.get(Department, form.department.data)
        if not department:
            flash("无效的部门选择", "danger")  # pragma: no cover
            return render_template(  # pragma: no cover
                "inventory_stockout.html.jinja",
                form=form,
                items=items,
            )

        # Get the selected warehouse
        selected_warehouse = db.session.get(Warehouse, form.warehouse.data)
        if not selected_warehouse:
            flash("请选择有效的仓库", "danger")  # pragma: no cover
            return render_template(  # pragma: no cover
                "inventory_stockout.html.jinja",
                form=form,
                items=items,
            )

        receipt = Receipt(
            operator=current_user,
            warehouse_id=selected_warehouse.id,
            type=ReceiptType.STOCKOUT,
            area=area,
            department=department,
            location=form.location.data,
            note=None if not form.note.data else form.note.data,
        )
        db.session.add(receipt)
        db.session.flush()

        for item_form in form.items:
            try:
                # Use the hidden item_sku_id field instead of item_id text field
                item_sku_id = item_form.item_sku_id.data
                if not item_sku_id:
                    # Fallback to the old method if hidden field is not populated
                    item_sku_id = item_form.item_id.data

                item_id = int(item_sku_id)

                # Validate the item exists
                item = db.session.get(ItemSKU, item_id)
                if not item:
                    raise ValueError("Invalid item ID")

                # Check if there's enough stock in the selected warehouse
                available_stock = (
                    db.session.query(WarehouseItemSKU.count)
                    .filter(
                        WarehouseItemSKU.itemSKU_id == item_id,
                        WarehouseItemSKU.warehouse_id == selected_warehouse.id,
                    )
                    .scalar()
                    or 0
                )

                if available_stock < item_form.quantity.data:
                    item_name = items_dict.get(item_id, {}).get("name", "Unknown Item")
                    flash(f"库存不足: {item_name}", "danger")
                    return render_template(
                        "inventory_stockout.html.jinja",
                        form=form,
                        items=items,
                    )

                transaction = Transaction(
                    itemSKU_id=item_id,
                    count=-item_form.quantity.data,  # Negative for stock out
                    price=item_form.price.data,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
            except ValueError:
                flash("无效的物品", "danger")
                return render_template(
                    "inventory_stockout.html.jinja",
                    form=form,
                    items=items,
                )

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()
        flash("出库成功。", "success")
        return redirect(url_for("inventory", warehouse=selected_warehouse.id))

    return render_template(
        "inventory_stockout.html.jinja",
        form=form,
        items=items,
    )


@app.route("/inventory/export")
@login_required
def inventory_export():
    # Admin can see inventory of all warehouses
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        # Regular users can only see public warehouses and their own warehouses
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

    # Get selected warehouse from query params
    selected_warehouse_id = request.args.get("warehouse", type=int)
    selected_warehouse = None

    if selected_warehouse_id:
        selected_warehouse = next(
            (w for w in warehouses if w.id == selected_warehouse_id),
            warehouses[0] if warehouses else None,
        )
    else:
        selected_warehouse = warehouses[0] if warehouses else None

    if not selected_warehouse:
        flash("未选择有效的仓库", "danger")
        return redirect(url_for("inventory"))

    # Build query to get inventory data
    query = (
        db.session.query(
            Item.name.label("item_name"),
            ItemSKU.id,
            ItemSKU.brand,
            ItemSKU.spec,
            WarehouseItemSKU.count,
        )
        .join(ItemSKU, WarehouseItemSKU.itemSKU_id == ItemSKU.id)
        .join(Item, ItemSKU.item_id == Item.id)
        .filter(
            and_(
                WarehouseItemSKU.warehouse_id == selected_warehouse.id,
                WarehouseItemSKU.count > 0,
            )
        )
    )

    # Apply filters from query string
    name = request.args.get("name", "")
    brand = request.args.get("brand", "")
    spec = request.args.get("spec", "")

    if name:
        query = query.filter(Item.name.ilike(f"%{name}%"))
    if brand:
        query = query.filter(ItemSKU.brand.ilike(f"%{brand}%"))
    if spec:
        query = query.filter(ItemSKU.spec.ilike(f"%{spec}%"))

    # Add ordering
    query = query.order_by(Item.name, ItemSKU.brand, ItemSKU.spec)

    # Execute query
    results = query.all()

    # Convert to DataFrame
    df = pd.DataFrame(
        [
            {
                "物品": row.item_name,
                "编号": row.id,
                "品牌": row.brand,
                "规格": row.spec,
                "数量": row.count,
            }
            for row in results
        ]
    )

    # Create Excel file in memory
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False, engine="openpyxl")
    excel_file.seek(0)

    # Generate filename
    filename = f"inventory_{selected_warehouse.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
