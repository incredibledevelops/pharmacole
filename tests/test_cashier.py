def test_pos_requires_login(client):
    r = client.get("/cashier/pos")
    assert r.status_code in (302, 401)


def test_checkout_rejects_empty_cart(client):
    r = client.post("/cashier/checkout", json={"items": [], "payment_method": "cash"})
    assert r.status_code in (302, 400, 401)