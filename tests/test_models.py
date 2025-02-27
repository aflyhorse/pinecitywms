import uuid
from wms.models import (
    User,
    Item,
    ItemSKU,
    Transaction,
    WarehouseItemSKU,
    Receipt,
    ReceiptType,
    Warehouse,
    Customer,
    CustomerType,
)
from wms import db


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


def test_customer_model(client):
    with client.application.app_context():
        # Test area customer creation
        area = Customer(
            name="测试区域",
            type=CustomerType.AREA,
        )
        db.session.add(area)

        # Test department under area
        department = Customer(name="测试部门", type=CustomerType.DEPARTMENT)
        db.session.add(department)

        # Test group under department
        group = Customer(name="测试班组", type=CustomerType.GROUP)
        db.session.add(group)
        db.session.flush()

        # Test relationships
        assert area.type == CustomerType.AREA
        assert department.type == CustomerType.DEPARTMENT
        assert group.type == CustomerType.GROUP
