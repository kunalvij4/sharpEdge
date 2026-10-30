export const env = {
  FIREBASE_API_KEY:'test-public-key', FIREBASE_PROJECT_ID:'sharpedge-test',
  FIREBASE_AUTH_DOMAIN:'sharpedge-test.firebaseapp.com', FIREBASE_APP_ID:'test-app',
  LAYERBASE_REST_URL:'https://redis.test.invalid', LAYERBASE_REST_TOKEN:'test-server-secret'
};
export const membershipExpiry = new Date(Date.now() + 30 * 86400000).toISOString();
export function tokenFor(overrides = {}) {
  const now = Math.floor(Date.now() / 1000);
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  return [encode({alg:'RS256', kid:'test'}), encode({
    aud:env.FIREBASE_PROJECT_ID, iss:`https://securetoken.google.com/${env.FIREBASE_PROJECT_ID}`,
    sub:'alice', email:'alice@example.test', email_verified:true, iat:now-10, auth_time:now-10, exp:now+3500,
    firebase:{sign_in_provider:'google.com'}, ...overrides
  }), 'fixture-signature'].join('.');
}
export function firebaseMock({token, plan = 'platinum', expiresAt = membershipExpiry, expiryField, databaseId = '(default)', missing = false, disabled = false, validSince = '0', displayName = 'Alice', upstreamStatus = 200, membershipStatus = 200, feed} = {}) {
  return async (url, options = {}) => {
    url = String(url);
    if (url.startsWith('https://identitytoolkit.googleapis.com/')) {
      if (JSON.parse(options.body).idToken !== token) return Response.json({error:{message:'INVALID_ID_TOKEN'}}, {status:400});
      return Response.json({users:[{localId:'alice', email:'alice@example.test', emailVerified:true, displayName, disabled, validSince}]}, {status:upstreamStatus});
    }
    if (url.startsWith('https://firestore.googleapis.com/')) {
      if (!url.endsWith(`/databases/${encodeURIComponent(databaseId)}/documents/users/alice`) || options.headers.authorization !== `Bearer ${token}`) throw new Error('Wrong user profile, database or token');
      if (missing) return Response.json({}, {status:404});
      return Response.json({fields:{plan:{stringValue:plan}, ...(expiryField ? {expiresAt:expiryField} : expiresAt !== null ? {expiresAt:{timestampValue:expiresAt}} : {})}}, {status:membershipStatus});
    }
    if (feed) return feed(url, options);
    throw new Error('Unexpected network request');
  };
}
