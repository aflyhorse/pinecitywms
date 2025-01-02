from wms import app, db
from wms.models import User
from wms.forms import LoginForm
from flask import render_template, request, url_for, redirect, flash
from flask_login import login_required, login_user, logout_user


@app.route("/")
@login_required
def index():
    return render_template("index.html.jinja")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if not username or not password:
            flash("输入无效。")
            return redirect(url_for("login"))
        else:
            user: User = db.session.execute(
                db.select(User).filter_by(username=username)
            ).scalar_one()
            if user is None or not user.validate_password(password):
                flash("输入无效。")
                return redirect(url_for("login"))
            else:
                login_user(user)
                flash("登录成功。")
                return redirect(url_for("index"))
    else:
        return render_template("login.html.jinja", form=LoginForm())


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("登出成功。")
    return redirect(url_for("index"))
