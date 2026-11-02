import assert from 'node:assert/strict';
import { createHmac, generateKeyPairSync, verify } from 'node:crypto';
import worker from '../dist/server/index.js';
import { env as firebaseEnv, tokenFor, firebaseMock } from './firebase-fixture.mjs';

const origin = 'https://sharpedge.test', token = tokenFor();
const {privateKey, publicKey} = generateKeyPairSync('rsa', {modulusLength:2048});
const env = {...firebaseEnv, APP_URL:origin, STRIPE_SECRET_KEY:'sk_test_server_only', STRIPE_WEBHOOK_SECRET:'whsec_server_only',
  STRIPE_PRICE_GOLD:'price_gold', STRIPE_PRICE_PLUS:'price_plus', STRIPE_PRICE_FANTASY:'price_fantasy', STRIPE_PRICE_FANTASY_PLUS:'price_fantasy_plus', STRIPE_PRICE_PLATINUM:'price_platinum',
  FIREBASE_CLIENT_EMAIL:'billing@sharpedge-test.iam.gserviceaccount.com', FIREBASE_PRIVATE_KEY:privateKey.export({type:'pkcs8', format:'pem'}).replace(/\n/g, '\\n')};
const scope = {uid:'alice', project:env.FIREBASE_PROJECT_ID, database:'(default)'};
const root = `projects/${env.FIREBASE_PROJECT_ID}/databases/(default)/documents`;
const future = Math.floor(Date.now() / 1000) + 30 * 86400;
const expiry = new Date(future * 1000).toISOString();
let documents, calls, subscriptions, sessions, revision, failStripe, conflicts;
function reset() {
  documents = new Map([['users/alice', {name:`${root}/users/alice`, updateTime:'version-0', fields:{plan:{stringValue:'guest'}, expiresAt:{nullValue:null},
    bankroll:{integerValue:'2500'}, betHistory:{arrayValue:{values:[{stringValue:'journal-to-preserve'}]}}, signupDate:{timestampValue:'2026-01-01T00:00:00Z'}}}]]);
  calls = []; subscriptions = new Map(); sessions = new Map(); revision = 0; failStripe = false; conflicts = 0;
}
const getField = (path, name) => documents.get(path)?.fields[name];
const basicFirebase = firebaseMock({token, plan:'guest'});
globalThis.fetch = async (input, options = {}) => {
  const url = new URL(input);
  if (url.hostname === 'identitytoolkit.googleapis.com') return basicFirebase(input, options);
  if (url.hostname === 'oauth2.googleapis.com') {
    const assertion = new URLSearchParams(options.body).get('assertion');
    const [header, payload, signature] = assertion.split('.');
    assert.equal(verify('RSA-SHA256', Buffer.from(`${header}.${payload}`), publicKey, Buffer.from(signature, 'base64url')), true);
    const claims = JSON.parse(Buffer.from(payload, 'base64url'));
    assert.equal(claims.iss, env.FIREBASE_CLIENT_EMAIL);
    assert.equal(claims.scope, 'https://www.googleapis.com/auth/datastore');
    return Response.json({access_token:'server-google-access', expires_in:3600});
  }
  if (url.hostname === 'firestore.googleapis.com') {
    assert.ok([`Bearer ${token}`, 'Bearer server-google-access'].includes(options.headers.authorization));
    const path = decodeURIComponent(url.pathname).split('/documents')[1];
    if (path === ':commit') {
      assert.equal(options.headers.authorization, 'Bearer server-google-access');
      if (conflicts-- > 0) return Response.json({error:{status:'FAILED_PRECONDITION'}}, {status:400});
      const {writes} = JSON.parse(options.body);
      for (const write of writes) {
        const name = write.update.name.slice(root.length + 1), doc = documents.get(name);
        if ((write.currentDocument?.exists === false && doc) || (write.currentDocument?.updateTime && doc?.updateTime !== write.currentDocument.updateTime)) return Response.json({}, {status:409});
      }
      for (const write of writes) {
        const name = write.update.name.slice(root.length + 1), previous = documents.get(name);
        const fields = {...previous?.fields};
        for (const key of write.updateMask.fieldPaths) fields[key] = write.update.fields[key];
        documents.set(name, {name:write.update.name, fields, updateTime:`version-${++revision}`});
      }
      return Response.json({writeResults:[]});
    }
    const doc = documents.get(path.slice(1));
    return doc ? Response.json(doc) : Response.json({}, {status:404});
  }
  if (url.hostname === 'api.stripe.com') {
    assert.equal(options.headers.authorization, `Bearer ${env.STRIPE_SECRET_KEY}`);
    assert.equal(options.headers['Stripe-Version'], '2026-10-28.endive');
    const path = url.pathname.slice(4), params = new URLSearchParams(options.body);
    calls.push({path, params, headers:options.headers});
    if (failStripe) return Response.json({error:{message:'sensitive upstream detail', key:env.STRIPE_SECRET_KEY}}, {status:500});
    if (path === 'customers') return Response.json({id:'cus_alice'});
    if (path === 'subscriptions') return Response.json({data:[...subscriptions.values()], has_more:false});
    if (path.startsWith('subscriptions/')) {
      const sub = subscriptions.get(path.slice('subscriptions/'.length));
      return sub ? Response.json(sub) : Response.json({}, {status:404});
    }
    if (path === 'checkout/sessions') return Response.json({id:'cs_test_created', url:'https://checkout.stripe.com/c/pay/cs_test_created'});
    if (path.startsWith('checkout/sessions/')) return Response.json(sessions.get(path.slice('checkout/sessions/'.length)));
    if (path === 'billing_portal/sessions') return Response.json({url:'https://billing.stripe.com/p/session/test'});
  }
  throw new Error('Unexpected network request: '+url.origin+url.pathname);
};
const request = (path, options = {}, config = env) => worker.fetch(new Request(origin + path, options), config);
const signed = (path, options = {}, config) => request(path, {...options, headers:{authorization:`Bearer ${token}`, origin, ...options.headers}}, config);
const choose = (plan = 'gold', config) => signed('/api/billing/checkout', {method:'POST', body:JSON.stringify({plan, price:'price_attacker', uid:'bob', success_url:'https://evil.test'})}, config);
const currentSubscription = (patch = {}) => ({id:'sub_alice', customer:'cus_alice', metadata:scope, status:'active',
  latest_invoice:{id:'in_paid', status:'paid'}, items:{data:[{id:'si_alice', price:{id:'price_gold'}, current_period_end:future}]}, ...patch});
function webhook(type, object, {timestamp = Math.floor(Date.now() / 1000), secret = env.STRIPE_WEBHOOK_SECRET, alterBody = false, rotate = false} = {}) {
  let body = JSON.stringify({id:'evt_test', type, data:{object}});
  const digest = createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex');
  if (alterBody) body += ' ';
  return request('/api/billing/webhook', {method:'POST', body, headers:{'stripe-signature':`t=${timestamp},${rotate ? 'v1='+'0'.repeat(64)+',' : ''}v1=${digest}`}});
}
async function prepareCustomer() {
  assert.equal((await choose()).status, 200);
  calls = [];
}

reset();
assert.equal((await request('/api/billing/checkout', {method:'POST', headers:{origin}, body:'{"plan":"gold"}'})).status, 401);
assert.equal((await signed('/api/billing/checkout', {method:'POST', headers:{origin:'https://evil.test'}, body:'{"plan":"gold"}'})).status, 403);
assert.equal((await signed('/api/billing/checkout', {method:'DELETE'})).status, 405);
assert.equal((await signed('/api/billing/checkout', {method:'POST', body:'invalid json'})).status, 400);
for (const plan of ['admin', 'fantasy_plus', '__proto__', null]) assert.equal((await choose(plan)).status, 400);
assert.equal(calls.length, 0, 'Rejected requests never call Stripe');
assert.equal((await choose('gold', {...env, STRIPE_PRICE_GOLD:''})).status, 503);
assert.equal((await choose('fantasyplus', {...env, STRIPE_PRICE_FANTASY_PLUS:''})).status, 503);
assert.equal((await choose('gold', {...env, FIREBASE_PRIVATE_KEY:''})).status, 503);
assert.equal((await choose('gold', {...env, STRIPE_WEBHOOK_SECRET:''})).status, 503);
for (const plan of ['gold','plus','fantasy','fantasyplus','platinum']) {
  const response = await choose(plan);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).url, 'https://checkout.stripe.com/c/pay/cs_test_created');
  const checkout = calls.filter(call => call.path === 'checkout/sessions').at(-1);
  assert.equal(checkout.params.get('line_items[0][price]'), env[plan === 'fantasyplus' ? 'STRIPE_PRICE_FANTASY_PLUS' : 'STRIPE_PRICE_' + plan.toUpperCase()]);
  assert.equal(checkout.params.get('mode'), 'subscription');
  assert.equal(checkout.params.get('customer'), 'cus_alice');
  assert.equal(checkout.params.get('client_reference_id'), 'alice');
  assert.equal(checkout.params.get('subscription_data[metadata][uid]'), 'alice');
  assert.equal(checkout.params.get('success_url'), origin+'/?checkout=success&session_id={CHECKOUT_SESSION_ID}#pricing');
  assert.equal(checkout.params.get('cancel_url'), origin+'/?checkout=cancelled#pricing');
  assert.ok(checkout.headers['Idempotency-Key']);
  assert.equal(checkout.params.has('price_attacker'), false);
  assert.equal(getField('users/alice', 'plan').stringValue, 'guest', 'Starting Checkout cannot grant access');
}
assert.equal(calls.filter(call => call.path === 'customers').length, 1, 'The customer is reused');
const lastCheckout = calls.filter(call => call.path === 'checkout/sessions').at(-1);
await choose('platinum');
assert.deepEqual(calls.at(-1), lastCheckout, 'Repeated clicks use the same Stripe idempotency key and payload');
const config = JSON.stringify(await (await request('/api/auth/config')).json());
for (const secret of [env.STRIPE_SECRET_KEY, env.STRIPE_WEBHOOK_SECRET, env.FIREBASE_CLIENT_EMAIL, 'PRIVATE KEY']) assert.ok(!config.includes(secret));
failStripe = true;
const failed = await choose();
assert.equal(failed.status, 503);
assert.doesNotMatch(await failed.text(), /sensitive|sk_test/);
failStripe = false;

subscriptions.set('sub_alice', currentSubscription());
calls = [];
assert.equal((await choose('plus')).status, 200);
assert.equal(calls.some(call => call.path === 'checkout/sessions'), false, 'Existing subscriptions do not create duplicate subscriptions');
const portal = calls.find(call => call.path === 'billing_portal/sessions');
assert.equal(portal.params.get('flow_data[subscription_update_confirm][items][0][price]'), 'price_plus');
assert.equal(portal.params.get('flow_data[subscription_update_confirm][subscription]'), 'sub_alice');
assert.equal((await choose('fantasyplus')).status, 200);
assert.equal(calls.at(-1).params.get('flow_data[subscription_update_confirm][items][0][price]'), 'price_fantasy_plus');
assert.equal((await signed('/api/billing/portal', {method:'POST'})).status, 200);

reset();
await prepareCustomer();
subscriptions.set('sub_alice', currentSubscription());
assert.equal((await request('/api/billing/webhook', {method:'POST', body:'{}'})).status, 400);
assert.equal((await webhook('customer.subscription.updated', {id:'sub_alice'}, {secret:'wrong'})).status, 400);
assert.equal((await webhook('customer.subscription.updated', {id:'sub_alice'}, {alterBody:true})).status, 400);
assert.equal((await webhook('customer.subscription.updated', {id:'sub_alice'}, {timestamp:1})).status, 400);
assert.equal(getField('users/alice', 'plan').stringValue, 'guest');
assert.equal((await webhook('checkout.session.completed', {mode:'subscription', payment_status:'unpaid', subscription:'sub_alice'})).status, 200);
assert.equal(getField('users/alice', 'plan').stringValue, 'guest', 'Unpaid Checkout cannot activate membership');
conflicts = 1;
assert.equal((await webhook('checkout.session.completed', {mode:'subscription', payment_status:'paid', subscription:'sub_alice'}, {rotate:true})).status, 200);
assert.equal(getField('users/alice', 'plan').stringValue, 'gold');
assert.equal(getField('users/alice', 'expiresAt').timestampValue, expiry);
assert.equal(getField('users/alice', 'bankroll').integerValue, '2500');
assert.equal(getField('users/alice', 'betHistory').arrayValue.values[0].stringValue, 'journal-to-preserve');
assert.equal((await webhook('invoice.paid', {parent:{subscription_details:{subscription:'sub_alice'}}})).status, 200);
assert.equal(getField('users/alice', 'expiresAt').timestampValue, expiry, 'Duplicate delivery is idempotent');
subscriptions.set('sub_alice', currentSubscription({status:'past_due', latest_invoice:{status:'open'}, items:{data:[{price:{id:'price_gold'}, current_period_end:future + 30 * 86400}]}}));
assert.equal((await webhook('invoice.payment_failed', {subscription:'sub_alice'})).status, 200);
assert.equal(getField('users/alice', 'expiresAt').timestampValue, expiry, 'Failed renewals never extend paid access');
subscriptions.set('sub_alice', currentSubscription({items:{data:[{price:{id:'price_gold'}, current_period_end:future + 30 * 86400}]}}));
assert.equal((await webhook('invoice.paid', {subscription:'sub_alice'})).status, 200);
assert.equal(getField('users/alice', 'expiresAt').timestampValue, new Date((future + 30 * 86400) * 1000).toISOString());
subscriptions.set('sub_alice', currentSubscription({cancel_at_period_end:true}));
await webhook('customer.subscription.updated', {id:'sub_alice'});
assert.equal(getField('users/alice', 'plan').stringValue, 'gold', 'End-of-period cancellation preserves paid access');
subscriptions.set('sub_alice', currentSubscription({status:'canceled'}));
await webhook('customer.subscription.updated', {id:'sub_alice', status:'active'});
assert.equal(getField('users/alice', 'plan').stringValue, 'guest', 'Out-of-order payloads use current Stripe state');

subscriptions.set('sub_new', currentSubscription({id:'sub_new', items:{data:[{price:{id:'price_plus'}, current_period_end:future}]}}));
await webhook('customer.subscription.created', {id:'sub_new'});
assert.equal(getField('users/alice', 'plan').stringValue, 'plus');
await webhook('customer.subscription.deleted', {id:'sub_alice'});
assert.equal(getField('users/alice', 'plan').stringValue, 'plus', 'An old cancellation cannot revoke a replacement');
subscriptions.set('sub_other_app', currentSubscription({id:'sub_other_app', metadata:{...scope, project:'other'}}));
await webhook('customer.subscription.updated', {id:'sub_other_app'});
assert.equal(getField('users/alice', 'plan').stringValue, 'plus');

reset();
await prepareCustomer();
subscriptions.set('sub_alice', currentSubscription());
sessions.set('cs_test_paid', {status:'complete', mode:'subscription', payment_status:'paid', client_reference_id:'alice', metadata:scope, subscription:'sub_alice'});
sessions.set('cs_test_bob', {...sessions.get('cs_test_paid'), client_reference_id:'bob'});
sessions.set('cs_test_pending', {...sessions.get('cs_test_paid'), payment_status:'unpaid'});
assert.equal((await signed('/api/billing/checkout?session_id=cs_test_bob')).status, 403);
assert.equal((await signed('/api/billing/checkout?session_id=invalid')).status, 400);
assert.equal((await (await signed('/api/billing/checkout?session_id=cs_test_pending')).json()).status, 'pending');
assert.equal(getField('users/alice', 'plan').stringValue, 'guest');
const status = await (await signed('/api/billing/checkout?session_id=cs_test_paid')).json();
assert.equal(status.status, 'paid');
assert.equal(status.account.uid, 'alice');
assert.equal(status.account.plan, 'gold', 'The verified return activates access without waiting for a webhook');
assert.equal(status.account.membershipExpiresAt, expiry);

reset();
await prepareCustomer();
subscriptions.set('sub_alice', currentSubscription({items:{data:[{price:{id:'price_fantasy_plus'}, current_period_end:future}]}}));
assert.equal((await webhook('checkout.session.completed', {mode:'subscription', payment_status:'paid', subscription:'sub_alice'})).status, 200);
assert.equal(getField('users/alice', 'plan').stringValue, 'fantasyplus', 'A paid Fantasy+ price activates the matching Firestore plan');
assert.equal(getField('users/alice', 'expiresAt').timestampValue, expiry);
assert.equal(getField('billingAccounts/alice', 'subscriptionId').stringValue, 'sub_alice');
console.log('Billing tests passed: authenticated plan checkout, server prices, customer reuse, portal changes, signed webhooks, renewals, cancellation, retries and verified returns.');
