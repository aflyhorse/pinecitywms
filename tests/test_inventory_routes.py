import pytest
from wms.models import (
    Warehouse,
    ItemSKU,
    User,
    CustomerType,
    Receipt,
    ReceiptType,
)
from wms import app, db
from werkzeug.security import generate_password_hash


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


def test_stockout_page_access(auth_client):
    # Test stockout page access
    response = auth_client.get("/stockout")
    assert response.status_code == 200
    assert b"warehouse" in response.data  # Check for warehouse field
    assert b"customer_type" in response.data
    assert b"customer" in response.data


def test_customer_type_selection(auth_client, test_customer):
    # Test customer type selection functionality
    response = auth_client.post(
        "/stockout", data={"customer_type": "DEPARTMENT"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Test Department" in response.data


@pytest.mark.usefixtures("test_item")
def test_stockout_process(auth_client, test_warehouse, test_customer):
    # First add some inventory via stockin
    with app.app_context():
        sku = ItemSKU.query.first()

    # Add inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "STOCKOUT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "20",
            "items-0-price": "50.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now attempt to stockout
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,  # Added warehouse selection
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe5\x87\xba\xe5\xba\x93\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "出库成功" in UTF-8

    # Verify the inventory was reduced
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        warehouse_item = warehouse.item_skus[0]
        assert warehouse_item.count == 15  # 20 - 5 = 15


@pytest.mark.usefixtures("test_item")
def test_stockout_insufficient_stock(auth_client, test_warehouse, test_customer):
    # First add some inventory via stockin
    with app.app_context():
        sku = ItemSKU.query.first()

    # Add limited inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "STOCKOUT-TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "3",
            "items-0-price": "50.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now attempt to stockout more than available
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,  # Added warehouse selection
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "10",  # More than available
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    print(response.data)
    assert (
        b"\xe5\xba\x93\xe5\xad\x98\xe4\xb8\x8d\xe8\xb6\xb3" in response.data
    )  # "库存不足" in UTF-8


def test_stockout_invalid_item(
    auth_client, test_customer, test_warehouse
):  # Added test_warehouse parameter
    # Test with an invalid item ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,  # Added warehouse selection
            "customer_type": "GROUP",
            "customer": test_customer["group"],
            "items-0-item_id": "99999",  # Non-existent ID
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe6\x97\xa0\xe6\x95\x88\xe7\x9a\x84\xe7\x89\xa9\xe5\x93\x81" in response.data
    )  # "无效的物品" in UTF-8


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


@pytest.mark.usefixtures("test_item")
def test_non_admin_stockout_access(
    client, regular_user, regular_warehouse
):  # Added regular_warehouse
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to stockout (stockout should be accessible to non-admin users)
    response = client.get("/stockout")
    assert response.status_code == 200
    assert b"warehouse" in response.data  # Check for warehouse field
    assert b"customer_type" in response.data
    # Confirm we're on the stockout page
    assert b"\xe5\x87\xba\xe5\xba\x93" in response.data


@pytest.mark.usefixtures("test_item", "test_another_item")
def test_stockout_multiple_items(test_user, auth_client, test_warehouse, test_customer):
    # First add some inventory for multiple items
    with app.app_context():
        # Get first item
        item1 = ItemSKU.query.first()
        item2 = ItemSKU.query.filter(ItemSKU.id != item1.id).first()

    # Add inventory for first item
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "MULTI-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(item1.id),
            "items-0-quantity": "30",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Add inventory for second item
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "MULTI-TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": str(item2.id),
            "items-0-quantity": "20",
            "items-0-price": "150.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Now attempt to stockout multiple items
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,  # Added warehouse selection
            "customer_type": "DEPARTMENT",
            "customer": test_customer["department"],
            "items-0-item_id": str(item1.id),
            "items-0-quantity": "5",
            "items-0-price": "110.00",
            "items-1-item_id": str(item2.id),
            "items-1-quantity": "8",
            "items-1-price": "160.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe5\x87\xba\xe5\xba\x93\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "出库成功" in UTF-8

    # Verify the inventory was reduced for both items
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        items = warehouse.item_skus
        assert len(items) == 2
        for item in items:
            if item.itemSKU_id == item1.id:
                assert item.count == 25  # 30 - 5 = 25
            elif item.itemSKU_id == item2.id:
                assert item.count == 12  # 20 - 8 = 12


def test_customer_type_switching(
    auth_client, test_customer, test_warehouse
):  # Added test_warehouse parameter
    # Test switching between different customer types
    response = auth_client.post(
        "/stockout",
        data={
            "customer_type": "PUBLICAREA",
            "warehouse": test_warehouse,
        },  # Added warehouse selection
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Test Area" in response.data

    response = auth_client.post(
        "/stockout",
        data={
            "customer_type": "DEPARTMENT",
            "warehouse": test_warehouse,
        },  # Added warehouse selection
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Test Department" in response.data

    response = auth_client.post(
        "/stockout",
        data={
            "customer_type": "GROUP",
            "warehouse": test_warehouse,
        },  # Added warehouse selection
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Test Group" in response.data


@pytest.mark.usefixtures("test_item")
def test_stockout_receipt_creation(auth_client, test_warehouse, test_customer):
    # Add inventory
    with app.app_context():
        sku = ItemSKU.query.first()

    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "RECEIPT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "25",
            "items-0-price": "90.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        # Count receipts before stockout
        receipts_before = Receipt.query.filter_by(type=ReceiptType.STOCKOUT).count()

    # Perform stockout
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,  # Added warehouse selection
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "12",
            "items-0-price": "95.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Verify receipt was created properly
    with app.app_context():
        # Count should have increased
        receipts_after = Receipt.query.filter_by(type=ReceiptType.STOCKOUT).count()
        assert receipts_after == receipts_before + 1

        # Get the latest receipt
        receipt = (
            Receipt.query.filter_by(type=ReceiptType.STOCKOUT)
            .order_by(Receipt.id.desc())
            .first()
        )
        assert receipt is not None
        assert receipt.operator_id == 1  # admin user ID
        assert receipt.customer_id == test_customer["area"]  # Verify customer was saved
        assert receipt.customer.type == CustomerType.PUBLICAREA  # Verify customer type

        # Check transaction details
        transaction = receipt.transactions[0]
        assert transaction.count == -12  # Negative for stockout
        assert transaction.price == 95.00
        assert transaction.itemSKU_id == sku.id


def test_missing_warehouse_selection(auth_client, test_customer):
    # Test submitting without a warehouse
    response = auth_client.post(
        "/stockout",
        data={
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": "1",
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Form validation should catch the missing warehouse
    assert b"This field is required" in response.data


@pytest.mark.usefixtures("test_item")
def test_warehouse_item_availability(
    auth_client, test_warehouse, public_warehouse, test_customer
):
    # Create a second warehouse and add items only to that warehouse
    with app.app_context():
        sku = ItemSKU.query.first()

    # Add inventory to second warehouse only
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "WAREHOUSE-TEST-001",
            "warehouse": public_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "15",
            "items-0-price": "70.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now try to stockout from the first warehouse which shouldn't have the item
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Should show stock insufficient error
    assert (
        b"\xe5\xba\x93\xe5\xad\x98\xe4\xb8\x8d\xe8\xb6\xb3" in response.data
        or b"\xe6\x97\xa0\xe6\x95\x88\xe7\x9a\x84\xe7\x89\xa9\xe5\x93\x81" in response.data
    )  # "无效的物品" or "库存不足" in UTF-8

    # Try with the second warehouse which has the stock
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": public_warehouse,
            "customer_type": "PUBLICAREA",
            "customer": test_customer["area"],
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe5\x87\xba\xe5\xba\x93\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "出库成功" in UTF-8
