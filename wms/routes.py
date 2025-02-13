from wms import app, db
from wms.models import User, Item, ItemSKU
from wms.forms import LoginForm, ItemSearchForm
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
        query = select(ItemSKU).join(Item)
        page = 1
        if request.args.get("page") is not None:
            page = int(request.args.get("page"))
        if form.is_submitted():
            session["itemname"] = form.itemname.data
            session["itembrand"] = form.itembrand.data
            session["itemspec"] = form.itemspec.data
            page = 1
        if session.get("itemname"):
            query = query.where(Item.name.ilike(f"%{session.get('itemname')}%"))
            form.itemname.data = session.get("itemname")
        if session.get("itembrand"):
            query = query.where(ItemSKU.brand.ilike(f"%{session.get('itembrand')}%"))
            form.itembrand.data = session.get("itembrand")
        if session.get("itemspec"):
            query = query.where(ItemSKU.spec.ilike(f"%{session.get('itemspec')}%"))
            form.itemspec.data = session.get("itemspec")
        itemskus_pag = db.paginate(query, page=page, per_page=15)
        return render_template(
            "item.html.jinja", itemSearchForm=form, pagination=itemskus_pag
        )
    else:
        flash("Unauthorized Access.")
        return redirect(url_for("index"))
