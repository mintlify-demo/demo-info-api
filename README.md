# demo-info-api

> [!NOTE]
> **Not hosted, and you may not need it.** Without hosting, point Mintlify's Info API URL straight at Auth0 (`https://dev-b65mix7svkohsb6d.us.auth0.com/userinfo`) and use [`auth0/direct-userinfo-action.js`](auth0/direct-userinfo-action.js): it puts `content`, `apiPlaygroundInputs` and `expiresAt` into Auth0's `/userinfo` response. Auth0 won't let an Action set a claim called `groups` (it's on Auth0's restricted list), so groups go in a namespaced claim that Mintlify reads with **groups from OAuth token claims**. Use this service only if Mintlify won't accept both settings together; it then needs a public HTTPS host.

The **Info API** for the [mintlify-demo docs](https://mintlify-demo.mintlify.site). When a reader signs in with Auth0, Mintlify calls this service with the reader's access token and gets back [Mintlify user data](https://www.mintlify.com/docs/deploy/authentication-setup#user-data-format):

```json
{
  "sub": "auth0|6f1c...",
  "expiresAt": 1893456000,
  "groups": ["enterprise"],
  "content": { "name": "Jane Doe", "firstName": "Jane", "plan": "enterprise", "email": "jane@example.com" },
  "apiPlaygroundInputs": {
    "header": { "X-API-Key": "enterprise-demo-key" },
    "query": { "api_key": "enterprise-demo-key" }
  }
}
```

That powers three things in the docs:

| Feature | Where |
| --- | --- |
| Group-gated pages and endpoints (`groups` frontmatter, `x-mint.groups`) | `todo-api/guides/enterprise-bulk-import`, `todo-api/guides/partner-integrations`, `merge-sort-api/guides/sorting-at-scale`, `text-utils-api/guides/partner-batch-processing`, `POST /todos/bulk` |
| Personalized text (`{user.name}`) | Every API's overview page |
| Prefilled playground key (`X-API-Key`, and `api_key` for the WebSocket) | Todo API endpoint pages |

Based on trev-org's `workers/mintlify-info-api` Cloudflare Worker, rewritten in FastAPI for this org.

## Endpoints

- `GET /userinfo` with `Authorization: Bearer <access token>`: user data, or `401 {"error": "unauthorized"}`. Responses carry `Cache-Control: private, no-store`.
- `GET /healthz`: `{"ok": true}`.

## How the token is checked

- **JWT access token** (you set an `audience` in Mintlify's OAuth settings): verified locally against the tenant JWKS (`https://dev-b65mix7svkohsb6d.us.auth0.com/.well-known/jwks.json`): RS256 signature, issuer `https://dev-b65mix7svkohsb6d.us.auth0.com/`, expiry, and audience if `AUTH0_AUDIENCE` is set. If the token has no groups claim or name, they're filled in from Auth0 `/userinfo`.
- **Opaque access token** (no audience, Auth0's default): checked by calling Auth0 `/userinfo`, which also returns the custom groups claim.

Groups are read from `https://mintlify-demo.mintlify.site/groups`; only `partner` and `enterprise` are passed to Mintlify. The highest plan picks the playground key: enterprise, then partner, then `demo-key` for everyone else. `expiresAt` is one hour from now, or the token's expiry if sooner.

## Configuration

| Variable | Default |
| --- | --- |
| `AUTH0_DOMAIN` | `dev-b65mix7svkohsb6d.us.auth0.com` |
| `AUTH0_AUDIENCE` | unset (audience not checked) |
| `GROUPS_CLAIM` | `https://mintlify-demo.mintlify.site/groups` |
| `ALLOWED_GROUPS` | `partner,enterprise` |
| `ALLOWED_ORIGINS` | `https://mintlify-demo.mintlify.site,https://mintlify-demo.mintlify.io` |
| `SESSION_TTL_SECONDS` | `3600` |
| `STANDARD_API_KEY` / `PARTNER_API_KEY` / `ENTERPRISE_API_KEY` | `demo-key` / `partner-demo-key` / `enterprise-demo-key` (the public Todo API demo keys) |

## Run and test

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload      # http://localhost:8000/userinfo
python -m pytest -q
```

## Setup

### 1. Host it

TODO(hosting): not hosted. Only needed if the direct Auth0 setup above isn't enough. It needs a public HTTPS URL, for example `https://<info-api-host>/userinfo`. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`; health check: `/healthz`.

### 2. Auth0: add the groups claim

1. **Actions > Library > Create Action > Build from scratch**. Name `Mintlify groups`, trigger **Login / Post Login**.
2. Paste [`auth0/post-login-action.js`](auth0/post-login-action.js), click **Deploy**.
3. **Actions > Triggers > post-login**: drag `Mintlify groups` into the flow, click **Apply**.
4. Give each demo login its group in **User Management > Users > (user) > Details > app_metadata**, for example `{ "groups": ["enterprise"] }` for the shared AE login, and `{ "groups": ["partner"] }` for a second partner login.

### 3. Mintlify: point Access at the Info API

Dashboard > **Access** (OAuth, already set up for Auth0): set **Info API URL** to `https://<info-api-host>/userinfo` and keep scopes `openid profile email`. Save; the site redeploys. Readers must sign out and in again to pick up groups.

Optional: to get JWT access tokens (verified locally instead of a call to Auth0 per login), create an Auth0 API (**Applications > APIs**, identifier such as `https://mintlify-demo-docs`), add `audience=https://mintlify-demo-docs` under **Additional authorization parameters** in Mintlify, and set `AUTH0_AUDIENCE` to the same value here.

### Check it

```bash
curl -i https://<info-api-host>/userinfo                       # 401
curl -s https://<info-api-host>/userinfo -H "Authorization: Bearer $TOKEN" | jq
```

## Groups without hosting (findings, Oct 27 2026)
- **Auth0 `/userinfo` can't carry `groups`.** Auth0 drops `groups`, `roles` and `permissions`; they're on the [restricted claim list](https://auth0.com/docs/secure/tokens/json-web-tokens/create-custom-claims#general-restrictions). `content`, `apiPlaygroundInputs` and `expiresAt` do come through, which is what `auth0/direct-userinfo-action.js` relies on.
- **Mintlify's "groups from OAuth token claims" isn't in the dashboard UI.** It's documented (`source`, `groupsClaim`, `groupsDelimiter`). If Mintlify turns it on for this deployment with `{"source":"id_token","groupsClaim":"https://mintlify-demo.mintlify.site/groups"}`, groups work with no other changes.
- **Experimental: `auth0/jwt-handoff-action.js`.** Switch Mintlify Access to **JWT** and let an Auth0 Action sign the Mintlify JWT (EdDSA, with the key from the dashboard) and redirect to `/login/jwt-callback#<jwt>`. Groups, content and prefill all go in the JWT, and nothing is hosted. Signing and verification were tested locally with `jose`. Still untested end to end: whether Auth0 keeps the `#fragment` when it appends `?state=`. Setup steps are in the file header.
- **Without groups,** gated pages and `POST /todos/bulk` just don't appear. The welcome pages still differ per reader through `user.plan` from `content`.
