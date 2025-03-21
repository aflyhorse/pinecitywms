from flask import render_template, url_for, redirect, flash
from flask_login import login_required, login_user, logout_user, current_user
from wms import app, db
from wms.models import User
from wms.forms import LoginForm, PasswordChangeForm


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
            return redirect(
                url_for("inventory")
            )  # temporary direct to inventory when dashboard is not ready
            # return redirect(request.args.get("next") or url_for("inventory"))
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


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    form = PasswordChangeForm()

    # Populate username choices - admins see all users, regular users only see themselves
    if current_user.is_admin:
        users = User.query.all()
        form.username.choices = [
            (u.username, f"{u.username} ({u.nickname})") for u in users
        ]
    else:
        form.username.choices = [
            (
                current_user.username,
                f"{current_user.username} ({current_user.nickname})",
            )
        ]
        form.username.render_kw = {"readonly": True}

    if form.validate_on_submit():
        target_user = User.query.filter_by(username=form.username.data).first()
        if not target_user:
            flash("用户不存在。", "danger")
            return redirect(url_for("change_password"))

        # Admin can change any user's password without old password
        if current_user.is_admin:
            target_user.set_password(form.new_password.data)
            db.session.commit()
            flash(f"已成功修改用户 {target_user.username} 的密码。", "success")
            return redirect(url_for("index"))

        # Regular users must provide old password
        if not form.old_password.data:
            flash("请输入原密码。", "danger")
            return redirect(url_for("change_password"))

        if not target_user.validate_password(form.old_password.data):
            flash("原密码错误。", "danger")
            return redirect(url_for("change_password"))

        target_user.set_password(form.new_password.data)
        db.session.commit()
        flash("密码修改成功。", "success")
        return redirect(url_for("index"))

    return render_template("change_password.html.jinja", form=form)
