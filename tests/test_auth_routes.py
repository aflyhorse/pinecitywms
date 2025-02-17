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
