import pytest
from wms.models import Item, ItemSKU
from wms import app, db


@pytest.mark.usefixtures("test_item")
def test_item_management(auth_client):
    # Test item listing
    response = auth_client.get("/item")
    assert response.status_code == 200
    assert b"Test Item" in response.data
    assert b"Test Brand" in response.data
    assert b"Test Spec" in response.data

    # Test item search
    response = auth_client.post(
        "/item",
        data={"name": "Test", "brand": "Brand", "spec": "Spec"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Test Item" in response.data


def test_item_creation(auth_client):
    # Test GET request to item creation page
    response = auth_client.get("/item/create")
    assert response.status_code == 200
    assert b"form" in response.data

    # Test item creation with new item
    response = auth_client.post(
        "/item/create",
        data={
            "item_name": "New Test Item",
            "brand": "New Brand",
            "spec": "New Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "物品添加成功".encode() in response.data

    # Get the first item from the database
    with app.app_context():
        existing_item = Item.query.first()

    # Test item creation with existing item
    response = auth_client.post(
        "/item/create",
        data={
            "item_name": existing_item.name,
            "brand": "Another Brand",
            "spec": "Another Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "物品添加成功".encode() in response.data


def test_non_admin_access(client, regular_user):
    # Login as non-admin user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to item management
    response = client.get("/item", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" in response.data

    # Test access to item creation
    response = client.get("/item/create", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" in response.data


def test_duplicate_sku_validation(auth_client):
    """Test that creating a SKU with same brand and spec for an item is prevented"""
    # First create an item with a SKU
    response = auth_client.post(
        "/item/create",
        data={
            "item_name": "Duplicate Test Item",
            "brand": "Duplicate Brand",
            "spec": "Duplicate Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "物品添加成功".encode() in response.data

    # Try to create another SKU with same brand and spec for the same item
    response = auth_client.post(
        "/item/create",
        data={
            "item_name": "Duplicate Test Item",  # Same item name
            "brand": "Duplicate Brand",  # Same brand
            "spec": "Duplicate Spec",  # Same spec
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "物品和对应型号已存在".encode() in response.data

    # Verify only one SKU was created in the database
    with app.app_context():
        item = Item.query.filter_by(name="Duplicate Test Item").first()
        assert item is not None
        assert len(item.skus) == 1
        assert item.skus[0].brand == "Duplicate Brand"
        assert item.skus[0].spec == "Duplicate Spec"


@pytest.mark.usefixtures("test_item")
def test_toggle_disabled(auth_client):
    """Test the toggle_disabled functionality for ItemSKU"""
    # Create a test item and SKU
    with app.app_context():
        # Create a new item for testing
        test_item = Item(name="Toggle Test Item")
        db.session.add(test_item)
        db.session.flush()

        # Create a SKU for the item
        test_sku = ItemSKU(
            item_id=test_item.id,
            brand="Toggle Brand",
            spec="Toggle Spec",
            disabled=False,  # Initially enabled
        )
        db.session.add(test_sku)
        db.session.commit()

        # Get the SKU ID for testing
        sku_id = test_sku.id

    # Test disabling the SKU
    response = auth_client.post(f"/item/{sku_id}/toggle_disabled")
    assert response.status_code == 200

    json_data = response.get_json()
    assert json_data["success"] is True
    assert json_data["disabled"] is True
    assert "禁用" in json_data["message"]

    # Verify in database that the SKU is disabled
    with app.app_context():
        sku = db.session.get(ItemSKU, sku_id)
        assert sku.disabled is True

    # Test enabling the SKU again
    response = auth_client.post(f"/item/{sku_id}/toggle_disabled")
    assert response.status_code == 200

    json_data = response.get_json()
    assert json_data["success"] is True
    assert json_data["disabled"] is False
    assert "启用" in json_data["message"]

    # Verify in database that the SKU is enabled
    with app.app_context():
        sku = db.session.get(ItemSKU, sku_id)
        assert sku.disabled is False

    # Test with non-existent SKU ID
    response = auth_client.post("/item/99999/toggle_disabled")
    assert response.status_code == 404

    json_data = response.get_json()
    assert json_data["success"] is False
    assert "物品不存在" in json_data["message"]


def test_toggle_disabled_non_admin_access(client, regular_user):
    """Test that regular users cannot access toggle_disabled"""
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Try to toggle disabled status
    response = client.post("/item/1/toggle_disabled", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" in response.data
