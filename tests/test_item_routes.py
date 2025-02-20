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
            "item_choice": "new",
            "new_item_name": "New Test Item",
            "brand": "New Brand",
            "spec": "New Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe7\x89\xa9\xe5\x93\x81\xe6\xb7\xbb\xe5\x8a\xa0\xe6\x88\x90\xe5\x8a\x9f"
        in response.data
    )  # 物品添加成功 in UTF-8

    # Get the first item from the database
    with app.app_context():
        existing_item = Item.query.first()

    # Test item creation with existing item
    response = auth_client.post(
        "/item/create",
        data={
            "item_choice": "existing",
            "existing_item": existing_item.name,
            "brand": "Another Brand",
            "spec": "Another Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe7\x89\xa9\xe5\x93\x81\xe6\xb7\xbb\xe5\x8a\xa0\xe6\x88\x90\xe5\x8a\x9f"
        in response.data
    )  # 物品添加成功 in UTF-8

    # Test invalid existing item
    response = auth_client.post(
        "/item/create",
        data={
            "item_choice": "existing",
            "existing_item": "Non-existent Item",
            "brand": "Brand",
            "spec": "Spec",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe6\x9c\xaa\xe6\x89\xbe\xe5\x88\xb0\xe6\x8c\x87\xe5\xae\x9a\xe7\x89\xa9\xe5\x93\x81"
        in response.data
    )  # 未找到指定物品 in UTF-8


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
