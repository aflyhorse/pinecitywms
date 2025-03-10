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
