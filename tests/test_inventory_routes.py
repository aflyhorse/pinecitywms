import pytest
from wms.models import Warehouse, ItemSKU, User, Receipt, ReceiptType, Transaction
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
    assert "入库成功".encode() in response.data

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
    assert "无效的物品".encode() in response.data


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
    assert b"area" in response.data  # Check for area field
    assert b"department" in response.data  # Check for department field
    assert b"location" in response.data  # Check for location field


def test_area_department_selection(auth_client, test_customer):
    # Test area and department selection functionality
    response = auth_client.post(
        "/stockout", data={"area": test_customer["area"]}, follow_redirects=True
    )
    assert response.status_code == 200


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
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

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
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "10",  # More than available
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "库存不足".encode() in response.data


def test_stockout_invalid_item(auth_client, test_customer, test_warehouse):
    # Test with an invalid item ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": "99999",  # Non-existent ID
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "无效的物品".encode() in response.data


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
def test_non_admin_stockout_access(client, regular_user, regular_warehouse):
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to stockout (stockout should be accessible to non-admin users)
    response = client.get("/stockout")
    assert response.status_code == 200
    assert b"warehouse" in response.data  # Check for warehouse field
    assert b"area" in response.data
    assert b"department" in response.data
    # Confirm we're on the stockout page
    assert "出库".encode() in response.data


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
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
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
    assert "出库成功".encode() in response.data

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


def test_area_department_switching(auth_client, test_customer, test_warehouse):
    # Test selecting different areas and departments
    response = auth_client.post(
        "/stockout",
        data={
            "area": test_customer["area"],
            "warehouse": test_warehouse,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    response = auth_client.post(
        "/stockout",
        data={
            "department": test_customer["department"],
            "warehouse": test_warehouse,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200


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
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "12",
            "items-0-price": "95.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

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
        assert receipt.area_id == test_customer["area"]  # Verify area was saved
        assert (
            receipt.department_id == test_customer["department"]
        )  # Verify department was saved
        assert receipt.location == "测试地点"  # Verify location was saved

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
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
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
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "库存不足".encode() in response.data or "无效的物品".encode() in response.data

    # Try with the second warehouse which has the stock
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": public_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_stockin_with_invalid_item_format(auth_client, test_warehouse):
    # Test with a non-numeric item ID that will trigger the ValueError exception
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-003",
            "warehouse": test_warehouse,
            "items-0-item_id": "not-a-number",  # Invalid format that will cause ValueError
            "items-0-quantity": "5",
            "items-0-price": "80.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "无效的物品".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_stockout_invalid_area_and_department(auth_client, test_warehouse):
    """Test stockout with invalid area and department IDs to cover error handling paths"""
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_id = sku.id
        # First add inventory so we can attempt stockout
        receipt = Receipt(
            operator_id=1,
            refcode="INVALID-AREA-TEST",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()
        transaction = Transaction(itemSKU=sku, count=20, price=50.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test with invalid area ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": 999,  # Non-existent area ID
            "department": 1,
            "location": "测试地点",
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data

    # Test with invalid department ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": 1,
            "department": 999,  # Non-existent department ID
            "location": "测试地点",
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data

    # Test with missing warehouse selection
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": 999,  # Non-existent warehouse ID
            "area": 1,
            "department": 1,
            "location": "测试地点",
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data
