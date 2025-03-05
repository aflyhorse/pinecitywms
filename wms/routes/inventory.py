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
    Customer,
    CustomerType,
)
from wms.forms import StockInForm, ItemSearchForm, StockOutForm
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
        return redirect(url_for("inventory", warehouse=form.warehouse.data))

    return render_template("inventory_stockin.html.jinja", form=form, items=items)


@app.route("/stockout", methods=["GET", "POST"])
@login_required
def stockout():
    form = StockOutForm()
    # Get all customers and group them by type
    customers_by_type = {}
    for customer_type in CustomerType:
        customers_by_type[customer_type.name] = Customer.query.filter_by(
            type=customer_type
        ).all()

    # Get warehouses accessible by the current user
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public) | (Warehouse.owner_id == current_user.id)
        ).all()

    # Populate warehouse choices in the form
    form.warehouse.choices = [(w.id, w.name) for w in warehouses]

    # Initialize items list
    items = []

    # Get selected warehouse - either from form data (POST) or query parameters (GET)
    selected_warehouse_id = None
    if request.method == "POST":
        selected_warehouse_id = form.warehouse.data
    else:
        selected_warehouse_id = request.args.get("warehouse", type=int)
        if selected_warehouse_id:
            form.warehouse.data = selected_warehouse_id
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

    # Handle customer type selection
    if request.method == "POST":
        selected_type = form.customer_type.data
        if selected_type:  # Only update if type is selected
            type_customers = Customer.query.filter_by(
                type=CustomerType[selected_type]
            ).all()
            form.customer.choices = [(c.id, c.name) for c in type_customers]

            # If warehouse was changed, redirect to GET to update the item list
            if "warehouse" in request.form and not form.validate_on_submit():
                return redirect(url_for("stockout", warehouse=selected_warehouse_id))

    items_dict = {
        id: {"name": name, "price": price, "count": count}
        for id, name, price, count in items
    }

    if form.validate_on_submit():
        # Find customer by ID
        customer = db.session.get(Customer, form.customer.data)
        if not customer:
            flash("无效的客户选择", "danger")
            return render_template(
                "inventory_stockout.html.jinja",
                form=form,
                items=items,
                customers_by_type=customers_by_type,
            )

        # Get the selected warehouse
        selected_warehouse = db.session.get(Warehouse, form.warehouse.data)
        if not selected_warehouse:
            flash("请选择有效的仓库", "danger")
            return render_template(
                "inventory_stockout.html.jinja",
                form=form,
                items=items,
                customers_by_type=customers_by_type,
            )

        receipt = Receipt(
            operator=current_user,
            warehouse_id=selected_warehouse.id,
            type=ReceiptType.STOCKOUT,
            customer=customer,
        )
        db.session.add(receipt)
        db.session.flush()

        for item_form in form.items:
            try:
                item_id = int(item_form.item_id.data)
                if item_id not in items_dict:
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
                    flash(f"库存不足: {items_dict[item_id]['name']}", "danger")
                    return render_template(
                        "inventory_stockout.html.jinja",
                        form=form,
                        items=items,
                        customers_by_type=customers_by_type,
                    )

                transaction = Transaction(
                    itemSKU_id=item_id,
                    count=-item_form.quantity.data,  # Negative for stock out
                    price=item_form.price.data,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
            except ValueError:
                flash(f"无效的物品: {item_form.item_id.data}", "danger")
                return render_template(
                    "inventory_stockout.html.jinja",
                    form=form,
                    items=items,
                    customers_by_type=customers_by_type,
                )

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()
        flash("出库成功。", "success")
        return redirect(url_for("inventory", warehouse=selected_warehouse.id))
    else:
        # Set initial customer choices based on first customer type
        if not form.customer_type.data:  # Only set default if not already set
            first_type = CustomerType.PUBLICAREA  # Use public area as default
            form.customer_type.data = first_type.name
            type_customers = Customer.query.filter_by(type=first_type).all()
            form.customer.choices = [(c.id, c.name) for c in type_customers]

    return render_template(
        "inventory_stockout.html.jinja",
        form=form,
        items=items,
        customers_by_type=customers_by_type,
    )
