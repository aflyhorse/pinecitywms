def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.location


def test_index_authenticated(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
