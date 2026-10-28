/**
 * Auth0 post-login Action: personalization with NO hosted Info API.
 *
 * Mintlify Access (OAuth) -> Info API URL = https://dev-b65mix7svkohsb6d.us.auth0.com/userinfo
 * Auth0 returns non-namespaced custom claims set on the ID token from /userinfo, so Mintlify
 * gets `content`, `apiPlaygroundInputs` and `expiresAt` from it.
 *
 * `groups` can NOT be delivered this way: it's on Auth0's restricted claim list and is
 * silently dropped. The namespaced claim below only helps if Mintlify's "groups from OAuth
 * token claims" option is enabled for the deployment (not in the dashboard UI today).
 *
 * Plan comes from app_metadata.groups, e.g. {"groups": ["enterprise"]}.
 */
exports.onExecutePostLogin = async (event, api) => {
  const ns = "https://mintlify-demo.mintlify.site";
  const allowed = ["partner", "enterprise"];
  const keys = { enterprise: "enterprise-demo-key", partner: "partner-demo-key", standard: "demo-key" };

  const raw = event.user.app_metadata?.groups ?? [];
  const groups = (Array.isArray(raw) ? raw : String(raw).split(","))
    .map((g) => String(g).trim())
    .filter((g) => allowed.includes(g));
  const plan = groups.includes("enterprise") ? "enterprise" : groups.includes("partner") ? "partner" : "standard";

  const email = event.user.email || "";
  const name = event.user.name && event.user.name !== email ? event.user.name : event.user.nickname || email.split("@")[0];

  api.idToken.setCustomClaim(`${ns}/groups`, groups);
  api.idToken.setCustomClaim("content", { name, firstName: name.split(" ")[0], plan, email, apiKey: keys[plan] });
  // Key must match the OpenAPI security scheme's `name` exactly (todo-api: apiKey in header "X-API-Key").
  api.idToken.setCustomClaim("apiPlaygroundInputs", { header: { "X-API-Key": keys[plan] } });
  api.idToken.setCustomClaim("expiresAt", Math.floor(Date.now() / 1000) + 8 * 60 * 60);
};
