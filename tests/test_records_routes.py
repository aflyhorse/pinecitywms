import pytest
from wms.models import Receipt, ReceiptType, Transaction, ItemSKU, Item
from wms import app, db


@pytest.mark.usefixtures("test_item")
def test_records_access_control(client, regular_user):
    # Test access as non-admin user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    response = client.get("/records", follow_redirects=True)
    assert response.status_code == 200  # Should be OK after redirect
    assert b"Unauthorized Access" in response.get_data()


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
