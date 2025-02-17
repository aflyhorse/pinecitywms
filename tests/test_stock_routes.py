import pytest
from wms.models import Warehouse, ItemSKU
from wms import app, db


@pytest.fixture
def test_warehouse(auth_client, test_user):
    with app.app_context():
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
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
        warehouse = db.session.get(Warehouse, test_warehouse)  # 使用新的 API
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
