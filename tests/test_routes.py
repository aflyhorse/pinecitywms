import pytest
from wms.models import Item
from wms import app


def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.location


def test_index_authenticated(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200


def test_login_logout(client, test_user):
    # Test login with valid credentials
    response = client.post(
        "/login",
        data={"username": "testadmin", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe7\x99\xbb\xe5\xbd\x95\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "登录成功" in UTF-8

    # Test login with invalid credentials
    response = client.post(
        "/login",
        data={
            "username": "testadmin",
            "password": "wrongpassword",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"\xe7\x94\xa8\xe6\x88\xb7\xe5\x90\x8d/\xe5\xaf\x86\xe7\xa0\x81\xe9\x94\x99\xe8\xaf\xaf"
        in response.data
    )  # "用户名/密码错误" in UTF-8

    # Test logout
    response = client.get("/logout", follow_redirects=True)
    assert response.status_code == 200
    assert (
        b"\xe7\x99\xbb\xe5\x87\xba\xe6\x88\x90\xe5\x8a\x9f" in response.data
    )  # "登出成功" in UTF-8


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
