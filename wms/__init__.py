import os
from flask_bootstrap import Bootstrap5
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////" + os.path.join(
    os.path.dirname(app.root_path), os.getenv("DATABASE_FILE", "data.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.getenv("SECRET_KEY", "dev")
app.config["BOOTSTRAP_SERVE_LOCAL"] = True
bootstrap = Bootstrap5(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


db = SQLAlchemy(app, model_class=Base)


@login_manager.user_loader
def load_user(user_id):
    from wms.models import User

    user = db.session.get(User, int(user_id))
    return user


@app.context_processor
def inject_user():
    return dict(user=current_user)


from wms import routes, commands  # noqa
