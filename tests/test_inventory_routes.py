import pytest
from wms.models import Warehouse, ItemSKU, User
from wms import app, db
from werkzeug.security import generate_password_hash


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


@pytest.mark.usefixtures("test_item")
def test_stockin(auth_client, test_warehouse):
    # Test stockin page access
    response = auth_client.get("/stockin")
    assert response.status_code == 200

    # Get test item SKU
    with app.app_context():
        sku = ItemSKU.query.first()

    # Test stockin submission
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "10",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe5\x85\xa5\xe5\xba\x93\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "入库成功" in UTF-8

    # Verify the warehouse item count
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        warehouse_item = warehouse.item_skus[0]
        assert warehouse_item.count == 10
        assert warehouse_item.average_price == 100.00


def test_stockin_validation(auth_client, test_warehouse):
    # Test invalid item ID
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": "99999",  # Non-existent ID
            "items-0-quantity": "10",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe6\x97\xa0\xe6\x95\x88\xe7\x9a\x84\xe7\x89\xa9\xe5\x93\x81" in response.data
    )  # "无效的物品" in UTF-8


def test_non_admin_stockin_access(client, regular_user):
    # Login as non-admin user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to stockin
    response = client.get("/stockin", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" in response.data


def test_inventory(auth_client, test_warehouse, test_item):
    # Test inventory page access
    response = auth_client.get("/inventory")
    assert response.status_code == 200

    # Add some inventory to test with
    sku = ItemSKU.query.first()
    # First add some stock via stockin
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "INV-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "50",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Test inventory view with search parameters
    response = auth_client.post(
        "/inventory",
        data={
            "name": sku.item.name,
            "brand": sku.brand,
            "spec": sku.spec,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert sku.item.name.encode() in response.data
    assert sku.brand.encode() in response.data
    assert sku.spec.encode() in response.data
    assert b"50" in response.data  # Check quantity is shown

    # Test warehouse selection
    response = auth_client.get(f"/inventory?warehouse={test_warehouse}")
    assert response.status_code == 200


def test_inventory_access_control(client, regular_user, regular_warehouse):
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to inventory
    response = client.get("/inventory")
    assert response.status_code == 200

    # Create another user and their warehouse
    otherwarehouse_id = None
    otherwarehouse_name = "Other Warehouse"
    with app.app_context():
        other_user = User(
            username="otherwarehouse",
            nickname="Other Warehouse Owner",
            password_hash=generate_password_hash("password123"),
            is_admin=False,
        )
        db.session.add(other_user)
        db.session.flush()  # Flush to get the user ID

        # Create warehouse owned by the other user
        otherwarehouse = Warehouse(name=otherwarehouse_name, owner=other_user)
        db.session.add(otherwarehouse)
        db.session.flush()
        otherwarehouse_id = otherwarehouse.id

    # Regular user should not see the private warehouse owned by other_user
    response = client.get(f"/inventory?warehouse={otherwarehouse_id}")
    assert response.status_code == 200
    assert otherwarehouse_name.encode() not in response.data
