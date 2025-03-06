from flask import render_template, url_for, redirect, flash, request
from flask_login import login_required
from sqlalchemy import select, distinct
from wms import app, db
from wms.utils import admin_required
from wms.models import Item, ItemSKU
from wms.forms import ItemSearchForm, ItemCreateForm


@app.route("/item", methods=["GET", "POST"])
@login_required
@admin_required
def item():
    # Get all unique item names for datalist
    item_names = (
        db.session.execute(select(distinct(Item.name)).order_by(Item.name))
        .scalars()
        .all()
    )

    form = ItemSearchForm()
    query = select(ItemSKU).join(Item)  # Always join with Item for sorting

    if form.validate_on_submit():
        # Redirect to GET request with search parameters
        return redirect(
            url_for(
                "item",
                name=form.name.data,
                brand=form.brand.data,
                spec=form.spec.data,
                page=1,
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

    page = 1 if request.args.get("page") is None else int(request.args.get("page"))
    items_pag = db.paginate(query, page=page)
    return render_template(
        "item.html.jinja",
        pagination=items_pag,
        itemSearchForm=form,
        item_names=item_names,
    )


@app.route("/item/create", methods=["GET", "POST"])
@login_required
@admin_required
def item_create():
    form = ItemCreateForm()
    # Get items for datalist
    items = db.session.execute(select(Item)).scalars()

    if form.validate_on_submit():
        if form.item_choice.data == "existing":
            # Find item by name
            item = db.session.execute(
                select(Item).filter_by(name=form.existing_item.data)
            ).scalar_one_or_none()
            if not item:
                flash("未找到指定物品。", "danger")
                return render_template("item_create.html.jinja", form=form, items=items)
            item_id = item.id
        else:
            # Create new item
            item = Item(name=form.new_item_name.data)
            db.session.add(item)
            db.session.flush()
            item_id = item.id

        # Create new SKU
        sku = ItemSKU(item_id=item_id, brand=form.brand.data, spec=form.spec.data)
        db.session.add(sku)
        db.session.commit()

        flash("物品添加成功。", "success")
        return redirect(url_for("item"))

    return render_template("item_create.html.jinja", form=form, items=items)
