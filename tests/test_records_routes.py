import pytest
from wms.models import Receipt, ReceiptType, Transaction, ItemSKU
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
        transaction = Transaction(
            itemSKU=sku,
            count=10,
            price=100.00,
            receipt=receipt
        )
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
        transaction = Transaction(
            itemSKU=sku,
            count=-5,
            price=100.00,
            receipt=receipt
        )
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
                itemSKU=sku,
                count=i + 1,
                price=10.00,
                receipt=receipt
            )
            db.session.add(transaction)
        db.session.commit()

    # Test first page
    response = auth_client.get("/records?type=stockin&page=1")
    assert response.status_code == 200
    # Our per_page is 20, so we should see exactly 20 items
    assert response.data.count(b'<tr>') == 21  # 20 data rows + 1 header row

    # Test second page
    response = auth_client.get("/records?type=stockin&page=2")
    assert response.status_code == 200
    # We should see the remaining 5 items
    assert response.data.count(b'<tr>') == 6  # 5 data rows + 1 header row
