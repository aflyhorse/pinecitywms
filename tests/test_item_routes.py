import pytest
from wms.models import Item
from wms import app


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
