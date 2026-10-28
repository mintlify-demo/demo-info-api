"""Mintlify Info API for the mintlify-demo docs.

Mintlify's OAuth login (Auth0) calls  GET /userinfo  with
`Authorization: Bearer <Auth0 access token>` and expects Mintlify's user data:

    {
      "sub": "auth0|abc",
      "expiresAt": 1893456000,
      "groups": ["enterprise"],
      "content": {"name": "Jane Doe", "plan": "enterprise", ...},
      "apiPlaygroundInputs": {"header": {"X-API-Key": "enterprise-demo-key"},
                              "query": {"api_key": "enterprise-demo-key"}}
    }

Token validation:
  * A JWT access token (Mintlify OAuth sends `audience=<your Auth0 API>`) is verified
    locally against the tenant's JWKS: RS256 signature, issuer, expiry, and audience
    when AUTH0_AUDIENCE is set. Groups come from the custom claim in the token.
  * Any other token (Auth0 issues an opaque token when no audience is requested) is
    checked by calling Auth0's /userinfo endpoint, which also returns the custom claim.
  Either way, name/email come from the token or, if missing, from Auth0 /userinfo.

Configuration (environment variables, defaults in brackets):
  AUTH0_DOMAIN        [dev-b65mix7svkohsb6d.us.auth0.com]
  AUTH0_AUDIENCE      [unset: audience not checked]
  GROUPS_CLAIM        [https://mintlify-demo.mintlify.site/groups]
  ALLOWED_GROUPS      [partner,enterprise]   groups passed through to Mintlify
  ALLOWED_ORIGINS     [https://mintlify-demo.mintlify.site,https://mintlify-demo.mintlify.io]
  SESSION_TTL_SECONDS [3600]   capped by the token's own expiry
  STANDARD_API_KEY    [demo-key]
  PARTNER_API_KEY     [partner-demo-key]
  ENTERPRISE_API_KEY  [enterprise-demo-key]

Run it:  uvicorn main:app --reload
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

log = logging.getLogger("demo-info-api")

AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN", "dev-b65mix7svkohsb6d.us.auth0.com").removeprefix("https://").rstrip("/")
AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE") or None
ISSUER = f"https://{AUTH0_DOMAIN}/"
GROUPS_CLAIM = os.environ.get("GROUPS_CLAIM", "https://mintlify-demo.mintlify.site/groups")
ALLOWED_GROUPS = [g.strip() for g in os.environ.get("ALLOWED_GROUPS", "partner,enterprise").split(",") if g.strip()]
ALLOWED_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.environ.get(
        "ALLOWED_ORIGINS", "https://mintlify-demo.mintlify.site,https://mintlify-demo.mintlify.io"
    ).split(",")
    if o.strip()
]
SESSION_TTL_SECONDS = min(int(os.environ.get("SESSION_TTL_SECONDS", "3600")), 7 * 24 * 3600)

# Plan -> the Todo API key the docs playground is prefilled with. Highest plan wins.
PLAN_KEYS = {
    "enterprise": os.environ.get("ENTERPRISE_API_KEY", "enterprise-demo-key"),
    "partner": os.environ.get("PARTNER_API_KEY", "partner-demo-key"),
    "standard": os.environ.get("STANDARD_API_KEY", "demo-key"),
}

NO_STORE = {"Cache-Control": "private, no-store"}


class Unauthorized(Exception):
    pass


# --------------------------------------------------------------------------- #
# Auth0 helpers (module-level so tests can swap them out)
# --------------------------------------------------------------------------- #

_jwks_client = jwt.PyJWKClient(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def signing_key_for(token: str):
    """The RSA public key from the tenant JWKS that signed this token."""
    return _jwks_client.get_signing_key_from_jwt(token).key


def fetch_auth0_userinfo(token: str) -> dict[str, Any]:
    """Call Auth0 /userinfo with the access token. Raises Unauthorized if Auth0 rejects it."""
    try:
        r = httpx.get(
            f"https://{AUTH0_DOMAIN}/userinfo",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        log.error("Auth0 /userinfo request failed: %s", exc)
        raise
    if r.status_code != 200:
        raise Unauthorized(f"Auth0 /userinfo returned {r.status_code}")
    data = r.json()
    if not isinstance(data, dict):
        raise Unauthorized("Auth0 /userinfo returned a non-object")
    return data


def looks_like_jwt(token: str) -> bool:
    if token.count(".") != 2:
        return False
    try:
        return jwt.get_unverified_header(token).get("alg") == "RS256"
    except jwt.PyJWTError:
        return False


def verify_jwt(token: str) -> dict[str, Any]:
    """Verify an Auth0 RS256 access token against the tenant JWKS."""
    try:
        return jwt.decode(
            token,
            signing_key_for(token),
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=AUTH0_AUDIENCE,
            options={"require": ["exp", "iss", "sub"], "verify_aud": AUTH0_AUDIENCE is not None},
        )
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise Unauthorized(f"invalid access token: {exc}") from exc


# --------------------------------------------------------------------------- #
# Mapping Auth0 claims -> Mintlify user data
# --------------------------------------------------------------------------- #


def normalize_groups(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else value.split(",") if isinstance(value, str) else []
    seen: list[str] = []
    for g in raw:
        if isinstance(g, str) and g.strip() and g.strip() not in seen:
            seen.append(g.strip())
    return seen


def plan_for(groups: list[str]) -> str:
    for plan in ("enterprise", "partner"):
        if plan in groups:
            return plan
    return "standard"


def user_data(claims: dict[str, Any], token_exp: int | None, now: float | None = None) -> dict[str, Any]:
    now = int(now if now is not None else time.time())
    groups = [g for g in normalize_groups(claims.get(GROUPS_CLAIM)) if g in ALLOWED_GROUPS]
    plan = plan_for(groups)
    expires_at = now + SESSION_TTL_SECONDS
    if token_exp and token_exp > now:
        expires_at = min(expires_at, int(token_exp))
    name = (claims.get("name") or claims.get("nickname") or "").strip()
    if not name or name == claims.get("email"):
        # Auth0 sets `name` to the email for database users; greet them by the part before @.
        name = (claims.get("email") or name or "").split("@")[0]
    content: dict[str, Any] = {"plan": plan}
    if name:
        content["name"] = name
        content["firstName"] = name.split()[0]
    if claims.get("email"):
        content["email"] = claims["email"]
    key = PLAN_KEYS[plan]
    data: dict[str, Any] = {
        "expiresAt": expires_at,
        "groups": groups,
        "content": content,
        "apiPlaygroundInputs": {
            "header": {"X-API-Key": key},  # Todo API REST + GraphQL
            "query": {"api_key": key},  # Todo API WebSocket events (AsyncAPI)
        },
    }
    if claims.get("sub"):
        data["sub"] = str(claims["sub"])
    return data


def resolve_claims(token: str) -> tuple[dict[str, Any], int | None]:
    """Return (claims, token expiry) for a valid token, or raise Unauthorized."""
    if looks_like_jwt(token):
        claims = verify_jwt(token)
        if GROUPS_CLAIM not in claims or not claims.get("name"):
            # Access tokens usually lack profile claims; fill them in from /userinfo.
            try:
                claims = {**fetch_auth0_userinfo(token), **claims}
            except (Unauthorized, httpx.HTTPError) as exc:
                log.warning("could not enrich JWT claims from /userinfo: %s", exc)
        return claims, claims.get("exp")
    return fetch_auth0_userinfo(token), None


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="mintlify-demo Info API",
    version="1.0.0",
    description="Maps an Auth0 login to Mintlify user data: groups, personalized content, and playground keys.",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


def error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers=NO_STORE)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/userinfo")
def userinfo(request: Request) -> JSONResponse:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return error(401, "unauthorized")
    try:
        claims, exp = resolve_claims(token.strip())
    except Unauthorized as exc:
        log.info("rejected token: %s", exc)
        return error(401, "unauthorized")
    except httpx.HTTPError:
        return error(502, "identity_provider_unavailable")
    return JSONResponse(user_data(claims, exp), headers=NO_STORE)
