// Firebase verifies the token at accounts:lookup. Never trust decoded claims alone.
const SESSION_COOKIE = '__Host-se-session';
const PAID_PLANS = new Set(['gold', 'plus', 'fantasy', 'fantasyplus', 'platinum']);
class AuthError extends Error {
  constructor(status, message, code = 'AUTH_UNAVAILABLE') { super(message); this.status = status; this.code = code; }
}
function firebaseConfig(env) {
  const config = { apiKey:env.FIREBASE_API_KEY, authDomain:env.FIREBASE_AUTH_DOMAIN, projectId:env.FIREBASE_PROJECT_ID, appId:env.FIREBASE_APP_ID };
  if (Object.values(config).some(value => typeof value !== 'string' || !value.trim())) throw new AuthError(503, 'Sign-in is temporarily unavailable. Please try again later.', 'AUTH_CONFIG_MISSING');
  return {...config, databaseId:env.FIREBASE_DATABASE_ID?.trim() || '(default)'};
}
function sessionCookie(token = '', maxAge = 0) {
  return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}
function sameOrigin(request) {
  if (request.headers.get('origin') !== new URL(request.url).origin) throw new AuthError(403, 'Open SharpEdge at its original address and try signing in again.', 'SESSION_ORIGIN_MISMATCH');
}
function tokenClaims(token) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3 || token.length > 6000) throw new Error();
    const decode = part => JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(part.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))));
    if (decode(parts[0]).alg !== 'RS256') throw new Error();
    return decode(parts[1]);
  } catch { throw new AuthError(401, 'Please sign in again.', 'AUTH_INVALID_TOKEN'); }
}
async function authenticate(request, env) {
  const bearer = request.headers.get('authorization');
  const token = bearer ? bearer.match(/^Bearer ([A-Za-z0-9_.-]+)$/)?.[1] : request.headers.get('cookie')?.match(/(?:^|;\s*)__Host-se-session=([A-Za-z0-9_.-]+)/)?.[1];
  if (!token) throw new AuthError(401, 'Sign in to continue.', 'AUTH_REQUIRED');
  const config = firebaseConfig(env), claims = tokenClaims(token), now = Math.floor(Date.now() / 1000);
  if (claims.aud !== config.projectId || claims.iss !== `https://securetoken.google.com/${config.projectId}`) throw new AuthError(401, 'Your sign-in belongs to a different application. Sign in again.', 'AUTH_PROJECT_MISMATCH');
  if (typeof claims.sub !== 'string' || !claims.sub || claims.sub.length > 128 || !Number.isFinite(claims.exp) || !Number.isFinite(claims.iat) || !Number.isFinite(claims.auth_time)) throw new AuthError(401, 'Please sign in again.', 'AUTH_INVALID_TOKEN');
  if (claims.exp <= now) throw new AuthError(401, 'Your session expired. Please sign in again.', 'AUTH_TOKEN_EXPIRED');
  // A new Google token may be a few seconds ahead of the local server clock.
  // Firebase still verifies its signature and validity below; expired tokens
  // and membership expiration receive no grace period.
  if (claims.iat > now + 60 || claims.auth_time > now + 60) throw new AuthError(401, 'The server clock is out of sync. Please try again shortly.', 'AUTH_TOKEN_NOT_YET_VALID');
  if (claims.firebase?.sign_in_provider !== 'google.com' || claims.email_verified !== true) throw new AuthError(401, 'Please sign in with Google again.', 'AUTH_GOOGLE_REQUIRED');
  let response;
  try {
    response = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=${encodeURIComponent(config.apiKey)}`, {
      method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({idToken:token}), signal:AbortSignal.timeout(10000)
    });
  } catch { throw new AuthError(503, 'The server could not reach Google to verify your sign-in. Please try again.', 'AUTH_PROVIDER_UNREACHABLE'); }
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).error?.message; } catch {}
    const providerCode = typeof detail === 'string' ? detail.match(/^[A-Z][A-Z0-9_]+/)?.[0] : null;
    const invalid = new Set(['INVALID_ID_TOKEN', 'TOKEN_EXPIRED', 'USER_NOT_FOUND', 'USER_DISABLED']);
    const code = providerCode && invalid.has(providerCode) ? `AUTH_${providerCode}` : 'AUTH_PROVIDER_REJECTED';
    throw new AuthError(response.status === 400 || response.status === 401 ? 401 : 503, 'Google could not verify your session. Please sign in again.', code);
  }
  const user = (await response.json()).users?.[0];
  if (!user || user.disabled || user.localId !== claims.sub || !user.emailVerified) throw new AuthError(401, 'This Google account could not be verified. Please sign in again.', 'AUTH_ACCOUNT_REJECTED');
  if (user.validSince && claims.auth_time < Number(user.validSince)) throw new AuthError(401, 'Your session was revoked. Please sign in with Google again.', 'AUTH_SESSION_REVOKED');
  return { token, uid:user.localId, email:user.email ?? '', displayName:user.displayName ?? '', photoURL:user.photoUrl ?? '', expiresAt:claims.exp };
}
async function membershipFor(user, env) {
  const project = encodeURIComponent(env.FIREBASE_PROJECT_ID), uid = encodeURIComponent(user.uid);
  const database = encodeURIComponent(env.FIREBASE_DATABASE_ID?.trim() || '(default)');
  const free = {plan:'guest', expiresAt:null};
  let response;
  try {
    response = await fetch(`https://firestore.googleapis.com/v1/projects/${project}/databases/${database}/documents/users/${uid}`, {
      headers:{authorization:`Bearer ${user.token}`}, signal:AbortSignal.timeout(10000)
    });
  } catch { throw new AuthError(503, 'The server could not reach your account storage. Please try again.', 'AUTH_PROFILE_UNREACHABLE'); }
  if (response.status === 404) return free;
  if (!response.ok) throw new AuthError(503, 'Your account could not be read. Please contact support if retrying does not help.', response.status === 403 ? 'AUTH_PROFILE_READ_DENIED' : 'AUTH_PROFILE_UNAVAILABLE');
  const fields = (await response.json()).fields ?? {}, plan = fields.plan?.stringValue;
  const expiresAt = fields.expiresAt?.timestampValue;
  // Access always has an end date, validated against the server clock.
  if (!PAID_PLANS.has(plan) || typeof expiresAt !== 'string' || !Number.isFinite(Date.parse(expiresAt))) return free;
  return {plan:Date.parse(expiresAt) > Date.now() ? plan : 'guest', expiresAt:new Date(expiresAt).toISOString()};
}
function publicAccount(user, membership) {
  return { uid:user.uid, email:user.email, displayName:user.displayName, photoURL:user.photoURL,
    plan:membership.plan, membershipExpiresAt:membership.expiresAt };
}
function authorizeFeed(feed, plan) {
  const fantasy = book => ['PrizePicks', 'Underdog'].includes(book);
  return { ...feed,
    ev:feed.ev.filter(row => plan === 'platinum' || (!row.live && (plan === 'fantasyplus' || (['gold', 'plus'].includes(plan) && !fantasy(row.book)) || (plan === 'fantasy' && fantasy(row.book))))),
    arbs:['plus', 'platinum'].includes(plan) ? feed.arbs : []
  };
}
export { AuthError, firebaseConfig, sessionCookie, sameOrigin, authenticate, membershipFor, publicAccount, authorizeFeed, PAID_PLANS };
