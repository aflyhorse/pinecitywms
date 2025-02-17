from flask import flash, redirect, url_for
from flask_login import current_user
from functools import wraps


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("Unauthorized Access.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function
