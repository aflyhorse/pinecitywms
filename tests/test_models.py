import uuid
from wms.models import User, Item, ItemSKU, Stock
from datetime import datetime
from wms import db


def test_user_model():
    # Test user creation and password validation
    user = User(username="test", nickname="Test User", is_admin=False, active=True)
    user.set_password("testpass")
    assert user.username == "test"
    assert user.nickname == "Test User"
    assert not user.is_admin
    assert user.active
    assert user.validate_password("testpass")
    assert not user.validate_password("wrongpass")
    assert user.is_active

    # Test inactive user
    inactive_user = User(
        username="inactive", nickname="Inactive User", is_admin=False, active=False
    )
    assert not inactive_user.is_active


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


def test_stock_model(client, test_user):
    with client.application.app_context():
        # Test stock creation and relationships
        item = Item(name=f"Test Item {uuid.uuid4()}")
        db.session.add(item)
        sku = ItemSKU(item=item, brand="Test Brand", spec="Test Spec")
        db.session.add(sku)

        stock = Stock(itemSKU=sku, count=10, price=20.5, owner=test_user)
        db.session.add(stock)
        db.session.flush()

        assert stock.count == 10
        assert stock.price == 20.5
        assert stock.owner == test_user
        assert stock.itemSKU == sku
        assert isinstance(stock.date, datetime)
        assert stock in test_user.stocks
        assert stock in sku.stocks
