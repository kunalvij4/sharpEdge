import assert from 'node:assert/strict';
import vm from 'node:vm';
import worker from '../dist/server/index.js';
import {env, tokenFor, firebaseMock, membershipExpiry} from './firebase-fixture.mjs';
import {membershipFor} from '../worker/auth.js';

const origin = 'https://sharpedge.test', token = tokenFor();
const request = (path, options = {}) => worker.fetch(new Request(origin+path, options), env);
const signed = (path, options = {}) => request(path, {...options, headers:{authorization:`Bearer ${token}`, ...options.headers}});
let feedReads = 0;
const fixture = [
  {id:'sports', book:'FanDuel', wager_display:'Home ML', market:'moneyline', odds:2, model_probability:.55, league:'NBA'},
  {id:'fantasy', book:'Underdog Fantasy', wager_display:'Player Over 5.5', market:'player_rebounds', odds:2, model_probability:.6, league:'NBA'},
  {id:'live', book:'FanDuel', wager_display:'Live ML', market:'moneyline', odds:2, model_probability:.55, live:true, league:'NBA'}
];
const feed = async (_url, options) => {
  feedReads++;
  const [command, key] = JSON.parse(options.body);
  return Response.json({result:command === 'TYPE' ? 'string' : JSON.stringify({opportunities:key === 'EV' ? fixture : [{book1:'FanDuel', book2:'DraftKings', odds1:2.1, odds2:2.1, side1:'Home', side2:'Away', match:'A vs B'}]})});
};
const mock = options => { globalThis.fetch = firebaseMock({token, feed, ...options}); };
mock();
for (const path of ['/api/feeds', '/api/account']) assert.equal((await request(path)).status, 401);
for (const path of ['/ev', '/arbitrage', '/parlay', '/analysis']) {
  const response = await request(path);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get('location'), '/signin?next='+encodeURIComponent(path));
  assert.equal(await response.text(), '');
}
assert.equal(feedReads, 0, 'Anonymous requests never query Redis');
for (const path of ['/', '/signin', '/app.js', '/auth.js', '/account-ui.js']) assert.equal((await request(path)).status, 200);
const publicConfig = await (await request('/api/auth/config')).json();
assert.deepEqual(Object.keys(publicConfig).sort(), ['apiKey','appId','authDomain','databaseId','projectId']);
assert.equal(publicConfig.databaseId, '(default)');
assert.ok(!JSON.stringify(publicConfig).includes(env.LAYERBASE_REST_TOKEN));
assert.equal((await worker.fetch(new Request(origin+'/api/auth/config'), {})).status, 503);
assert.equal((await request('/api/session')).status, 405);
assert.equal((await signed('/api/feeds', {method:'POST'})).status, 405);
for (const method of ['POST','DELETE']) {
  assert.equal((await signed('/api/session', {method, headers:{origin:'https://evil.test'}})).status, 403);
  assert.equal((await signed('/api/session', {method})).status, 403);
}
const login = await signed('/api/session', {method:'POST', headers:{origin}});
assert.equal(login.status, 200);
assert.deepEqual(await login.json(), {uid:'alice',email:'alice@example.test',displayName:'Alice',photoURL:'',plan:'platinum',membershipExpiresAt:membershipExpiry});
const cookie = login.headers.get('set-cookie');
for (const flag of ['__Host-se-session=', 'Path=/', 'HttpOnly', 'Secure', 'SameSite=Lax']) assert.ok(cookie.includes(flag));
assert.ok(Number(cookie.match(/Max-Age=(\d+)/)[1]) <= 3600);
const html = await (await request('/parlay', {headers:{cookie}})).text();
assert.match(html, /window\.__SHARPEDGE_FEED__/);
assert.match(html, /"sourceId":"fantasy"/);
assert.doesNotMatch(html, /fixture-signature|test-server-secret|test-public-key/);
const logout = await request('/api/session', {method:'DELETE', headers:{origin}});
assert.equal(logout.status, 200);
assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
assert.equal((await request('/api/feeds', {headers:{cookie:logout.headers.get('set-cookie')}})).status, 401);
for (const overrides of [{exp:1}, {iat:Date.now()/1000+500}, {auth_time:Date.now()/1000+500}, {aud:'foreign-project'}, {iss:'https://evil.test'}, {firebase:{sign_in_provider:'anonymous'}}, {email_verified:false}, {sub:''}]) {
  const bad = tokenFor(overrides);
  assert.equal((await request('/api/feeds', {headers:{authorization:`Bearer ${bad}`}})).status, 401);
}
// A freshly issued token remains valid when the local clock is slightly behind
// Google. Firebase must still verify the token; expiration remains strict.
const ahead = tokenFor({iat:Math.floor(Date.now()/1000)+2,auth_time:Math.floor(Date.now()/1000)+2});
globalThis.fetch = firebaseMock({token:ahead, feed});
assert.equal((await request('/api/session',{method:'POST',headers:{origin,authorization:`Bearer ${ahead}`}})).status,200);
mock();
const expired = await request('/api/session',{method:'POST',headers:{origin,authorization:`Bearer ${tokenFor({exp:1})}`}});
assert.equal(expired.status,401);
assert.equal((await expired.json()).code,'AUTH_TOKEN_EXPIRED');
const wrongOrigin = await signed('/api/session',{method:'POST',headers:{origin:'https://evil.test'}});
assert.equal((await wrongOrigin.json()).code,'SESSION_ORIGIN_MISMATCH');
assert.equal((await request('/api/feeds', {headers:{authorization:'Bearer not.a.token'}})).status, 401);
// A plausible JWT with a tampered signature must still pass Firebase's validation.
const forged = token.replace('fixture-signature','forged-signature');
assert.equal((await request('/api/feeds', {headers:{authorization:`Bearer ${forged}`}})).status, 401);
for (const options of [{disabled:true}, {validSince:String(Math.floor(Date.now()/1000))}]) {
  mock(options);
  assert.equal((await signed('/api/feeds')).status, 401);
}
for (const options of [{missing:true}, {expiresAt:null}, {plan:'admin'}, {expiresAt:'2000-01-01T00:00:00Z'}, {expiresAt:'invalid'}, {expiryField:{stringValue:membershipExpiry}}]) {
  mock(options);
  const response = await signed('/api/feeds', {headers:{cookie:'se-plan=platinum', 'x-plan':'platinum'}});
  assert.equal(response.status, 403, 'Missing, incorrectly typed and expired dates cannot grant market access');
  assert.equal((await signed('/analysis')).status, 200, 'Signed-in accounts can open their journal');
}
// Freeze only the membership clock to verify the exact expiry boundary without sleeping.
const realNow = Date.now, cutoff = realNow() + 60000;
try {
  Date.now = () => cutoff;
  for (const [offset, expected] of [[-1,'guest'], [0,'guest'], [1,'platinum']]) {
    mock({expiresAt:new Date(cutoff + offset).toISOString()});
    const membership = await membershipFor({uid:'alice',token}, env);
    assert.equal(membership.plan, expected, 'Access ends at the expiration instant');
  }
} finally { Date.now = realNow; }
// An extension is visible immediately on the next request, without rotating ID tokens.
mock({expiresAt:'2000-01-01T00:00:00Z'});
assert.equal((await signed('/api/feeds')).status, 403);
mock({expiresAt:membershipExpiry});
assert.equal((await signed('/api/feeds')).status, 200);
const restoredEnv = {...env,FIREBASE_DATABASE_ID:'sharpedge-restored'};
mock({databaseId:restoredEnv.FIREBASE_DATABASE_ID});
const restoredConfig = await (await worker.fetch(new Request(origin+'/api/auth/config'),restoredEnv)).json();
assert.equal(restoredConfig.databaseId, 'sharpedge-restored');
assert.equal((await worker.fetch(new Request(origin+'/api/account',{headers:{authorization:`Bearer ${token}`}}),restoredEnv)).status,200);
for (const [plan, ids, arbCount] of [
  ['gold',['sports'],0], ['plus',['sports'],1], ['fantasy',['fantasy'],0],
  ['fantasyplus',['sports','fantasy'],0], ['platinum',['sports','fantasy','live'],1]
]) {
  mock({plan});
  const response = await signed('/api/feeds');
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.ev.map(row=>row.sourceId).sort(), ids.sort());
  assert.equal(body.arbs.length, arbCount);
}
mock({membershipStatus:403});
assert.equal((await signed('/api/feeds')).status, 503, 'Membership lookup failures fail closed');
const deniedProfile = await signed('/api/session',{method:'POST',headers:{origin}});
assert.equal(deniedProfile.status,503);
assert.equal((await deniedProfile.json()).code,'AUTH_PROFILE_READ_DENIED');
mock({displayName:'</script><script>alert(1)</script>'});
const escaped = await (await signed('/ev')).text();
assert.doesNotMatch(escaped, /<script>alert\(1\)<\/script>/);
const boot = {window:{}};
vm.runInNewContext(escaped.match(/<script>(window\.__SHARPEDGE_SERVER__=.*?)<\/script>/)[1], boot);
assert.equal(boot.window.__SHARPEDGE_ACCOUNT__.displayName, '</script><script>alert(1)</script>');
mock({feed:async()=>{throw new Error('test outage')}});
const unavailable = await signed('/api/feeds');
assert.equal(unavailable.status, 503);
assert.deepEqual(await unavailable.json(), {error:'Feed temporarily unavailable'});
console.log('Authentication tests passed: protected pages/APIs, verified sessions, CSRF, revocation, expiration boundaries, renewals, restored databases and plan-filtered feeds.');
