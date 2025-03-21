import os
from flask_bootstrap import Bootstrap5
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////" + os.path.join(
    os.path.dirname(app.root_path), os.getenv("DATABASE_FILE", "data.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Configure connection pool
app.config["SQLALCHEMY_POOL_SIZE"] = 10  # Maximum number of database connections to keep
app.config["SQLALCHEMY_POOL_TIMEOUT"] = 30  # Seconds to wait before timing out
app.config["SQLALCHEMY_POOL_RECYCLE"] = 1800  # Recycle connections after 30 minutes
app.config["SQLALCHEMY_MAX_OVERFLOW"] = 20  # Maximum number of connections to create beyond pool_size
app.secret_key = os.getenv("SECRET_KEY", "dev")
app.config["BOOTSTRAP_SERVE_LOCAL"] = True
bootstrap = Bootstrap5(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
db = SQLAlchemy(app)


@login_manager.user_loader
def load_user(user_id):
    from wms.models import User

    user = db.session.get(User, int(user_id))
    return user


@app.context_processor
def inject_user():
    return dict(user=current_user)


from wms import routes, commands  # noqa : F401
