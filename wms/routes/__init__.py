from flask import render_template
from flask_login import login_required
from wms import app

# Import all route modules to register them
from . import auth, inventory, item, records, batch  # noqa: F401


__all__ = ["auth", "item", "inventory", "records", "batch"]


@app.route("/")
@login_required
def index():
    return render_template("index.html.jinja")
