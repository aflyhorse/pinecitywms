from flask import render_template, url_for, redirect, flash, request, jsonify
from flask_login import login_required
from sqlalchemy import select, distinct, desc
from wms import app, db
from wms.utils import admin_required, _escape_like
from wms.models import Item, ItemSKU, ToolInventory
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
                sku_id=form.sku_id.data,
                page=1,
            )
        )

    # Get search parameters from query string
    form.name.data = request.args.get("name", "")
    form.brand.data = request.args.get("brand", "")
    form.spec.data = request.args.get("spec", "")
    form.sku_id.data = request.args.get("sku_id", "")

    # Apply filters if there's search data
    if form.name.data:
        esc = _escape_like(form.name.data)
        query = query.filter(Item.name.ilike(f"%{esc}%", escape="\\"))
    if form.brand.data:
        esc = _escape_like(form.brand.data)
        query = query.filter(ItemSKU.brand.ilike(f"%{esc}%", escape="\\"))
    if form.spec.data:
        esc = _escape_like(form.spec.data)
        query = query.filter(ItemSKU.spec.ilike(f"%{esc}%", escape="\\"))
    if form.sku_id.data:
        try:
            sku_id_int = int(form.sku_id.data)
            query = query.filter(ItemSKU.id == sku_id_int)
        except ValueError:
            pass  # Ignore invalid SKU ID

    # Order by Item.id in descending order
    query = query.order_by(desc(Item.id), desc(ItemSKU.id))

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
        # Check if item with this name already exists
        item = db.session.execute(
            select(Item).filter_by(name=form.item_name.data)
        ).scalar_one_or_none()

        if not item:
            # Create new item if it doesn't exist
            item = Item(name=form.item_name.data, is_tool=form.is_tool.data)
            db.session.add(item)
            db.session.flush()
        else:
            # Update is_tool status if item exists and is_tool was checked
            if form.is_tool.data and not item.is_tool:
                item.is_tool = True

        # Check if SKU with same brand and spec already exists for this item
        existing_sku = db.session.execute(
            select(ItemSKU).filter_by(
                item_id=item.id, brand=form.brand.data, spec=form.spec.data
            )
        ).scalar_one_or_none()

        if existing_sku:
            if existing_sku.disabled:
                # Re-enable the disabled SKU instead of creating a new one
                existing_sku.disabled = False
                db.session.commit()
                flash("对应型号已修改为启用", "success")
                return redirect(url_for("item"))
            else:
                # SKU is already enabled
                flash("物品和对应型号已存在", "danger")
                return render_template("item_create.html.jinja", form=form, items=items)

        # Create new SKU for the item
        sku = ItemSKU(item_id=item.id, brand=form.brand.data, spec=form.spec.data)
        db.session.add(sku)
        db.session.commit()

        flash("物品添加成功。", "success")
        return redirect(url_for("item"))

    return render_template("item_create.html.jinja", form=form, items=items)


@app.route("/item/<int:itemSKU_id>/toggle_disabled", methods=["POST"])
@login_required
@admin_required
def toggle_disabled(itemSKU_id):
    # Find the item SKU
    item_sku = db.session.get(ItemSKU, itemSKU_id)

    if not item_sku:
        return jsonify({"success": False, "message": "物品不存在"}), 404

    # Toggle the disabled status
    item_sku.disabled = not item_sku.disabled
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "disabled": item_sku.disabled,
            "message": "物品已{}。".format("禁用" if item_sku.disabled else "启用"),
        }
    )


@app.route("/item/<int:item_id>/toggle_tool", methods=["POST"])
@login_required
@admin_required
def toggle_tool(item_id):
    """Toggle whether an item is classified as a tool."""
    item = db.session.get(Item, item_id)
    if not item:
        return jsonify({"success": False, "message": "物品不存在"}), 404

    item.is_tool = not item.is_tool

    if item.is_tool:
        # Seed ToolInventory from current warehouse stock (one row per group-user per SKU)
        for sku in item.skus:
            for wis in sku.warehouses:
                owner_id = wis.warehouse.owner_id
                if not owner_id or wis.count <= 0:
                    continue  # skip public warehouses and empty stock
                ti = ToolInventory.query.filter_by(
                    user_id=owner_id, itemSKU_id=sku.id
                ).first()
                if ti is None:
                    ti = ToolInventory(
                        user_id=owner_id,
                        itemSKU_id=sku.id,
                        count=wis.count,
                        pending_scrap=0,
                    )
                    db.session.add(ti)
                else:
                    ti.count = wis.count  # resync if toggled off and back on
    else:
        # Remove tool inventory rows when un-marking
        for sku in item.skus:
            ToolInventory.query.filter_by(itemSKU_id=sku.id).delete()
    db.session.commit()
    return jsonify(
        {
            "success": True,
            "is_tool": item.is_tool,
            "message": "已标记为工具" if item.is_tool else "已取消工具标记",
        }
    )
