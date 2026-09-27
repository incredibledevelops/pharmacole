def test_pharmacist_inventory_requires_login(client):
    r = client.get("/pharmacist/inventory")
    assert r.status_code in (302, 401)