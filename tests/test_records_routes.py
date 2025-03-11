import pytest
from wms.models import Receipt, ReceiptType, Transaction, ItemSKU, Item, User, Warehouse
from werkzeug.security import generate_password_hash
from wms import app, db
from datetime import datetime, timedelta


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
    assert "操作记录".encode() in response.data

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
            area_id=test_customer["area"],
            department_id=test_customer["department"],
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
            area_id=test_customer["area"],
            department_id=test_customer["department"],
        )
        db.session.add(receipt)
        db.session.flush()

        # Add transaction to stockout
        transaction = Transaction(itemSKU=sku, count=-15, price=100.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test with date range that should include our data

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
    with app.app_context():
        sku = ItemSKU.query.first()

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
            area_id=test_customer["area"],
            department_id=test_customer["department"],
        )
        db.session.add(stockout_receipt)
        db.session.flush()

        # Add transaction to stockout
        stockout_trans = Transaction(
            itemSKU=sku, count=-5, price=110.00, receipt=stockout_receipt
        )
        db.session.add(stockout_trans)

        db.session.commit()

    # Test export stockin records
    response = auth_client.get("/export_records?type=stockin")
    assert response.status_code == 200
    # Check that we received an Excel file
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in response.content_type
    )
    assert "attachment" in response.headers.get("Content-Disposition", "")

    # Test export stockout records
    response = auth_client.get("/export_records?type=stockout")
    assert response.status_code == 200
    # Check that we received an Excel file
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in response.content_type
    )
    assert "attachment" in response.headers.get("Content-Disposition", "")

    # Test with filtering
    response = auth_client.get(
        f"/export_records?type=stockout&warehouse={test_warehouse}"
    )
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


@pytest.mark.usefixtures("test_item")
def test_default_warehouse_redirection(client, regular_user, regular_warehouse):
    """Test the auto-redirection when a regular user has no warehouse selected"""
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Access records without specifying a warehouse - should auto redirect to default
    response = client.get(
        "/records", follow_redirects=False
    )  # Don't follow redirects so we can check redirect URL
    assert response.status_code == 302  # Should redirect
    assert (
        f"warehouse={regular_warehouse}" in response.location
    )  # Should contain the default warehouse


@pytest.mark.usefixtures("test_item")
def test_statistics_with_no_date_range(auth_client):
    """Test statistics when no date range is provided, resulting in default current month"""
    # Access statistics without providing date range
    response = auth_client.get("/statistics_fee")
    assert response.status_code == 200

    # Check for current month/year in the response
    today = datetime.now()
    current_year = today.year
    current_month = today.month

    # Convert month to string with leading zero if needed
    month_str = f"{current_month:02d}"

    # These should be in the input fields as default values
    assert (
        f"{current_year}-{month_str}-01".encode() in response.data
    )  # First day of current month

    # Verify script contains current year and month variables
    assert f"const currentYear = {current_year};".encode() in response.data
    assert f"const currentMonth = {current_month};".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_with_missing_area_department(auth_client, test_warehouse):
    """Test statistics when some receipts have no area or department"""
    with app.app_context():
        sku = ItemSKU.query.first()
        # Create a stockout receipt without area and department
        incomplete_receipt = Receipt(
            operator_id=1,  # admin user
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            # Intentionally omitting area_id and department_id
        )
        db.session.add(incomplete_receipt)
        db.session.flush()

        # Add transaction to the incomplete receipt
        transaction = Transaction(
            itemSKU=sku, count=-3, price=50.00, receipt=incomplete_receipt
        )
        db.session.add(transaction)
        db.session.commit()

    # Access statistics page - should handle null area/department gracefully
    today = datetime.now().date()
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    response = auth_client.get(
        f"/statistics_fee?start_date={start_date}&end_date={end_date}"
    )
    assert response.status_code == 200
    # The page should load successfully even with incomplete receipts


@pytest.mark.usefixtures("test_item")
def test_export_records_with_filters(auth_client, test_warehouse, test_customer):
    """Test exporting records with various filtering options to improve coverage"""
    with app.app_context():
        sku = ItemSKU.query.first()

        # Create a stock receipt with a specific refcode for filtering
        special_receipt = Receipt(
            operator_id=1,
            refcode="SPECIAL-EXPORT-TEST",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(special_receipt)
        db.session.flush()
        special_trans = Transaction(
            itemSKU=sku, count=8, price=80.00, receipt=special_receipt
        )
        db.session.add(special_trans)

        # Create a stockout receipt with location information
        special_out = Receipt(
            operator_id=1,
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            area_id=test_customer["area"],
            department_id=test_customer["department"],
            location="Special Location Test",
        )
        db.session.add(special_out)
        db.session.flush()
        special_out_trans = Transaction(
            itemSKU=sku, count=-4, price=90.00, receipt=special_out
        )
        db.session.add(special_out_trans)

        db.session.commit()

        item_name = sku.item.name

    # Test export with refcode filter - this should hit line 383
    response = auth_client.get("/export_records?type=stockin&refcode=SPECIAL-EXPORT")
    assert response.status_code == 200

    # Test export with date filters - this should hit lines 373-376
    today = datetime.now().date()
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    response = auth_client.get(
        f"/export_records?start_date={start_date}&end_date={end_date}"
    )
    assert response.status_code == 200

    # Test export with location filter - this should hit lines 379-380
    response = auth_client.get(
        "/export_records?type=stockout&location_info=Special+Location"
    )
    assert response.status_code == 200

    # Test export with item name filter - this should hit line 386
    response = auth_client.get(f"/export_records?item_name={item_name}")
    assert response.status_code == 200

    # Test export with sku description filter - this should hit line 389
    response = auth_client.get(f"/export_records?sku_desc={sku.brand}")
    assert response.status_code == 200


@pytest.mark.usefixtures("test_item")
def test_statistics_usage_access(auth_client):
    """Test basic access to statistics_usage page"""
    response = auth_client.get("/statistics_usage")
    assert response.status_code == 200
    assert "用量统计".encode() in response.data
    # Check for filter form elements
    assert b'name="start_date"' in response.data
    assert b'name="end_date"' in response.data
    assert b'name="item_name"' in response.data
    assert b'name="brand"' in response.data
    assert b'name="spec"' in response.data
    # Check for shortcut buttons
    assert b'id="current-year"' in response.data
    assert b'id="last-year"' in response.data
    assert b'id="current-month"' in response.data
    assert b'id="last-month"' in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_usage_default_date(auth_client):
    """Test that default date range is set to current month"""
    response = auth_client.get("/statistics_usage")
    assert response.status_code == 200

    # Check for current month/year in the response
    today = datetime.now()
    current_year = today.year
    current_month = today.month
    month_str = f"{current_month:02d}"

    # First day of current month should be the default start date
    assert f"{current_year}-{month_str}-01".encode() in response.data

    # Verify script contains current year and month variables
    assert f"const currentYear = {current_year};".encode() in response.data
    assert f"const currentMonth = {current_month};".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_usage_warehouse_access(client, regular_user, regular_warehouse):
    """Test warehouse access control for regular users"""
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Create another private warehouse
    with app.app_context():
        other_user = User(
            username="otherwarehouse",
            nickname="Other User",
            password_hash=generate_password_hash("password123"),
            is_admin=False,
        )
        db.session.add(other_user)
        db.session.flush()

        other_warehouse = Warehouse(name="Other Private Warehouse", owner=other_user)
        db.session.add(other_warehouse)

        public_warehouse = Warehouse(name="Public Test Warehouse", is_public=True)
        db.session.add(public_warehouse)
        db.session.commit()

        other_warehouse_id = other_warehouse.id
        public_warehouse_id = public_warehouse.id

    # Regular user should be redirected to their default warehouse
    response = client.get("/statistics_usage", follow_redirects=False)
    assert response.status_code == 302  # Should redirect
    assert (
        f"warehouse={regular_warehouse}" in response.location
    )  # Should redirect to default warehouse

    # Following the redirect should show the page
    response = client.get(response.location, follow_redirects=True)
    assert response.status_code == 200

    # Should see their own warehouse and public warehouse
    assert "Public Test Warehouse".encode() in response.data
    assert (
        "全部仓库".encode() not in response.data
    )  # Regular users can't see "All Warehouses"

    # Should not see other user's private warehouse
    response = client.get(f"/statistics_usage?warehouse={other_warehouse_id}")
    assert response.status_code == 200
    assert "Other Private Warehouse".encode() not in response.data

    # Should see public warehouse data
    response = client.get(f"/statistics_usage?warehouse={public_warehouse_id}")
    assert response.status_code == 200
    assert "Public Test Warehouse".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_usage_data_accuracy(auth_client, test_warehouse, test_customer):
    """Test that usage statistics are calculated correctly"""
    with app.app_context():
        sku = ItemSKU.query.first()

        # Create stockout receipts with different quantities
        receipt1 = Receipt(
            operator_id=1,
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            area_id=test_customer["area"],
            department_id=test_customer["department"],
        )
        db.session.add(receipt1)
        db.session.flush()
        transaction1 = Transaction(
            itemSKU=sku, count=-10, price=100.00, receipt=receipt1
        )
        db.session.add(transaction1)

        receipt2 = Receipt(
            operator_id=1,
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            area_id=test_customer["area"],
            department_id=test_customer["department"],
        )
        db.session.add(receipt2)
        db.session.flush()
        transaction2 = Transaction(
            itemSKU=sku, count=-5, price=110.00, receipt=receipt2
        )
        db.session.add(transaction2)

        db.session.commit()

        item_name = sku.item.name
        brand = sku.brand
        spec = sku.spec

    # Get today's date for testing
    today = datetime.now().date()
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    # Test without filters
    response = auth_client.get(
        f"/statistics_usage?start_date={start_date}&end_date={end_date}"
    )
    assert response.status_code == 200
    assert str(15).encode() in response.data  # Total usage should be 15 (10 + 5)

    # Test with item name filter
    response = auth_client.get(
        f"/statistics_usage?start_date={start_date}&end_date={end_date}&item_name={item_name}"
    )
    assert response.status_code == 200
    assert str(15).encode() in response.data
    assert item_name.encode() in response.data

    # Test with brand filter
    response = auth_client.get(
        f"/statistics_usage?start_date={start_date}&end_date={end_date}&brand={brand}"
    )
    assert response.status_code == 200
    assert str(15).encode() in response.data
    assert brand.encode() in response.data

    # Test with spec filter
    response = auth_client.get(
        f"/statistics_usage?start_date={start_date}&end_date={end_date}&spec={spec}"
    )
    assert response.status_code == 200
    assert str(15).encode() in response.data
    assert spec.encode() in response.data

    # Test with warehouse filter
    response = auth_client.get(
        f"/statistics_usage?start_date={start_date}&end_date={end_date}&warehouse={test_warehouse}"
    )
    assert response.status_code == 200
    assert str(15).encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_statistics_usage_with_stockin_ignored(auth_client, test_warehouse):
    """Test that stockin transactions are not counted in usage statistics"""
    with app.app_context():
        sku = ItemSKU.query.first()

        # Create a stockin receipt
        receipt_in = Receipt(
            operator_id=1,
            refcode="USAGE-TEST-IN",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt_in)
        db.session.flush()
        transaction_in = Transaction(
            itemSKU=sku, count=2000, price=100.00, receipt=receipt_in
        )
        db.session.add(transaction_in)

        # Create a stockout receipt
        receipt_out = Receipt(
            operator_id=1,
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
        )
        db.session.add(receipt_out)
        db.session.flush()
        transaction_out = Transaction(
            itemSKU=sku, count=-8, price=110.00, receipt=receipt_out
        )
        db.session.add(transaction_out)

        db.session.commit()

    # Test statistics - should only show the stockout amount
    response = auth_client.get("/statistics_usage")
    assert response.status_code == 200
    assert str(8).encode() in response.data  # Only stockout amount should be counted
    assert str(2000).encode() not in response.data  # Stockin amount should not appear


@pytest.mark.usefixtures("test_item")
def test_records_location_info_filter(auth_client, test_warehouse, test_customer):
    with app.app_context():
        sku = ItemSKU.query.first()

        # Create a stockout receipt with a specific location
        receipt = Receipt(
            operator_id=1,  # admin user
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKOUT,
            location="Shelf A-123",  # Specific location that we'll search for
        )
        db.session.add(receipt)
        db.session.flush()

        # Add transaction to stockout
        transaction = Transaction(itemSKU=sku, count=-5, price=100.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test filtering by location name
    response = auth_client.get("/records?type=stockout&location_info=Shelf+A-123")
    assert response.status_code == 200
    assert b"Shelf A-123" in response.data

    # Test filtering by partial location name
    response = auth_client.get("/records?type=stockout&location_info=Shelf")
    assert response.status_code == 200
    assert b"Shelf A-123" in response.data

    # Test with non-matching location
    response = auth_client.get(
        "/records?type=stockout&location_info=NonExistentLocation"
    )
    assert response.status_code == 200
    assert b"Shelf A-123" not in response.data
