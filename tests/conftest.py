import os
import pytest

# Set testing environment variable before importing the app
os.environ["TESTING"] = "True"

# Now import app and db
from wms import app, db  # noqa : E402
from wms.models import User, Item, ItemSKU, Warehouse, Area, Department  # noqa : E402
import uuid  # noqa : E402


@pytest.fixture(scope="function")
def client():
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
        item_name = f"Test Item {uuid.uuid4()}"
        item = Item(name=item_name)
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        db.session.commit()
        return item_name


@pytest.fixture
def test_another_item(client):
    with app.app_context():
        item_name = f"Another Test Item {uuid.uuid4()}"
        item = Item(name=item_name)
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Another Test Brand", spec="Another Test Spec")
        db.session.add(sku)
        db.session.commit()
        return item_name


@pytest.fixture
def auth_client(client, test_user):
    with app.app_context():
        client.post(
            "/login",
            data={"username": "testadmin", "password": "password123", "remember": "y"},
        )
        return client


@pytest.fixture
def test_warehouse(auth_client, test_user):
    with app.app_context():
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.commit()
        warehouse_id = warehouse.id  # Get the ID before closing the session
        return warehouse_id


@pytest.fixture
def regular_warehouse(auth_client, regular_user):
    with app.app_context():
        warehouse = Warehouse(name="Test Warehouse", owner=regular_user)
        db.session.add(warehouse)
        db.session.commit()
        warehouse_id = warehouse.id  # Get the ID before closing the session
        return warehouse_id


@pytest.fixture
def public_warehouse(auth_client):
    with app.app_context():
        warehouse = Warehouse(name="Public Warehouse", owner=None, is_public=True)
        db.session.add(warehouse)
        db.session.commit()
        warehouse_id = warehouse.id  # Get the ID before closing the session
        return warehouse_id


@pytest.fixture
def test_customer(auth_client):
    with app.app_context():
        # Create test areas and departments
        area = Area(name="Test Area")
        department = Department(name="Test Department")
        db.session.add_all([area, department])
        db.session.commit()
        return {"area": area.id, "department": department.id}
