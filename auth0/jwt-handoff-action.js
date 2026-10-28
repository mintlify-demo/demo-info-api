/**
 * EXPERIMENTAL Auth0 post-login Action: Mintlify JWT auth signed inside Auth0 (no hosting).
 * Gives Mintlify real `groups` (plus content, apiPlaygroundInputs) because the JWT is
 * signed by us, not filtered through Auth0's restricted-claim list.
 *
 * Setup (see README "Groups without hosting"):
 *  - A separate Auth0 application "Mintlify docs JWT handoff" (Regular Web App). Allowed
 *    Callback URL: https://mintlify-demo.mintlify.site/login/jwt-callback
 *  - Action secrets: HANDOFF_CLIENT_ID (that app's client ID) and MINTLIFY_JWT_PRIVATE_KEY
 *    (the PEM Mintlify downloads under Access -> JWT -> Generate new key).
 *  - Mintlify Access -> Custom -> JWT, login URL:
 *    https://dev-b65mix7svkohsb6d.us.auth0.com/authorize?response_type=code&client_id=<HANDOFF_CLIENT_ID>&redirect_uri=https%3A%2F%2Fmintlify-demo.mintlify.site%2Flogin%2Fjwt-callback&scope=openid%20profile%20email
 *
 * Unverified: that Auth0 keeps the #fragment when it appends ?state= to the sendUserTo URL.
 */
const crypto = require("crypto");

const DOCS_ORIGIN = "https://mintlify-demo.mintlify.site";
const DOCS_HOST = "mintlify-demo.mintlify.site";
const ALLOWED = ["partner", "enterprise"];
const KEYS = { enterprise: "enterprise-demo-key", partner: "partner-demo-key", standard: "demo-key" };
const b64u = (v) => Buffer.from(v).toString("base64url");

exports.onExecutePostLogin = async (event, api) => {
  if (event.client.client_id !== event.secrets.HANDOFF_CLIENT_ID) return; // leave every other app alone

  const raw = event.user.app_metadata?.groups ?? [];
  const groups = (Array.isArray(raw) ? raw : String(raw).split(","))
    .map((g) => String(g).trim())
    .filter((g) => ALLOWED.includes(g));
  const plan = groups.includes("enterprise") ? "enterprise" : groups.includes("partner") ? "partner" : "standard";
  const email = event.user.email || "";
  const name = event.user.name && event.user.name !== email ? event.user.name : event.user.nickname || email.split("@")[0];

  const now = Math.floor(Date.now() / 1000);
  const payload = {
    host: DOCS_HOST,
    sub: event.user.user_id,
    iat: now,
    exp: now + 10, // JWT itself lives 10 s
    expiresAt: now + 8 * 60 * 60, // docs session lives 8 h
    groups,
    content: { name, firstName: name.split(" ")[0], plan, email, apiKey: KEYS[plan] },
    apiPlaygroundInputs: { header: { "X-API-Key": KEYS[plan] } },
  };
  const signingInput = `${b64u(JSON.stringify({ alg: "EdDSA", typ: "JWT" }))}.${b64u(JSON.stringify(payload))}`;
  const key = crypto.createPrivateKey(String(event.secrets.MINTLIFY_JWT_PRIVATE_KEY).replace(/\\n/g, "\n"));
  const jwt = `${signingInput}.${b64u(crypto.sign(null, Buffer.from(signingInput), key))}`;

  // Mintlify adds ?redirect=/path to the login URL; Auth0 passes it through to event.request.query.
  const r = event.request.query?.redirect;
  const redirect = typeof r === "string" && r.startsWith("/") && !r.startsWith("//") ? r : "";
  const qs = redirect ? `?redirect=${encodeURIComponent(redirect)}` : "";
  api.redirect.sendUserTo(`${DOCS_ORIGIN}/login/jwt-callback${qs}#${jwt}`);
};

// Never called: the docs site doesn't return to /continue. Required by Auth0 when redirecting.
exports.onContinuePostLogin = async () => {};
