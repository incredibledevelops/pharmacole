def test_super_admin_requires_login(client):
    r = client.get("/super-admin/dashboard")
    assert r.status_code in (302, 401)