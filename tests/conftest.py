import pytest
from wms import app, db
from wms.models import User, Item, ItemSKU
import uuid


@pytest.fixture(scope="function")
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-key"

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()


@pytest.fixture
def test_user(client):
    with app.app_context():
        user = User(username="testadmin", nickname="Test Admin", is_admin=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user


@pytest.fixture
def regular_user(client):
    with app.app_context():
        user = User(username="testuser", nickname="Test User", is_admin=False)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user


@pytest.fixture
def test_item(client):
    with app.app_context():
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        db.session.commit()
        return item


@pytest.fixture
def auth_client(client, test_user):
    with app.app_context():
        client.post(
            "/login",
            data={"username": "testadmin", "password": "password123", "remember": "y"},
        )
        return client
