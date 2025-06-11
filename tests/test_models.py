import uuid
from decimal import Decimal
from wms.models import (
    User,
    Item,
    ItemSKU,
    Transaction,
    WarehouseItemSKU,
    Receipt,
    ReceiptType,
    Warehouse,
    Area,
    Department,
)
from wms import db
from sqlalchemy.exc import IntegrityError


def test_user_model():
    # Test user creation and password validation
    user = User(username="test", nickname="Test User", is_admin=False)
    user.set_password("testpass")
    assert user.username == "test"
    assert user.nickname == "Test User"
    assert not user.is_admin
    assert user.validate_password("testpass")
    assert not user.validate_password("wrongpass")


def test_item_model(client):
    with client.application.app_context():
        # Test item creation
        item_name = f"Test Item {uuid.uuid4()}"
        item = Item(name=item_name)
        db.session.add(item)

        # Test relationship with SKUs
        sku1 = ItemSKU(item=item, brand="Brand1", spec="Spec1")
        sku2 = ItemSKU(item=item, brand="Brand2", spec="Spec2")
        db.session.add(sku1)
        db.session.add(sku2)
        db.session.flush()

        assert item.name == item_name
        assert len(item.skus) == 2
        assert sku1 in item.skus
        assert sku2 in item.skus

        # Test unique constraint on item name
        duplicate_item = Item(name=item_name)
        db.session.add(duplicate_item)
        try:
            db.session.flush()
            assert False, "Should have raised IntegrityError"
        except IntegrityError:
            db.session.rollback()


def test_itemsku_model(client):
    with client.application.app_context():
        # Test SKU creation and relationships
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        db.session.flush()

        assert sku.brand == "Test Brand"
        assert sku.spec == "Test Spec"
        assert sku.item == item


def test_warehouse_item_sku_model(client):
    with client.application.app_context():
        # Test warehouse item SKU creation and relationships
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse")
        db.session.add(warehouse)
        db.session.flush()

        warehouse_item_sku = WarehouseItemSKU(
            warehouse_id=warehouse.id, itemSKU_id=sku.id, count=100, average_price=15.0
        )
        db.session.add(warehouse_item_sku)
        db.session.flush()

        assert warehouse_item_sku.warehouse == warehouse
        assert warehouse_item_sku.itemSKU == sku
        assert warehouse_item_sku.count == 100
        assert warehouse_item_sku.average_price == 15.0


def test_receipt_model(client, test_user):
    with client.application.app_context():
        # Test receipt creation and relationships
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Test STOCKIN receipt
        receipt = Receipt(
            operator=test_user,
            refcode="20250214-1",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction = Transaction(itemSKU=sku, count=5, price=10, receipt=receipt)
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()
        receipt.update_warehouse_item_skus()
        db.session.flush()

        assert receipt.operator == test_user
        assert receipt.warehouse == warehouse
        assert receipt.type == ReceiptType.STOCKIN
        assert transaction in receipt.transactions
        assert receipt.sum == 5 * 10
        assert warehouse.item_skus[0].count == 5

        # Test second STOCKIN with different price
        receipt = Receipt(
            operator=test_user,
            refcode="20250214-2",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction = Transaction(itemSKU=sku, count=10, price=20, receipt=receipt)
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()
        receipt.update_warehouse_item_skus()
        db.session.flush()
        assert warehouse.item_skus[0].count == 5 + 10
        newaverage = float(5 * 10 + 10 * 20) / (5 + 10)
        assert warehouse.item_skus[0].average_price == newaverage

        # Test STOCKOUT receipt
        receipt = Receipt(
            operator=test_user,
            refcode="20250214-3",
            warehouse=warehouse,
            type=ReceiptType.STOCKOUT,
        )
        transaction = Transaction(
            itemSKU=sku,
            count=-2,
            price=warehouse.item_skus[0].average_price,
            receipt=receipt,
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()
        receipt.update_warehouse_item_skus()
        db.session.flush()
        assert warehouse.item_skus[0].count == 5 + 10 - 2
        assert warehouse.item_skus[0].average_price == newaverage

        # Test TAKESTOCK receipt
        receipt = Receipt(
            operator=test_user,
            warehouse=warehouse,
            type=ReceiptType.TAKESTOCK,
        )
        # Adjust stock count to 10 (current is 13)
        transaction = Transaction(
            itemSKU=sku,
            count=-3,  # Reduce by 3 to get to 10
            price=warehouse.item_skus[0].average_price,
            receipt=receipt,
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()
        receipt.update_warehouse_item_skus()
        db.session.flush()
        assert warehouse.item_skus[0].count == 10
        assert warehouse.item_skus[0].average_price == newaverage


def test_area_and_department_models(client):
    with client.application.app_context():
        # Test area creation
        area = Area(name="测试区域")
        db.session.add(area)

        # Test department creation
        department = Department(name="测试部门")
        db.session.add(department)

        db.session.flush()

        # Test properties
        assert area.name == "测试区域"
        assert department.name == "测试部门"

        # Test unique constraint on area name
        duplicate_area = Area(name="测试区域")
        db.session.add(duplicate_area)
        try:
            db.session.flush()
            assert False, "Should have raised IntegrityError"
        except IntegrityError:
            db.session.rollback()


def test_warehouse_item_sku_creation(client, test_user):
    with client.application.app_context():
        # Test creation of WarehouseItemSKU for new item during stock operation
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Create a receipt for a new item
        receipt = Receipt(
            operator=test_user,
            refcode="TEST-NEW-ITEM",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction = Transaction(itemSKU=sku, count=5, price=10, receipt=receipt)
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()

        # Before update, warehouse should not have the item
        assert len(warehouse.item_skus) == 0

        receipt.update_warehouse_item_skus()
        db.session.flush()

        # After update, warehouse should have the item
        assert len(warehouse.item_skus) == 1
        warehouse_item = warehouse.item_skus[0]
        assert warehouse_item.count == 5
        assert warehouse_item.average_price == 10
        assert warehouse_item.itemSKU == sku


def test_receipt_stockin_average_price_zero_case(client, test_user):
    """Test the case where total_count becomes 0 after stockin, setting average_price to 0"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Create initial stock
        receipt1 = Receipt(
            operator=test_user,
            refcode="TEST-INITIAL",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction1 = Transaction(
            itemSKU=sku, count=10, price=Decimal("50.0"), receipt=receipt1
        )
        db.session.add(transaction1)
        db.session.add(receipt1)
        db.session.flush()
        receipt1.update_warehouse_item_skus()

        # Create a stockout to bring count to 0
        receipt2 = Receipt(
            operator=test_user,
            refcode="TEST-STOCKOUT",
            warehouse=warehouse,
            type=ReceiptType.STOCKOUT,
        )
        transaction2 = Transaction(
            itemSKU=sku, count=-10, price=Decimal("50.0"), receipt=receipt2
        )
        db.session.add(transaction2)
        db.session.add(receipt2)
        db.session.flush()
        receipt2.update_warehouse_item_skus()

        # Verify count is 0
        warehouse_item = WarehouseItemSKU.query.filter_by(
            warehouse_id=warehouse.id, itemSKU_id=sku.id
        ).first()
        assert warehouse_item.count == 0

        # Now add stock with negative count that results in total_count = 0
        # This simulates a scenario where we're adding -stock to bring total to 0
        receipt3 = Receipt(
            operator=test_user,
            refcode="TEST-ZERO",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction3 = Transaction(
            itemSKU=sku, count=0, price=Decimal("75.0"), receipt=receipt3
        )
        db.session.add(transaction3)
        db.session.add(receipt3)
        db.session.flush()
        receipt3.update_warehouse_item_skus()

        # Check that average_price is set to 0 when total_count is 0
        warehouse_item = WarehouseItemSKU.query.filter_by(
            warehouse_id=warehouse.id, itemSKU_id=sku.id
        ).first()
        assert warehouse_item.count == 0
        assert warehouse_item.average_price == 0


def test_receipt_insufficient_stock_error(client, test_user):
    """Test error when trying to stock out more than available"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Create initial stock
        receipt1 = Receipt(
            operator=test_user,
            refcode="TEST-INITIAL",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction1 = Transaction(
            itemSKU=sku, count=5, price=Decimal("10.0"), receipt=receipt1
        )
        db.session.add(transaction1)
        db.session.add(receipt1)
        db.session.flush()
        receipt1.update_warehouse_item_skus()

        # Try to stock out more than available
        receipt2 = Receipt(
            operator=test_user,
            refcode="TEST-INSUFFICIENT",
            warehouse=warehouse,
            type=ReceiptType.STOCKOUT,
        )
        transaction2 = Transaction(
            itemSKU=sku, count=-10, price=Decimal("10.0"), receipt=receipt2
        )
        db.session.add(transaction2)
        db.session.add(receipt2)
        db.session.flush()

        # This should raise a ValueError with specific message
        try:
            receipt2.update_warehouse_item_skus()
            assert False, "Should have raised ValueError for insufficient stock"
        except ValueError as e:
            error_msg = str(e)
            assert "库存不足" in error_msg
            assert item.name in error_msg
            assert sku.brand in error_msg
            assert sku.spec in error_msg
            assert warehouse.name in error_msg
            assert "5" in error_msg  # Current stock
            assert "10" in error_msg  # Attempted reduction


def test_receipt_takestock_insufficient_stock_error(client, test_user):
    """Test error when takestock would result in negative inventory"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Create initial stock
        receipt1 = Receipt(
            operator=test_user,
            refcode="TEST-INITIAL",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction1 = Transaction(
            itemSKU=sku, count=3, price=Decimal("15.0"), receipt=receipt1
        )
        db.session.add(transaction1)
        db.session.add(receipt1)
        db.session.flush()
        receipt1.update_warehouse_item_skus()

        # Try takestock with negative adjustment that would result in negative inventory
        receipt2 = Receipt(
            operator=test_user,
            refcode="TEST-TAKESTOCK-NEG",
            warehouse=warehouse,
            type=ReceiptType.TAKESTOCK,
        )
        transaction2 = Transaction(
            itemSKU=sku, count=-5, price=Decimal("15.0"), receipt=receipt2
        )
        db.session.add(transaction2)
        db.session.add(receipt2)
        db.session.flush()

        # This should raise a ValueError
        try:
            receipt2.update_warehouse_item_skus()
            assert (
                False
            ), "Should have raised ValueError for insufficient stock in takestock"
        except ValueError as e:
            error_msg = str(e)
            assert "库存不足" in error_msg
            assert item.name in error_msg
            assert sku.brand in error_msg
            assert sku.spec in error_msg
            assert warehouse.name in error_msg


def test_receipt_stockout_nonexistent_item_error(client, test_user):
    """Test error when trying to stock out an item that doesn't exist in warehouse"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Try to stock out without any initial stock (item doesn't exist in warehouse)
        receipt = Receipt(
            operator=test_user,
            refcode="TEST-NONEXISTENT",
            warehouse=warehouse,
            type=ReceiptType.STOCKOUT,
        )
        transaction = Transaction(
            itemSKU=sku, count=-5, price=Decimal("10.0"), receipt=receipt
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()

        # This should raise a ValueError with specific message
        try:
            receipt.update_warehouse_item_skus()
            assert False, "Should have raised ValueError for nonexistent item"
        except ValueError as e:
            error_msg = str(e)
            assert "物品不存在于仓库" in error_msg
            assert item.name in error_msg
            assert sku.brand in error_msg
            assert sku.spec in error_msg
            assert warehouse.name in error_msg


def test_receipt_takestock_negative_nonexistent_item_error(client, test_user):
    """Test error when trying negative takestock adjustment on item that doesn't exist in warehouse"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Try negative takestock adjustment without any initial stock
        receipt = Receipt(
            operator=test_user,
            refcode="TEST-TAKESTOCK-NONEXISTENT",
            warehouse=warehouse,
            type=ReceiptType.TAKESTOCK,
        )
        transaction = Transaction(
            itemSKU=sku, count=-3, price=Decimal("20.0"), receipt=receipt
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()

        # This should raise a ValueError
        try:
            receipt.update_warehouse_item_skus()
            assert (
                False
            ), "Should have raised ValueError for negative takestock on nonexistent item"
        except ValueError as e:
            error_msg = str(e)
            assert "物品不存在于仓库" in error_msg
            assert item.name in error_msg
            assert sku.brand in error_msg
            assert sku.spec in error_msg
            assert warehouse.name in error_msg


def test_receipt_takestock_positive_creates_new_item(client, test_user):
    """Test that positive takestock adjustment creates new warehouse item"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Positive takestock adjustment should create new warehouse item
        receipt = Receipt(
            operator=test_user,
            refcode="TEST-TAKESTOCK-POSITIVE",
            warehouse=warehouse,
            type=ReceiptType.TAKESTOCK,
        )
        transaction = Transaction(
            itemSKU=sku, count=7, price=Decimal("25.0"), receipt=receipt
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()

        # This should work and create new warehouse item
        receipt.update_warehouse_item_skus()

        # Verify the new warehouse item was created
        warehouse_item = WarehouseItemSKU.query.filter_by(
            warehouse_id=warehouse.id, itemSKU_id=sku.id
        ).first()
        assert warehouse_item is not None
        assert warehouse_item.count == 7
        assert warehouse_item.average_price == 25.0


def test_receipt_stockin_zero_average_price_initialization(client, test_user):
    """Test that stockin initializes average_price when it's 0"""
    with client.application.app_context():
        # Create test data
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)
        warehouse = Warehouse(name="Test Warehouse", owner=test_user)
        db.session.add(warehouse)
        db.session.flush()

        # Manually create a warehouse item with 0 average_price
        warehouse_item = WarehouseItemSKU(
            warehouse_id=warehouse.id, itemSKU_id=sku.id, count=0, average_price=0
        )
        db.session.add(warehouse_item)
        db.session.flush()

        # Create a stockin receipt
        receipt = Receipt(
            operator=test_user,
            refcode="TEST-PRICE-INIT",
            warehouse=warehouse,
            type=ReceiptType.STOCKIN,
        )
        transaction = Transaction(
            itemSKU=sku, count=5, price=Decimal("30.0"), receipt=receipt
        )
        db.session.add(transaction)
        db.session.add(receipt)
        db.session.flush()

        receipt.update_warehouse_item_skus()

        # Verify average_price was initialized
        warehouse_item = WarehouseItemSKU.query.filter_by(
            warehouse_id=warehouse.id, itemSKU_id=sku.id
        ).first()
        assert warehouse_item.count == 5
        assert warehouse_item.average_price == 30.0
