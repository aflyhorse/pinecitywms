import pytest
from wms.models import Receipt, ReceiptType, Transaction, ItemSKU, Item, User, Warehouse
from werkzeug.security import generate_password_hash
from wms import app, db
from datetime import datetime


@pytest.mark.usefixtures("test_item")
def test_records_access_control(client, regular_user, regular_warehouse):
    # Test access as regular (non-admin) user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Regular user should be able to access records page now
    response = client.get("/records", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" not in response.data
    assert (
        b"\xe6\x93\x8d\xe4\xbd\x9c\xe8\xae\xb0\xe5\xbd\x95" in response.data
    )  # "操作记录" in UTF-8

    with app.app_context():
        # Create another user and warehouse
        other_user = User(
            username="otheruser",
            nickname="Other User",
            password_hash=generate_password_hash("password123"),
            is_admin=False,
        )
        db.session.add(other_user)
        db.session.flush()

        # Create warehouse owned by the other user
        other_warehouse = Warehouse(name="Other Warehouse", owner=other_user)
        db.session.add(other_warehouse)
        db.session.flush()

        # Create public warehouse
        public_warehouse = Warehouse(name="Public Warehouse", is_public=True)
        db.session.add(public_warehouse)
        db.session.flush()

        # Get test item SKU
        sku = ItemSKU.query.first()

        # Create receipt in regular user's warehouse
        user_receipt = Receipt(
            operator=regular_user,
            refcode="USER-RECORD-TEST",
            warehouse_id=regular_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(user_receipt)
        db.session.flush()
        user_transaction = Transaction(
            itemSKU=sku, count=5, price=100.00, receipt=user_receipt
        )
        db.session.add(user_transaction)

        # Create receipt in other user's warehouse
        other_receipt = Receipt(
            operator=other_user,
            refcode="OTHER-RECORD-TEST",
            warehouse_id=other_warehouse.id,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(other_receipt)
        db.session.flush()
        other_transaction = Transaction(
            itemSKU=sku, count=10, price=50.00, receipt=other_receipt
        )
        db.session.add(other_transaction)

        # Create receipt in public warehouse
        public_receipt = Receipt(
            operator=other_user,
            refcode="PUBLIC-RECORD-TEST",
            warehouse_id=public_warehouse.id,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(public_receipt)
        db.session.flush()
        public_transaction = Transaction(
            itemSKU=sku, count=15, price=25.00, receipt=public_receipt
        )
        db.session.add(public_transaction)

        db.session.commit()

        # Store warehouse IDs for later assertions
        other_warehouse_id = other_warehouse.id
        public_warehouse_id = public_warehouse.id

    # Check regular user can see records from their own warehouse
    response = client.get(
        f"/records?type=stockin&warehouse={regular_warehouse}", follow_redirects=True
    )
    assert response.status_code == 200
    assert b"USER-RECORD-TEST" in response.data

    # Check regular user cannot see records from other user's private warehouse
    response = client.get(
        f"/records?type=stockin&warehouse={other_warehouse_id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert b"OTHER-RECORD-TEST" not in response.data

    # Check regular user can see records from public warehouse
    response = client.get(
        f"/records?type=stockin&warehouse={public_warehouse_id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert b"PUBLIC-RECORD-TEST" in response.data

    # Verify the "All Warehouses" option is not available to regular users
    response = client.get("/records", follow_redirects=True)
    assert (
        b"\xe5\x85\xa8\xe9\x83\xa8\xe4\xbb\x93\xe5\xba\x93" not in response.data
    )  # "全部仓库" (All Warehouses) in UTF-8


@pytest.mark.usefixtures("test_item")
def test_records_filtering(auth_client, test_warehouse, test_customer):
    with app.app_context():
        sku = ItemSKU.query.first()

        # First do a stockin
        receipt = Receipt(
            operator_id=1,  # admin user
            refcode="TEST-RECORDS-001",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()

        # Add transaction to stockin
        transaction = Transaction(itemSKU=sku, count=10, price=100.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

        # Then do a stockout
        receipt = Receipt(
            operator_id=1,  # admin user
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            customer_id=test_customer["area"],
        )
        db.session.add(receipt)
        db.session.flush()

        # Add transaction to stockout
        transaction = Transaction(itemSKU=sku, count=-5, price=100.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test stockin records filtering
    response = auth_client.get("/records?type=stockin")
    assert response.status_code == 200
    assert b"TEST-RECORDS-001" in response.data

    # Test stockout records filtering
    response = auth_client.get("/records?type=stockout")
    assert response.status_code == 200
    assert b"Test Area" in response.data  # Customer name should appear

    # Test warehouse filtering
    response = auth_client.get(f"/records?type=stockin&warehouse={test_warehouse}")
    assert response.status_code == 200
    assert b"TEST-RECORDS-001" in response.data

    # Test date range filtering
    response = auth_client.get(
        "/records?type=stockin&start_date=2024-01-01&end_date=2024-12-31"
    )
    assert response.status_code == 200

    # Test refcode filtering for stockin
    response = auth_client.get("/records?type=stockin&refcode=RECORDS")
    assert response.status_code == 200
    assert b"TEST-RECORDS-001" in response.data

    # Test customer filtering for stockout
    response = auth_client.get("/records?type=stockout&customer=Test")
    assert response.status_code == 200
    assert b"Test Area" in response.data


@pytest.mark.usefixtures("test_item")
def test_records_pagination(auth_client, test_warehouse):
    with app.app_context():
        sku = ItemSKU.query.first()
        # Create a receipt with multiple transactions
        receipt = Receipt(
            operator_id=1,  # admin user
            refcode="TEST-RECORDS-002",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()

        # Add 25 transactions (more than per_page)
        for i in range(25):
            transaction = Transaction(
                itemSKU=sku, count=i + 1, price=10.00, receipt=receipt
            )
            db.session.add(transaction)
        db.session.commit()

    # Test first page
    response = auth_client.get("/records?type=stockin&page=1")
    assert response.status_code == 200
    # Our per_page is 20, so we should see exactly 20 items
    assert response.data.count(b"<tr>") == 21  # 20 data rows + 1 header row

    # Test second page
    response = auth_client.get("/records?type=stockin&page=2")
    assert response.status_code == 200
    # We should see the remaining 5 items
    assert response.data.count(b"<tr>") == 6  # 5 data rows + 1 header row


@pytest.mark.usefixtures("test_item")
def test_statistics_access_control(client, regular_user):
    # Test access as non-admin user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    response = client.get("/statistics_fee", follow_redirects=True)
    assert response.status_code == 200  # Should be OK after redirect
    assert b"Unauthorized Access" in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_page_access(auth_client):
    # Test statistics page access
    response = auth_client.get("/statistics_fee")
    assert response.status_code == 200
    # Check for key elements on the page
    assert b"start_date" in response.data
    assert b"end_date" in response.data
    assert b"current-year" in response.data
    assert b"last-year" in response.data
    assert b"current-month" in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_date_filtering(auth_client, test_warehouse, test_customer):
    # Create stockout data to test statistics
    with app.app_context():
        sku = ItemSKU.query.first()

        # Create a stockout receipt
        receipt = Receipt(
            operator_id=1,  # admin user
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            customer_id=test_customer["area"],
        )
        db.session.add(receipt)
        db.session.flush()

        # Add transaction to stockout
        transaction = Transaction(itemSKU=sku, count=-15, price=100.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test with date range that should include our data
    from datetime import datetime, timedelta

    today = datetime.now().date()
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    response = auth_client.get(
        f"/statistics_fee?start_date={start_date}&end_date={end_date}"
    )
    assert response.status_code == 200

    # With data we should see the customer name and warehouse name
    assert b"Test Area" in response.data
    assert b"Test Warehouse" in response.data

    # Verify the total value is displayed
    assert b"1500.00" in response.data  # 15 * 100.00 = 1500.00


@pytest.mark.usefixtures("test_item")
def test_statistics_shortcut_buttons(auth_client):
    # Test statistics page with date shortcut buttons
    response = auth_client.get("/statistics_fee")
    assert response.status_code == 200

    # Check that JavaScript correctly sets up the date filter buttons
    assert b"current-year" in response.data
    assert b"last-year" in response.data
    assert b"current-month" in response.data
    assert b"last-month" in response.data

    # Verify JS functionality is included
    assert b"getFirstDayOfMonth" in response.data
    assert b"getLastDayOfMonth" in response.data
    assert b"getFirstDayOfYear" in response.data
    assert b"getLastDayOfYear" in response.data


@pytest.mark.usefixtures("test_item", "test_another_item")
def test_records_item_and_sku_filtering(auth_client, test_warehouse):
    # This test checks the newly added item name and SKU description filtering capabilities

    # Setup test data with distinct item names, brands and specs
    with app.app_context():
        # Get our test items
        sku1 = ItemSKU.query.first()  # First test item
        sku2 = ItemSKU.query.filter(ItemSKU.id != sku1.id).first()  # Second test item

        # Create stockin receipts with unique refcodes for clearer testing
        # Receipt for first item
        receipt1 = Receipt(
            operator_id=1,  # admin user
            refcode="FILTER-TEST-ITEM1",  # Unique refcode for first item
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt1)
        db.session.flush()
        transaction1 = Transaction(
            itemSKU=sku1, count=10, price=100.00, receipt=receipt1
        )
        db.session.add(transaction1)

        # Receipt for second item with different item name
        receipt2 = Receipt(
            operator_id=1,  # admin user
            refcode="FILTER-TEST-ITEM2",  # Unique refcode for second item
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt2)
        db.session.flush()
        transaction2 = Transaction(itemSKU=sku2, count=5, price=50.00, receipt=receipt2)
        db.session.add(transaction2)

        db.session.commit()

        # Store item names for assertions
        item1_name = sku1.item.name

    # Test filtering by item name
    response = auth_client.get(f"/records?item_name={item1_name}&type=stockin")
    assert response.status_code == 200
    # Check that the first item's refcode is in the response
    assert b"FILTER-TEST-ITEM1" in response.data
    # Check that the second item's refcode is not in the response
    assert b"FILTER-TEST-ITEM2" not in response.data

    # Test that datalist for item names is included in the response
    response = auth_client.get("/records")
    assert response.status_code == 200
    assert b'<datalist id="item-names">' in response.data

    # Test combining multiple filters
    response = auth_client.get(
        f"/records?item_name={item1_name}&type=stockin&warehouse={test_warehouse}"
    )
    assert response.status_code == 200
    assert b"FILTER-TEST-ITEM1" in response.data
    assert b"FILTER-TEST-ITEM2" not in response.data

    # Add test for the sku_desc filter with unique values
    with app.app_context():
        # Create a new item with a unique brand for testing sku_desc filter
        new_item = Item(name="Unique Filter Item")
        db.session.add(new_item)
        db.session.flush()

        unique_sku = ItemSKU(
            item=new_item,
            brand="UNIQUE-BRAND-FOR-TESTING",
            spec="UNIQUE-SPEC-FOR-TESTING",
        )
        db.session.add(unique_sku)
        db.session.flush()

        # Create a receipt for this unique SKU
        unique_receipt = Receipt(
            operator_id=1,
            refcode="UNIQUE-FILTER-SKU-TEST",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(unique_receipt)
        db.session.flush()

        unique_transaction = Transaction(
            itemSKU=unique_sku, count=3, price=75.00, receipt=unique_receipt
        )
        db.session.add(unique_transaction)
        db.session.commit()

    # Test filtering by unique brand
    response = auth_client.get(
        "/records?sku_desc=UNIQUE-BRAND-FOR-TESTING&type=stockin"
    )
    assert response.status_code == 200
    assert b"UNIQUE-FILTER-SKU-TEST" in response.data
    assert b"FILTER-TEST-ITEM1" not in response.data
    assert b"FILTER-TEST-ITEM2" not in response.data

    # Test filtering by unique spec
    response = auth_client.get("/records?sku_desc=UNIQUE-SPEC-FOR-TESTING&type=stockin")
    assert response.status_code == 200
    assert b"UNIQUE-FILTER-SKU-TEST" in response.data
    assert b"FILTER-TEST-ITEM1" not in response.data
    assert b"FILTER-TEST-ITEM2" not in response.data


@pytest.mark.usefixtures("test_item")
def test_export_records(auth_client, test_warehouse, test_customer):
    # Create test data and store necessary values
    item_name = None
    sku_brand = None

    with app.app_context():
        sku = ItemSKU.query.first()
        # Store values we'll need later while in session
        item_name = sku.item.name
        sku_brand = sku.brand

        # Create a stockin receipt
        stockin_receipt = Receipt(
            operator_id=1,  # admin user
            refcode="EXPORT-TEST-IN",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(stockin_receipt)
        db.session.flush()

        # Add transaction to stockin
        stockin_trans = Transaction(
            itemSKU=sku, count=10, price=100.00, receipt=stockin_receipt
        )
        db.session.add(stockin_trans)

        # Create a stockout receipt
        stockout_receipt = Receipt(
            operator_id=1,
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            customer_id=test_customer["area"],
        )
        db.session.add(stockout_receipt)
        db.session.flush()

        # Add transaction to stockout
        stockout_trans = Transaction(
            itemSKU=sku, count=-5, price=120.00, receipt=stockout_receipt
        )
        db.session.add(stockout_trans)
        db.session.commit()

    # Test export stockin records
    response = auth_client.get("/export_records?type=stockin")
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=records_"
    )
    assert isinstance(response.data, bytes)

    # Test export stockout records
    response = auth_client.get("/export_records?type=stockout")
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=records_"
    )
    assert isinstance(response.data, bytes)

    # Test with warehouse filter
    response = auth_client.get(
        f"/export_records?type=stockin&warehouse={test_warehouse}"
    )
    assert response.status_code == 200
    assert "records_Test Warehouse_" in response.headers["Content-Disposition"]

    # Test with date range
    today = datetime.now().strftime("%Y-%m-%d")
    response = auth_client.get(
        f"/export_records?type=stockout&start_date={today}&end_date={today}"
    )
    assert response.status_code == 200

    # Test with customer filter for stockout
    response = auth_client.get("/export_records?type=stockout&customer=Test")
    assert response.status_code == 200

    # Test with item name filter
    response = auth_client.get(f"/export_records?item_name={item_name}")
    assert response.status_code == 200

    # Test with SKU description filter
    response = auth_client.get(f"/export_records?sku_desc={sku_brand}")
    assert response.status_code == 200


@pytest.mark.usefixtures("test_item")
def test_export_records_access_control(client, regular_user, regular_warehouse):
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Regular user should be able to export records
    response = client.get("/export_records")
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Create another warehouse that the user shouldn't have access to
    with app.app_context():
        other_user = User(
            username="otherwarehouse",
            nickname="Other Warehouse Owner",
            password_hash=generate_password_hash("password123"),
            is_admin=False,
        )
        db.session.add(other_user)
        db.session.flush()

        other_warehouse = Warehouse(name="Other Warehouse", owner=other_user)
        db.session.add(other_warehouse)
        db.session.commit()

        other_warehouse_id = other_warehouse.id

    # Try to export from unauthorized warehouse - should silently exclude unauthorized data
    response = client.get(f"/export_records?warehouse={other_warehouse_id}")
    assert (
        response.status_code == 200
    )  # Should still work but exclude unauthorized data
