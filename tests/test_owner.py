def test_owner_dashboard_requires_login(client):
    r = client.get("/owner/dashboard")
    assert r.status_code in (302, 401)