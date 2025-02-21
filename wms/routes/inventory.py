from flask import render_template, url_for, redirect, flash, request, session
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
)
from wms.forms import StockInForm, ItemSearchForm
from sqlalchemy import and_


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
            # Store search parameters in session and start from page 1
            session["inventory_search"] = {
                "name": form.name.data,
                "brand": form.brand.data,
                "spec": form.spec.data,
            }
            # Redirect to GET request with page 1
            return redirect(
                url_for(
                    "inventory",
                    warehouse=selected_warehouse.id,
                    name=form.name.data,
                    brand=form.brand.data,
                    spec=form.spec.data,
                    page=1,
                )
            )
        elif request.method == "GET":
            # Restore form data from session or request args
            saved_search = session.get("inventory_search", {})
            form.name.data = request.args.get("name", saved_search.get("name", ""))
            form.brand.data = request.args.get("brand", saved_search.get("brand", ""))
            form.spec.data = request.args.get("spec", saved_search.get("spec", ""))

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
    items_dict = dict(items)
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
                item_id = int(item_form.item_id.data)
                if item_id not in items_dict:
                    raise ValueError("Invalid item ID")

                transaction = Transaction(
                    itemSKU_id=item_id,
                    count=item_form.quantity.data,
                    price=item_form.price.data,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
            except ValueError:
                flash(f"无效的物品: {item_form.item_id.data}", "danger")
                return render_template(
                    "inventory_stockin.html.jinja", form=form, items=items
                )

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()

        flash("入库成功。", "success")
        return redirect(url_for("index"))

    return render_template("inventory_stockin.html.jinja", form=form, items=items)
