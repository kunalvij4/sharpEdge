import { AuthError, membershipFor, publicAccount } from './auth.js';

// HTTPS and Web Crypto keep billing compatible with both Workers and local Node.
const STRIPE_API_VERSION = '2026-10-28.endive';
const BILLING_PLANS = { gold:'STRIPE_PRICE_GOLD', plus:'STRIPE_PRICE_PLUS', fantasy:'STRIPE_PRICE_FANTASY', fantasyplus:'STRIPE_PRICE_FANTASY_PLUS', platinum:'STRIPE_PRICE_PLATINUM' };
const billingFailure = () => new AuthError(503, 'Payments are temporarily unavailable. Please try again later.', 'BILLING_UNAVAILABLE');
const encoder = new TextEncoder();
let googleAccess;
const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const encodeJSON = value => base64url(encoder.encode(JSON.stringify(value)));
const objectID = value => typeof value === 'string' ? value : value?.id;

function billingConfig(env) {
  if (!env.STRIPE_SECRET_KEY?.trim() || !env.STRIPE_WEBHOOK_SECRET?.trim() || !env.FIREBASE_CLIENT_EMAIL?.trim() || !env.FIREBASE_PRIVATE_KEY?.trim()) throw billingFailure();
}
async function stripeRequest(env, path, params, idempotencyKey) {
  if (!env.STRIPE_SECRET_KEY?.trim()) throw billingFailure();
  let response;
  try {
    response = await fetch(`https://api.stripe.com/v1/${path}`, {
      method:params ? 'POST' : 'GET',
      headers:{authorization:`Bearer ${env.STRIPE_SECRET_KEY.trim()}`, 'Stripe-Version':STRIPE_API_VERSION,
        ...(params ? {'content-type':'application/x-www-form-urlencoded'} : {}),
        ...(idempotencyKey ? {'Idempotency-Key':idempotencyKey} : {})},
      ...(params ? {body:new URLSearchParams(params).toString()} : {}), signal:AbortSignal.timeout(15000)
    });
  } catch { throw billingFailure(); }
  // Stripe error bodies can contain customer data. Never return or log them.
  if (!response.ok) throw billingFailure();
  return response.json();
}
async function googleToken(env) {
  const identity = `${env.FIREBASE_CLIENT_EMAIL}:${env.FIREBASE_PRIVATE_KEY}`;
  if (googleAccess?.identity === identity && googleAccess.expiresAt > Date.now() + 60000) return googleAccess.token;
  if (!env.FIREBASE_CLIENT_EMAIL || !env.FIREBASE_PRIVATE_KEY) throw billingFailure();
  try {
    const pem = env.FIREBASE_PRIVATE_KEY.replace(/\\n/g, '\n').replace(/-----[^-]+-----|\s/g, '');
    const key = await crypto.subtle.importKey('pkcs8', Uint8Array.from(atob(pem), c => c.charCodeAt(0)), {name:'RSASSA-PKCS1-v1_5', hash:'SHA-256'}, false, ['sign']);
    const now = Math.floor(Date.now() / 1000);
    const content = `${encodeJSON({alg:'RS256', typ:'JWT'})}.${encodeJSON({iss:env.FIREBASE_CLIENT_EMAIL, scope:'https://www.googleapis.com/auth/datastore', aud:'https://oauth2.googleapis.com/token', iat:now, exp:now + 3600})}`;
    const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, encoder.encode(content));
    const response = await fetch('https://oauth2.googleapis.com/token', {
      method:'POST', headers:{'content-type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({grant_type:'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion:`${content}.${base64url(new Uint8Array(signature))}`}).toString(), signal:AbortSignal.timeout(10000)
    });
    if (!response.ok) throw billingFailure();
    const result = await response.json();
    if (!result.access_token || !Number.isFinite(result.expires_in)) throw billingFailure();
    googleAccess = {identity, token:result.access_token, expiresAt:Date.now() + result.expires_in * 1000};
    return result.access_token;
  } catch { throw billingFailure(); }
}
function documentRoot(env) {
  if (!env.FIREBASE_PROJECT_ID) throw billingFailure();
  return `projects/${encodeURIComponent(env.FIREBASE_PROJECT_ID)}/databases/${encodeURIComponent(env.FIREBASE_DATABASE_ID?.trim() || '(default)')}/documents`;
}
async function firestoreRequest(env, path, body) {
  let response;
  try {
    response = await fetch(`https://firestore.googleapis.com/v1/${documentRoot(env)}${path}`, {
      method:body ? 'POST' : 'GET', headers:{authorization:`Bearer ${await googleToken(env)}`, 'content-type':'application/json'},
      ...(body ? {body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(10000)
    });
  } catch { throw billingFailure(); }
  if (response.status === 404 && !body) return null;
  if ([409, 412].includes(response.status)) return false;
  if (!response.ok) {
    // Google can map a failed updateTime precondition to HTTP 400.
    const detail = await response.json().catch(() => ({}));
    if (body && ['ABORTED', 'FAILED_PRECONDITION'].includes(detail.error?.status)) return false;
    throw billingFailure();
  }
  return response.json();
}
const readBilling = (env, uid) => firestoreRequest(env, `/billingAccounts/${encodeURIComponent(uid)}`);
const field = (document, name) => document?.fields?.[name]?.stringValue;
function billingWrite(env, uid, document, values) {
  return {update:{name:`${documentRoot(env)}/billingAccounts/${encodeURIComponent(uid)}`, fields:Object.fromEntries(Object.entries(values).map(([key, value]) => [key, {stringValue:value}]))},
    updateMask:{fieldPaths:Object.keys(values)}, currentDocument:document?.updateTime ? {updateTime:document.updateTime} : {exists:false}};
}
const commitBilling = (env, writes) => firestoreRequest(env, ':commit', {writes});
function returnOrigin(request, env) {
  const url = new URL(env.APP_URL || request.url);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) throw billingFailure();
  return url.origin;
}
function scopeMetadata(env, uid) {
  return {uid, project:env.FIREBASE_PROJECT_ID, database:env.FIREBASE_DATABASE_ID?.trim() || '(default)'};
}
function belongsToApp(metadata, env) {
  return metadata?.project === env.FIREBASE_PROJECT_ID && metadata?.database === (env.FIREBASE_DATABASE_ID?.trim() || '(default)');
}
async function customerFor(user, env) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const record = await readBilling(env, user.uid);
    if (field(record, 'customerId')) return field(record, 'customerId');
    const metadata = scopeMetadata(env, user.uid);
    const digest = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(JSON.stringify(metadata)))));
    const customer = await stripeRequest(env, 'customers', {email:user.email, ...Object.fromEntries(Object.entries(metadata).map(([key, value]) => [`metadata[${key}]`, value]))}, `sharpedge-customer-${digest}`);
    if (!customer.id) throw billingFailure();
    if (await commitBilling(env, [billingWrite(env, user.uid, record, {customerId:customer.id})])) return customer.id;
  }
  throw billingFailure();
}
async function activeSubscription(env, customer) {
  const result = await stripeRequest(env, `subscriptions?customer=${encodeURIComponent(customer)}&status=all&limit=100`);
  if (!Array.isArray(result.data) || result.has_more) throw billingFailure();
  return result.data.find(subscription => !['canceled', 'incomplete_expired'].includes(subscription.status));
}
async function portalSession(request, env, customer, subscription, price) {
  const returnURL = `${returnOrigin(request, env)}/#pricing`;
  const params = {customer, return_url:returnURL};
  if (subscription && price && ['active', 'trialing'].includes(subscription.status)) {
    const item = subscription.items?.data?.[0];
    if (!item?.id || subscription.items.data.length !== 1) throw billingFailure();
    if (objectID(item.price) !== price) Object.assign(params, {
      'flow_data[type]':'subscription_update_confirm', 'flow_data[subscription_update_confirm][subscription]':subscription.id,
      'flow_data[subscription_update_confirm][items][0][id]':item.id, 'flow_data[subscription_update_confirm][items][0][price]':price,
      'flow_data[subscription_update_confirm][items][0][quantity]':'1',
      'flow_data[after_completion][type]':'redirect', 'flow_data[after_completion][redirect][return_url]':returnURL
    });
  }
  const session = await stripeRequest(env, 'billing_portal/sessions', params);
  if (!session.url?.startsWith('https://billing.stripe.com/')) throw billingFailure();
  return {url:session.url};
}
async function createCheckout(request, env, user, plan) {
  if (!Object.hasOwn(BILLING_PLANS, plan)) throw new AuthError(400, 'Choose an available monthly plan.', 'BILLING_INVALID_PLAN');
  billingConfig(env);
  const price = env[BILLING_PLANS[plan]]?.trim();
  if (!price?.startsWith('price_')) throw new AuthError(503, 'This plan is not available for payment yet. Please try again later.', 'BILLING_PRICE_MISSING');
  // Verify the account exists before charging; membership writes require it.
  if (!await firestoreRequest(env, `/users/${encodeURIComponent(user.uid)}`)) throw new AuthError(409, 'Finish setting up your account before choosing a plan.', 'BILLING_PROFILE_MISSING');
  const customer = await customerFor(user, env);
  const subscription = await activeSubscription(env, customer);
  if (subscription) return portalSession(request, env, customer, subscription, price);
  const origin = returnOrigin(request, env), metadata = scopeMetadata(env, user.uid);
  const params = {mode:'subscription', customer, client_reference_id:user.uid,
    'line_items[0][price]':price, 'line_items[0][quantity]':'1',
    success_url:`${origin}/?checkout=success&session_id={CHECKOUT_SESSION_ID}#pricing`, cancel_url:`${origin}/?checkout=cancelled#pricing`,
    ...Object.fromEntries(Object.entries(metadata).flatMap(([key, value]) => [[`metadata[${key}]`, value], [`subscription_data[metadata][${key}]`, value]]))};
  // Repeated clicks/retries share a session without letting the browser set prices.
  const bucket = Math.floor(Date.now() / 1800000);
  const key = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(`${customer}:${price}:${bucket}`))));
  const session = await stripeRequest(env, 'checkout/sessions', params, `sharpedge-checkout-${key}`);
  if (!session.url?.startsWith('https://checkout.stripe.com/')) throw billingFailure();
  return {url:session.url};
}
async function createPortal(request, env, user) {
  billingConfig(env);
  const customer = field(await readBilling(env, user.uid), 'customerId');
  if (!customer) throw new AuthError(409, 'Choose a plan to start your membership first.', 'BILLING_CUSTOMER_MISSING');
  return portalSession(request, env, customer);
}

// Fetch current Stripe state and use Firestore preconditions so retries and
// out-of-order events cannot roll a newer subscription back to an old snapshot.
async function syncSubscription(env, subscriptionID) {
  let subscription = await stripeRequest(env, `subscriptions/${encodeURIComponent(subscriptionID)}?expand[]=latest_invoice`);
  if (!belongsToApp(subscription.metadata, env)) return;
  const uid = subscription.metadata.uid;
  if (typeof uid !== 'string' || !uid || uid.length > 128 || uid.includes('/')) throw billingFailure();
  for (let attempt = 0; attempt < 3; attempt++) {
    const record = await readBilling(env, uid);
    subscription = await stripeRequest(env, `subscriptions/${encodeURIComponent(subscriptionID)}?expand[]=latest_invoice`);
    if (!belongsToApp(subscription.metadata, env) || subscription.metadata.uid !== uid || objectID(subscription.customer) !== field(record, 'customerId')) throw billingFailure();
    const previousID = field(record, 'subscriptionId');
    if (previousID && previousID !== subscriptionID) {
      const previous = await stripeRequest(env, `subscriptions/${encodeURIComponent(previousID)}`);
      // An old cancellation must never revoke a replacement membership.
      if (!['canceled', 'incomplete_expired'].includes(previous.status)) return;
      if (['canceled', 'incomplete_expired'].includes(subscription.status)) return;
    }
    const account = await firestoreRequest(env, `/users/${encodeURIComponent(uid)}`);
    if (!account?.updateTime) throw billingFailure();
    const existingExpiry = account.fields?.expiresAt?.timestampValue;
    let plan = 'guest', expiresAt = null;
    if (subscription.status === 'active' && subscription.latest_invoice?.status === 'paid' && !subscription.pause_collection) {
      const items = subscription.items?.data;
      if (!Array.isArray(items) || items.length !== 1) throw billingFailure();
      plan = Object.keys(BILLING_PLANS).find(id => env[BILLING_PLANS[id]]?.trim() === objectID(items[0].price));
      const end = items[0].current_period_end;
      if (!plan || !Number.isFinite(end) || end <= 0) throw billingFailure();
      expiresAt = new Date(end * 1000).toISOString();
    } else if (['active', 'past_due'].includes(subscription.status) && previousID === subscriptionID && Date.parse(existingExpiry) > Date.now()) {
      // An unpaid renewal does not extend the last paid access period.
      plan = field(account, 'plan') || 'guest'; expiresAt = existingExpiry;
    }
    const writes = [billingWrite(env, uid, record, {subscriptionId:subscriptionID, status:subscription.status}), {
      update:{name:`${documentRoot(env)}/users/${encodeURIComponent(uid)}`, fields:{plan:{stringValue:plan}, expiresAt:expiresAt ? {timestampValue:expiresAt} : {nullValue:null}}},
      updateMask:{fieldPaths:['plan', 'expiresAt']}, currentDocument:{updateTime:account.updateTime}
    }];
    if (await commitBilling(env, writes)) return;
  }
  throw billingFailure();
}
async function checkoutStatus(env, user, sessionID) {
  if (!/^cs_[A-Za-z0-9_]+$/.test(sessionID || '')) throw new AuthError(400, 'The checkout session is invalid.', 'BILLING_INVALID_SESSION');
  const session = await stripeRequest(env, `checkout/sessions/${encodeURIComponent(sessionID)}`);
  if (session.client_reference_id !== user.uid || !belongsToApp(session.metadata, env)) throw new AuthError(403, 'This checkout belongs to a different account.', 'BILLING_SESSION_FORBIDDEN');
  const paid = session.status === 'complete' && session.payment_status === 'paid' && session.mode === 'subscription';
  if (paid && objectID(session.subscription)) await syncSubscription(env, objectID(session.subscription));
  return {status:paid ? 'paid' : 'pending', account:publicAccount(user, await membershipFor(user, env))};
}
async function verifyStripeEvent(request, env) {
  if (!env.STRIPE_WEBHOOK_SECRET) throw billingFailure();
  const signature = request.headers.get('stripe-signature') || '';
  const timestamp = signature.match(/(?:^|,)t=(\d+)(?:,|$)/)?.[1];
  const signatures = [...signature.matchAll(/(?:^|,)v1=([a-fA-F0-9]{64})(?=,|$)/g)].map(match => match[1]);
  if (!timestamp || Math.abs(Date.now() / 1000 - Number(timestamp)) > 300 || !signatures.length) throw new AuthError(400, 'Invalid webhook signature.', 'BILLING_INVALID_SIGNATURE');
  const body = await request.text();
  const key = await crypto.subtle.importKey('raw', encoder.encode(env.STRIPE_WEBHOOK_SECRET), {name:'HMAC', hash:'SHA-256'}, false, ['verify']);
  const valid = await Promise.all(signatures.map(value => crypto.subtle.verify('HMAC', key, Uint8Array.from(value.match(/../g), hex => parseInt(hex, 16)), encoder.encode(`${timestamp}.${body}`))));
  if (!valid.some(Boolean)) throw new AuthError(400, 'Invalid webhook signature.', 'BILLING_INVALID_SIGNATURE');
  try { return JSON.parse(body); }
  catch { throw new AuthError(400, 'Invalid webhook payload.', 'BILLING_INVALID_PAYLOAD'); }
}
async function stripeWebhook(request, env) {
  const event = await verifyStripeEvent(request, env), object = event.data?.object;
  let subscriptionID;
  if (['checkout.session.completed', 'checkout.session.async_payment_succeeded'].includes(event.type)) {
    if (object?.mode === 'subscription' && object.payment_status === 'paid') subscriptionID = objectID(object.subscription);
  } else if (['customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'].includes(event.type)) subscriptionID = object?.id;
  else if (['invoice.paid', 'invoice.payment_failed'].includes(event.type)) subscriptionID = objectID(object?.parent?.subscription_details?.subscription || object?.subscription);
  if (subscriptionID) await syncSubscription(env, subscriptionID);
  return {received:true};
}

export { createCheckout, createPortal, checkoutStatus, stripeWebhook };
