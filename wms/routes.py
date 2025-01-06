from wms import app, db
from wms.models import User, Item
from wms.forms import LoginForm
from flask import render_template, request, url_for, redirect, flash
from flask_login import login_required, login_user, logout_user, current_user
from sqlalchemy import select


@app.route("/")
@login_required
def index():
    return render_template("index.html.jinja")


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm(request.form)
    if form.validate_on_submit():
        user: User = db.session.execute(
            select(User).filter_by(username=form.username.data)
        ).scalar_one_or_none()
        if (
            user is not None
            and user.validate_password(form.password.data)
            and login_user(user, remember=form.remember.data)
        ):
            flash("登录成功。")
            return redirect(request.args.get("next") or url_for("index"))
        else:
            flash("用户名/密码错误。")
            return redirect(url_for("login"))
    else:
        form.remember.data = True
        return render_template("login.html.jinja", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("登出成功。")
    return redirect(url_for("index"))


@app.route("/item", methods=["GET", "POST"])
@login_required
def item():
    if current_user.is_admin:
        page = 1
        if request.args.get("page") is not None:
            page = int(request.args.get("page"))
        items_pag = db.paginate(select(Item), page=page)
        return render_template("item.html.jinja", pagination=items_pag)
    else:
        flash("Unauthorized Access.")
        return redirect(url_for("index"))
