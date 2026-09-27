def test_landing_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Pharmacole" in r.data


def test_signup_creates_tenant(client, clean_db):
    r = client.post("/signup", data={
        "pharmacy_name": "GreenHealth",
        "owner_name": "Ama Mensah",
        "email": "ama@greenhealth.com",
        "phone": "+233200000000",
        "address": "Accra",
        "password": "strongpassword",
        "confirm_password": "strongpassword",
    }, follow_redirects=False)
    assert r.status_code in (302, 303)


def test_login_requires_valid_credentials(client, clean_db):
    r = client.post("/login", data={
        "login_type": "super",
        "email": "nobody@example.com",
        "password": "wrong",
    })
    assert r.status_code in (401, 400)