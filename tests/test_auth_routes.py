def test_login_logout(client, test_user):
    # Test login with valid credentials
    response = client.post(
        "/login",
        data={"username": "testadmin", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "登录成功".encode() in response.data

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
    assert "用户名/密码错误".encode() in response.data

    # Test logout
    response = client.get("/logout", follow_redirects=True)
    assert response.status_code == 200
    assert "登出成功".encode() in response.data


def test_admin_change_password(auth_client, regular_user):
    # Test admin changing another user's password
    response = auth_client.post(
        "/change_password",
        data={
            "username": "testuser",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "已成功修改用户 testuser 的密码。".encode() in response.data


def test_regular_user_change_password(client, regular_user):
    # Login as regular user and verify login success
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "登录成功".encode() in response.data

    # Verify user can access the change password page
    response = client.get("/change_password")
    assert response.status_code == 200

    # Test regular user attempting to change another user's password
    response = client.post(
        "/change_password",
        data={
            "username": "testadmin",
            "old_password": "password123",
            "new_password": "hackpassword123",
            "confirm_password": "hackpassword123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "您只能修改自己的密码。".encode() in response.data

    # Test regular user changing their own password with wrong old password
    response = client.post(
        "/change_password",
        data={
            "username": "testuser",
            "old_password": "wrongpassword",
            "new_password": "anotherpassword",
            "confirm_password": "anotherpassword",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "原密码错误。".encode() in response.data

    # Test regular user changing their own password successfully
    response = client.post(
        "/change_password",
        data={
            "username": "testuser",
            "old_password": "password123",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "密码修改成功。".encode() in response.data
