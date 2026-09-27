def test_initialize_requires_login(client):
    r = client.post("/payments/initialize")
    assert r.status_code in (302, 401)


def test_webhook_rejects_invalid_signature(client):
    r = client.post("/webhooks/paystack", json={"event": "charge.success"}, headers={"x-paystack-signature": "bad"})
    assert r.status_code in (401, 500)