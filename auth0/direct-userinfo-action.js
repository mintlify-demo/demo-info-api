/**
 * Auth0 Action (Login / Post Login) for running personalization WITHOUT this service:
 * Mintlify's Info API URL points straight at https://dev-b65mix7svkohsb6d.us.auth0.com/userinfo.
 *
 * Auth0 returns non-namespaced custom claims set on the ID token from /userinfo, so `content`,
 * `apiPlaygroundInputs` and `expiresAt` reach Mintlify as-is. `groups` is a RESTRICTED claim name in
 * Auth0 (setCustomClaim("groups") is silently dropped), so groups go in a namespaced claim that
 * Mintlify reads with its "groups from OAuth token claims" setting.
 *
 * Give a user a group in User Management > Users > (user) > app_metadata: { "groups": ["enterprise"] }
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
  // Database users get their email as `name`; greet them by the part before the @ instead.
  const name =
    event.user.name && event.user.name !== email ? event.user.name : event.user.nickname || email.split("@")[0];

  // Groups (namespaced: Auth0 reserves `groups`). Mintlify: Access > token claims, source id_token.
  api.idToken.setCustomClaim(`${ns}/groups`, groups);

  // Mintlify user data, returned by /userinfo because they're set on the ID token.
  api.idToken.setCustomClaim("content", { name, firstName: name.split(" ")[0], plan, email });
  api.idToken.setCustomClaim("apiPlaygroundInputs", {
    header: { "X-API-Key": keys[plan] }, // Todo API REST + GraphQL
    query: { api_key: keys[plan] }, // Todo API WebSocket events
  });
  api.idToken.setCustomClaim("expiresAt", Math.floor(Date.now() / 1000) + 8 * 60 * 60);
};
