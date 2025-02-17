from wms import app, db
from wms.models import User, Item, ItemSKU, Warehouse, Receipt, Transaction, ReceiptType
from wms.forms import LoginForm, ItemSearchForm, ItemCreateForm, StockInForm
from flask import render_template, request, url_for, redirect, flash, session
from flask_login import login_required, login_user, logout_user, current_user
from sqlalchemy import select


@app.route("/")
@login_required
def index():
    return render_template("index.html.jinja")


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user: User = db.session.execute(
            select(User).filter_by(username=form.username.data)
        ).scalar_one_or_none()
        if (
            user is not None
            and user.validate_password(form.password.data)
            and login_user(user, remember=form.remember.data)
        ):
            flash("登录成功。", "success")
            return redirect(request.args.get("next") or url_for("index"))
        else:
            flash("用户名/密码错误。", "danger")
            return redirect(url_for("login"))
    else:
        form.remember.data = True
        return render_template("login.html.jinja", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("登出成功。", "success")
    return redirect(url_for("index"))


@app.route("/item", methods=["GET", "POST"])
@login_required
def item():
    if current_user.is_admin:
        form = ItemSearchForm()
        query = select(ItemSKU).join(Item)  # Always join with Item for sorting

        if form.validate_on_submit():
            # Store search parameters in session and start from page 1
            session["item_search"] = {
                "name": form.name.data,
                "brand": form.brand.data,
                "spec": form.spec.data,
            }
            # Redirect to GET request with page 1
            return redirect(
                url_for(
                    "item",
                    name=form.name.data,
                    brand=form.brand.data,
                    spec=form.spec.data,
                    page=1,
                )
            )
        elif request.method == "GET":
            # Restore form data from session or request args
            saved_search = session.get("item_search", {})
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

        page = 1 if request.args.get("page") is None else int(request.args.get("page"))
        items_pag = db.paginate(query, page=page)
        return render_template(
            "item.html.jinja", pagination=items_pag, itemSearchForm=form
        )
    else:
        flash("Unauthorized Access.")
        return redirect(url_for("index"))


@app.route("/item/create", methods=["GET", "POST"])
@login_required
def item_create():
    if not current_user.is_admin:
        flash("Unauthorized Access.")
        return redirect(url_for("index"))

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


@app.route("/stockin", methods=["GET", "POST"])
@login_required
def stockin():
    if not current_user.is_admin:
        flash("Unauthorized Access.")
        return redirect(url_for("index"))

    form = StockInForm()
    form.warehouse.choices = [(w.id, w.name) for w in Warehouse.query.all()]

    # Get all items with their display text
    skus = db.session.query(ItemSKU).join(Item).all()
    items = [(sku.id, f"{sku.item.name} - {sku.brand} - {sku.spec}") for sku in skus]
    items_dict = dict(items)

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
                return render_template("stockin.html.jinja", form=form, items=items)

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()

        flash("入库成功。", "success")
        return redirect(url_for("index"))

    return render_template("stockin.html.jinja", form=form, items=items)
