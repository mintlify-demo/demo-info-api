import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main

GROUPS = "https://mintlify-demo.mintlify.site/groups"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_jwt(key=KEY, **claims):
    now = int(time.time())
    payload = {"iss": main.ISSUER, "sub": "auth0|ae", "aud": "https://api.demo", "iat": now, "exp": now + 600}
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "signing_key_for", lambda token: KEY.public_key())
    calls = []

    def fake_userinfo(token):
        calls.append(token)
        if token == "opaque-good":
            return {"sub": "auth0|ae", "name": "Avery Exec", "email": "ae@example.com", GROUPS: ["partner"]}
        if token.count(".") == 2:  # a JWT: /userinfo returns the profile
            return {"sub": "auth0|ae", "name": "Avery Exec", "email": "ae@example.com"}
        raise main.Unauthorized("bad")

    monkeypatch.setattr(main, "fetch_auth0_userinfo", fake_userinfo)
    c = TestClient(main.app)
    c.calls = calls
    return c


def get(client, token, **headers):
    return client.get("/userinfo", headers={"Authorization": f"Bearer {token}", **headers})


def test_missing_token_is_401(client):
    r = client.get("/userinfo")
    assert r.status_code == 401 and r.headers["cache-control"] == "private, no-store"


def test_enterprise_jwt(client):
    r = get(client, make_jwt(**{GROUPS: ["enterprise", "admin"], "name": "Jane Doe"}))
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == ["enterprise"]  # only allowed groups pass through
    assert body["content"]["name"] == "Jane Doe" and body["content"]["plan"] == "enterprise"
    assert body["apiPlaygroundInputs"] == {
        "header": {"X-API-Key": "enterprise-demo-key"},
        "query": {"api_key": "enterprise-demo-key"},
    }
    assert body["sub"] == "auth0|ae"
    assert body["expiresAt"] <= int(time.time()) + 600
    assert r.headers["cache-control"] == "private, no-store"


def test_jwt_without_profile_claims_is_enriched_from_userinfo(client):
    body = get(client, make_jwt(**{GROUPS: "partner"})).json()
    assert body["groups"] == ["partner"]  # string claims are split on commas
    assert body["content"]["name"] == "Avery Exec"
    assert body["apiPlaygroundInputs"]["header"]["X-API-Key"] == "partner-demo-key"


def test_jwt_bad_signature_expired_or_wrong_issuer_is_401(client):
    assert get(client, make_jwt(key=OTHER_KEY)).status_code == 401
    assert get(client, make_jwt(exp=int(time.time()) - 10)).status_code == 401
    assert get(client, make_jwt(iss="https://evil.example.com/")).status_code == 401


def test_opaque_token_uses_auth0_userinfo(client):
    body = get(client, "opaque-good").json()
    assert body["groups"] == ["partner"] and body["content"]["firstName"] == "Avery"
    assert get(client, "opaque-bad").status_code == 401


def test_no_groups_gets_the_standard_key(client):
    body = get(client, make_jwt(name="Sam")).json()
    assert body["groups"] == [] and body["content"]["plan"] == "standard"
    assert body["apiPlaygroundInputs"]["header"]["X-API-Key"] == "demo-key"


def test_email_as_name_is_shortened():
    data = main.user_data({"name": "marco+aedemo@mintlify.com", "email": "marco+aedemo@mintlify.com"}, None)
    assert data["content"]["name"] == "marco+aedemo"


def test_cors_allows_only_the_docs_origin(client):
    ok = client.options("/userinfo", headers={"Origin": "https://mintlify-demo.mintlify.site",
                                              "Access-Control-Request-Method": "GET",
                                              "Access-Control-Request-Headers": "authorization"})
    assert ok.headers["access-control-allow-origin"] == "https://mintlify-demo.mintlify.site"
    assert ok.headers["access-control-allow-credentials"] == "true"
    bad = client.options("/userinfo", headers={"Origin": "https://evil.example.com",
                                               "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}
