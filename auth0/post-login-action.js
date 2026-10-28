/**
 * Auth0 Action, trigger: Login / Post Login.
 * Adds the reader's Mintlify groups (partner, enterprise) to the ID token and access token,
 * and to the /userinfo response, under the claim the Info API reads.
 *
 * Set a user's groups in Auth0: User Management > Users > (user) > Details > app_metadata:
 *   { "groups": ["enterprise"] }
 */
exports.onExecutePostLogin = async (event, api) => {
  const namespace = "https://mintlify-demo.mintlify.site";
  const allowed = ["partner", "enterprise"];
  const raw = event.user.app_metadata?.groups ?? event.authorization?.roles ?? [];
  const groups = (Array.isArray(raw) ? raw : String(raw).split(","))
    .map((g) => String(g).trim())
    .filter((g) => allowed.includes(g));

  api.idToken.setCustomClaim(`${namespace}/groups`, groups);
  api.accessToken.setCustomClaim(`${namespace}/groups`, groups);
  if (event.user.name) {
    api.accessToken.setCustomClaim("name", event.user.name);
  }
};
