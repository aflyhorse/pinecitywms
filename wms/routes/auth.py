from flask import render_template, request, url_for, redirect, flash
from flask_login import login_required, login_user, logout_user
from wms import app
from wms.models import User
from wms.forms import LoginForm


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user: User = User.query.filter_by(username=form.username.data).first()
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
