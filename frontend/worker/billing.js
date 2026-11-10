import { AuthError, membershipFor, publicAccount } from './auth.js';

// HTTPS and Web Crypto keep billing compatible with both Workers and local Node.
const STRIPE_API_VERSION = '2026-10-28.endive';
const BILLING_PLANS = { gold:'STRIPE_PRICE_GOLD', plus:'STRIPE_PRICE_PLUS', fantasy:'STRIPE_PRICE_FANTASY', fantasyplus:'STRIPE_PRICE_FANTASY_PLUS', platinum:'STRIPE_PRICE_PLATINUM' };
const billingFailure = () => new AuthError(503, 'Payments are temporarily unavailable. Please try again later.', 'BILLING_UNAVAILABLE');
const encoder = new TextEncoder();
let googleAccess;
let portalConfiguration;
const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const encodeJSON = value => base64url(encoder.encode(JSON.stringify(value)));
const objectID = value => typeof value === 'string' ? value : value?.id;

function billingConfig(env) {
  if (!env.STRIPE_SECRET_KEY?.trim() || !env.STRIPE_WEBHOOK_SECRET?.trim() || !env.FIREBASE_CLIENT_EMAIL?.trim() || !env.FIREBASE_PRIVATE_KEY?.trim()) throw billingFailure();
}
async function stripeRequest(env, path, params, idempotencyKey, allowMissing = false) {
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
  if (response.status === 404 && allowMissing) return null;
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    console.error('Stripe request failed', {operation:path.split('?')[0].split('/')[0], status:response.status, code:detail.error?.code || 'unknown'});
    throw billingFailure();
  }
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
const digestBilling = async value => base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value))));
const customerOwnedBy = (customer, user, env) => customer && !customer.deleted && belongsToApp(customer.metadata, env) && customer.metadata.uid === user.uid;
async function linkCustomer(env, uid, customerID) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const record = await readBilling(env, uid);
    if (field(record, 'customerId') === customerID) return;
    const values = {customerId:customerID};
    if (field(record, 'customerId')) Object.assign(values, {subscriptionId:'', scheduledPlan:'', scheduledAt:''});
    if (await commitBilling(env, [billingWrite(env, uid, record, values)])) return;
  }
  throw billingFailure();
}
async function findCustomer(user, env, create = false) {
  const record = await readBilling(env, user.uid), customerID = field(record, 'customerId');
  if (customerID) {
    const customer = await stripeRequest(env, `customers/${encodeURIComponent(customerID)}?expand[]=invoice_settings.default_payment_method`, undefined, undefined, true);
    if (customer && !customer.deleted) {
      // A stored link is server-owned. If Stripe has ownership metadata, it must agree.
      if (customer.metadata?.uid && !customerOwnedBy(customer, user, env)) throw new AuthError(409, 'Your billing account needs to be reconciled. Please contact support.', 'BILLING_ACCOUNT_MISMATCH');
      return customer;
    }
  }
  // Recover a missing Firestore link using immutable Firebase identity, never email alone.
  const escapeQuery = value => String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  const query = Object.entries(scopeMetadata(env, user.uid)).map(([key, value]) => `metadata['${key}']:'${escapeQuery(value)}'`).join(' AND ');
  const result = await stripeRequest(env, `customers/search?query=${encodeURIComponent(query)}&limit=100`);
  if (!Array.isArray(result.data) || result.has_more) throw billingFailure();
  const candidates = result.data.filter(customer => customerOwnedBy(customer, user, env));
  let recovered;
  if (candidates.length === 1) recovered = candidates[0];
  else if (candidates.length > 1) {
    const active = [];
    for (const customer of candidates) if (await activeSubscription(env, customer.id)) active.push(customer);
    if (active.length > 1) throw new AuthError(409, 'Multiple active billing accounts were found. Please contact support before changing your plan.', 'BILLING_MULTIPLE_ACCOUNTS');
    recovered = active[0] || candidates.sort((a, b) => b.created - a.created)[0];
  }
  if (recovered) {
    await linkCustomer(env, user.uid, recovered.id);
    return stripeRequest(env, `customers/${encodeURIComponent(recovered.id)}?expand[]=invoice_settings.default_payment_method`);
  }
  if (!create) return null;
  const metadata = scopeMetadata(env, user.uid);
  const customer = await stripeRequest(env, 'customers', {email:user.email, ...Object.fromEntries(Object.entries(metadata).map(([key, value]) => [`metadata[${key}]`, value]))}, `sharpedge-customer-${await digestBilling(JSON.stringify(metadata))}`);
  if (!customer.id) throw billingFailure();
  await linkCustomer(env, user.uid, customer.id);
  return customer;
}
async function activeSubscription(env, customer) {
  let cursor, selected;
  for (let page = 0; page < 10; page++) {
    const result = await stripeRequest(env, `subscriptions?customer=${encodeURIComponent(customer)}&status=all&limit=100${cursor ? '&starting_after='+encodeURIComponent(cursor) : ''}`);
    if (!Array.isArray(result.data)) throw billingFailure();
    for (const subscription of result.data) if (!['canceled', 'incomplete_expired'].includes(subscription.status) && belongsToApp(subscription.metadata, env)) {
      if (selected) throw new AuthError(409, 'Multiple active subscriptions were found. Please contact support before changing your plan.', 'BILLING_MULTIPLE_SUBSCRIPTIONS');
      selected = subscription;
    }
    if (!result.has_more) return selected;
    cursor = result.data.at(-1)?.id;
    if (!cursor) break;
  }
  throw billingFailure();
}
async function portalSession(request, env, customer) {
  const origin = returnOrigin(request, env), returnURL = `${origin}/?billing=return#account-billing`;
  const identity = `${env.STRIPE_SECRET_KEY}:${origin}`;
  if (portalConfiguration?.identity !== identity || portalConfiguration.expiresAt < Date.now()) {
    const params = {
      'business_profile[headline]':'SharpEdge billing. Payments are non-refundable.',
      'business_profile[privacy_policy_url]':`${origin}/#privacy`, 'business_profile[terms_of_service_url]':`${origin}/#billing`,
      default_return_url:returnURL, 'features[customer_update][enabled]':'true',
      'features[customer_update][allowed_updates][0]':'name', 'features[customer_update][allowed_updates][1]':'email',
      'features[customer_update][allowed_updates][2]':'address', 'features[customer_update][allowed_updates][3]':'phone',
      'features[payment_method_update][enabled]':'true', 'features[invoice_history][enabled]':'true',
      'features[subscription_cancel][enabled]':'true', 'features[subscription_cancel][mode]':'at_period_end',
      'features[subscription_cancel][proration_behavior]':'none', 'features[subscription_update][enabled]':'false',
      'metadata[application]':'sharpedge', 'metadata[version]':'billing-2'
    };
    const configuration = await stripeRequest(env, 'billing_portal/configurations', params, `sharpedge-portal-${await digestBilling(JSON.stringify(params))}`);
    if (!configuration.id) throw billingFailure();
    portalConfiguration = {identity, id:configuration.id, expiresAt:Date.now() + 3600000};
  }
  const session = await stripeRequest(env, 'billing_portal/sessions', {customer, configuration:portalConfiguration.id, return_url:returnURL});
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
  const customer = await findCustomer(user, env, true);
  const subscription = await activeSubscription(env, customer.id);
  if (subscription) return previewPlanChange(env, user, subscription, plan);
  const origin = returnOrigin(request, env), metadata = scopeMetadata(env, user.uid);
  const params = {mode:'subscription', customer:customer.id, client_reference_id:user.uid,
    'line_items[0][price]':price, 'line_items[0][quantity]':'1',
    success_url:`${origin}/?checkout=success&session_id={CHECKOUT_SESSION_ID}#pricing`, cancel_url:`${origin}/?checkout=cancelled#pricing`,
    ...Object.fromEntries(Object.entries(metadata).flatMap(([key, value]) => [[`metadata[${key}]`, value], [`subscription_data[metadata][${key}]`, value]]))};
  // Repeated clicks/retries share a session without letting the browser set prices.
  const bucket = Math.floor(Date.now() / 1800000);
  const key = await digestBilling(`${customer.id}:${price}:${bucket}`);
  const session = await stripeRequest(env, 'checkout/sessions', params, `sharpedge-checkout-${key}`);
  if (!session.url?.startsWith('https://checkout.stripe.com/')) throw billingFailure();
  return {url:session.url};
}
async function createPortal(request, env, user) {
  billingConfig(env);
  const customer = await findCustomer(user, env);
  if (!customer) throw new AuthError(409, 'Choose a plan to start your membership first.', 'BILLING_CUSTOMER_MISSING');
  return portalSession(request, env, customer.id);
}

const planForPrice = (env, price) => Object.keys(BILLING_PLANS).find(plan => env[BILLING_PLANS[plan]]?.trim() === objectID(price));
const secondsISO = value => Number.isFinite(value) && value > 0 ? new Date(value * 1000).toISOString() : null;
const subscriptionPath = id => `subscriptions/${encodeURIComponent(id)}?expand[]=latest_invoice&expand[]=schedule&expand[]=default_payment_method`;
function subscriptionItem(subscription) {
  const items = subscription.items?.data;
  if (!Array.isArray(items) || items.length !== 1 || !items[0].id || (items[0].quantity ?? 1) !== 1 || !Number.isFinite(items[0].current_period_end)) throw new AuthError(409, 'This subscription needs assistance from support before changing plans.', 'BILLING_UNSUPPORTED_SUBSCRIPTION');
  return items[0];
}
function assertSubscriptionOwner(subscription, user, env) {
  if (!belongsToApp(subscription.metadata, env) || subscription.metadata.uid !== user.uid) throw new AuthError(403, 'This subscription belongs to a different account.', 'BILLING_SUBSCRIPTION_FORBIDDEN');
}
async function priceDetails(env, id) {
  const price = await stripeRequest(env, `prices/${encodeURIComponent(id)}`);
  if (!Number.isSafeInteger(price.unit_amount) || price.unit_amount < 0 || price.recurring?.interval !== 'month' || (price.recurring.interval_count ?? 1) !== 1) throw new AuthError(409, 'This plan is not configured as a fixed monthly membership.', 'BILLING_UNSUPPORTED_PRICE');
  return price;
}
async function signChange(env, payload) {
  const content = encodeJSON(payload);
  const key = await crypto.subtle.importKey('raw', encoder.encode(env.STRIPE_WEBHOOK_SECRET), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
  return `${content}.${base64url(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(content))))}`;
}
async function verifyChange(env, quote, user) {
  try {
    if (typeof quote !== 'string' || quote.length > 6000) throw new Error();
    const [content, signature, extra] = quote.split('.');
    if (!content || !signature || extra) throw new Error();
    const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0));
    const key = await crypto.subtle.importKey('raw', encoder.encode(env.STRIPE_WEBHOOK_SECRET), {name:'HMAC', hash:'SHA-256'}, false, ['verify']);
    if (!await crypto.subtle.verify('HMAC', key, decode(signature), encoder.encode(content))) throw new Error();
    const payload = JSON.parse(new TextDecoder().decode(decode(content)));
    if (payload.uid !== user.uid || !belongsToApp(payload, env) || payload.expiresAt < Date.now() || !Number.isFinite(payload.expiresAt) || env[BILLING_PLANS[payload.plan]]?.trim() !== payload.targetPrice) throw new Error();
    return payload;
  } catch { throw new AuthError(409, 'This plan-change quote expired or is invalid. Choose your plan again.', 'BILLING_QUOTE_INVALID'); }
}
async function upgradePreview(env, subscription, item, targetPrice) {
  return stripeRequest(env, 'invoices/create_preview', {
    subscription:subscription.id, 'subscription_details[items][0][id]':item.id,
    'subscription_details[items][0][price]':targetPrice, 'subscription_details[items][0][quantity]':'1',
    'subscription_details[proration_behavior]':'none', 'subscription_details[billing_cycle_anchor][type]':'now'
  });
}
async function paidCurrentTerm(env, user, subscription) {
  if (subscription.latest_invoice?.status === 'paid') return true;
  // An abandoned upgrade leaves a void invoice as latest_invoice. The original
  // paid membership is still authoritative until its stored expiration.
  if (subscription.latest_invoice?.status !== 'void') return false;
  const membership = await membershipFor(user, env);
  return membership.plan === planForPrice(env, subscription.items?.data?.[0]?.price) && Date.parse(membership.expiresAt) > Date.now();
}
async function previewPlanChange(env, user, selected, plan) {
  const subscription = await stripeRequest(env, subscriptionPath(selected.id));
  assertSubscriptionOwner(subscription, user, env);
  await syncSubscription(env, subscription.id);
  const item = subscriptionItem(subscription), targetPrice = env[BILLING_PLANS[plan]].trim();
  if (objectID(item.price) === targetPrice) {
    await syncSubscription(env, subscription.id);
    return {status:'unchanged', account:publicAccount(user, await membershipFor(user, env))};
  }
  if (subscription.status !== 'active' || !await paidCurrentTerm(env, user, subscription)) throw new AuthError(409, 'Please settle your outstanding invoice in Manage billing before changing plans.', 'BILLING_PAYMENT_REQUIRED');
  if (subscription.pending_update) throw new AuthError(409, 'A plan upgrade is awaiting payment. Complete it in Manage billing before choosing another plan.', 'BILLING_CHANGE_PENDING');
  if (subscription.cancel_at_period_end) throw new AuthError(409, 'Your membership is set to end. Resume renewal in Manage billing before changing plans.', 'BILLING_CANCELLATION_PENDING');
  const [current, target] = await Promise.all([priceDetails(env, objectID(item.price)), priceDetails(env, targetPrice)]);
  if (!target.active || current.currency !== target.currency) throw new AuthError(409, 'These plans cannot be switched with the current billing configuration.', 'BILLING_PRICE_INCOMPATIBLE');
  const kind = target.unit_amount > current.unit_amount ? 'upgrade' : 'downgrade';
  const preview = kind === 'upgrade' ? await upgradePreview(env, subscription, item, targetPrice) : null;
  const amountDue = preview?.amount_due ?? 0;
  if (!Number.isSafeInteger(amountDue) || amountDue < 0) throw billingFailure();
  const payload = {...scopeMetadata(env, user.uid), id:crypto.randomUUID(), subscriptionID:subscription.id, itemID:item.id,
    currentPrice:current.id, targetPrice:target.id, plan, kind, termEnd:item.current_period_end,
    amountDue, currency:target.currency, expiresAt:Date.now() + 10 * 60000};
  return {account:publicAccount(user, await membershipFor(user, env)), change:{quote:await signChange(env, payload), plan, currentPlan:planForPrice(env, current.id), kind,
    monthlyAmount:target.unit_amount, currency:target.currency, amountDue, effectiveAt:kind === 'upgrade' ? null : secondsISO(item.current_period_end)}};
}
async function releaseSchedule(env, subscription) {
  if (!subscription.schedule) return;
  const schedule = typeof subscription.schedule === 'string'
    ? await stripeRequest(env, `subscription_schedules/${encodeURIComponent(subscription.schedule)}`) : subscription.schedule;
  if (objectID(schedule.subscription) !== subscription.id || objectID(schedule.customer) !== objectID(subscription.customer)) throw billingFailure();
  if (['active', 'not_started'].includes(schedule.status)) await stripeRequest(env, `subscription_schedules/${encodeURIComponent(schedule.id)}/release`, {});
}
function upcomingPlan(subscription, env) {
  const schedule = subscription.schedule;
  if (!schedule || typeof schedule !== 'object' || !['active', 'not_started'].includes(schedule.status)) return null;
  const end = subscription.items?.data?.[0]?.current_period_end;
  const phase = schedule.phases?.find(phase => phase.start_date >= end);
  const plan = planForPrice(env, phase?.items?.[0]?.price);
  return plan ? {plan, effectiveAt:secondsISO(phase.start_date)} : null;
}
async function changePlan(env, user, quote) {
  billingConfig(env);
  const change = await verifyChange(env, quote, user);
  let subscription = await stripeRequest(env, subscriptionPath(change.subscriptionID));
  assertSubscriptionOwner(subscription, user, env);
  const item = subscriptionItem(subscription);
  if (objectID(item.price) === change.targetPrice && subscription.latest_invoice?.status === 'paid') {
    await syncSubscription(env, subscription.id);
    return {status:'updated', account:publicAccount(user, await membershipFor(user, env))};
  }
  if (objectID(item.price) !== change.currentPrice || item.current_period_end !== change.termEnd || subscription.status !== 'active' || subscription.cancel_at_period_end) throw new AuthError(409, 'Your subscription changed. Review a new quote before continuing.', 'BILLING_QUOTE_STALE');
  const pending = subscription.pending_update?.subscription_items?.find(row => objectID(row.price) === change.targetPrice);
  if (subscription.pending_update) {
    if (pending && subscription.latest_invoice?.hosted_invoice_url) return {status:'payment_required', paymentUrl:subscription.latest_invoice.hosted_invoice_url};
    throw new AuthError(409, 'Another upgrade is awaiting payment. Open Manage billing to complete it.', 'BILLING_CHANGE_PENDING');
  }
  if (!await paidCurrentTerm(env, user, subscription)) throw new AuthError(409, 'Pay your outstanding invoice before changing plans.', 'BILLING_PAYMENT_REQUIRED');
  if (change.kind === 'upgrade') {
    const preview = await upgradePreview(env, subscription, item, change.targetPrice);
    if (preview.amount_due !== change.amountDue || preview.currency !== change.currency) throw new AuthError(409, 'The amount due changed. Choose the plan again to review the updated total.', 'BILLING_QUOTE_STALE');
    await releaseSchedule(env, subscription);
    subscription = await stripeRequest(env, `subscriptions/${encodeURIComponent(subscription.id)}`, {
      'items[0][id]':item.id, 'items[0][price]':change.targetPrice, 'items[0][quantity]':'1',
      proration_behavior:'none', 'billing_cycle_anchor[type]':'now', payment_behavior:'pending_if_incomplete',
      'expand[0]':'latest_invoice'
    }, `sharpedge-upgrade-${await digestBilling(quote)}`);
    await syncSubscription(env, subscription.id);
    subscription = await stripeRequest(env, subscriptionPath(subscription.id));
    if (subscription.pending_update || subscription.latest_invoice?.status !== 'paid' || objectID(subscription.items?.data?.[0]?.price) !== change.targetPrice) {
      return {status:'payment_required', paymentUrl:subscription.latest_invoice?.hosted_invoice_url || null, account:publicAccount(user, await membershipFor(user, env))};
    }
    return {status:'updated', account:publicAccount(user, await membershipFor(user, env))};
  }
  if (upcomingPlan(subscription, env)?.plan !== change.plan) {
    let schedule = subscription.schedule;
    if (!schedule) schedule = await stripeRequest(env, 'subscription_schedules', {from_subscription:subscription.id}, `sharpedge-schedule-${await digestBilling(quote)}`);
    else if (typeof schedule === 'string') schedule = await stripeRequest(env, `subscription_schedules/${encodeURIComponent(schedule)}`);
    if (objectID(schedule.subscription) !== subscription.id || !schedule.current_phase?.start_date) throw billingFailure();
    await stripeRequest(env, `subscription_schedules/${encodeURIComponent(schedule.id)}`, {
      end_behavior:'release', proration_behavior:'none',
      'phases[0][start_date]':String(schedule.current_phase.start_date), 'phases[0][end_date]':String(change.termEnd),
      'phases[0][items][0][price]':change.currentPrice, 'phases[0][items][0][quantity]':'1', 'phases[0][proration_behavior]':'none',
      'phases[1][start_date]':String(change.termEnd), 'phases[1][duration][interval]':'month', 'phases[1][duration][interval_count]':'1',
      'phases[1][items][0][price]':change.targetPrice, 'phases[1][items][0][quantity]':'1', 'phases[1][proration_behavior]':'none',
      'metadata[uid]':user.uid, 'metadata[project]':env.FIREBASE_PROJECT_ID, 'metadata[database]':env.FIREBASE_DATABASE_ID?.trim() || '(default)'
    }, `sharpedge-downgrade-${await digestBilling(quote)}`);
  }
  await syncSubscription(env, subscription.id);
  return {status:'scheduled', plan:change.plan, effectiveAt:secondsISO(change.termEnd), account:publicAccount(user, await membershipFor(user, env))};
}
async function setCancellation(env, user, cancel) {
  billingConfig(env);
  if (typeof cancel !== 'boolean') throw new AuthError(400, 'Choose whether to cancel or resume your membership.', 'BILLING_INVALID_REQUEST');
  const customer = await findCustomer(user, env);
  const selected = customer && await activeSubscription(env, customer.id);
  if (!selected) throw new AuthError(409, 'There is no renewing Stripe subscription on this account.', 'BILLING_SUBSCRIPTION_MISSING');
  let subscription = await stripeRequest(env, subscriptionPath(selected.id));
  assertSubscriptionOwner(subscription, user, env);
  if (subscription.pending_update) {
    if (!cancel || !subscription.latest_invoice?.id || subscription.latest_invoice.status !== 'open') throw new AuthError(409, 'Your upgrade payment is still being processed. Refresh billing before changing renewal settings.', 'BILLING_CHANGE_PENDING');
    // Cancellation also abandons an unpaid upgrade, without charging it first.
    await stripeRequest(env, `invoices/${encodeURIComponent(subscription.latest_invoice.id)}/void`, {});
    subscription = await stripeRequest(env, subscriptionPath(selected.id));
  }
  if (cancel) await releaseSchedule(env, subscription);
  await stripeRequest(env, `subscriptions/${encodeURIComponent(subscription.id)}`, {cancel_at_period_end:String(cancel), proration_behavior:'none'});
  await syncSubscription(env, subscription.id);
  return {status:cancel ? 'cancelling' : 'renewing', account:publicAccount(user, await membershipFor(user, env))};
}
async function removeScheduledChange(env, user) {
  billingConfig(env);
  const customer = await findCustomer(user, env), selected = customer && await activeSubscription(env, customer.id);
  if (!selected) throw new AuthError(409, 'There is no active subscription to update.', 'BILLING_SUBSCRIPTION_MISSING');
  const subscription = await stripeRequest(env, subscriptionPath(selected.id));
  assertSubscriptionOwner(subscription, user, env);
  await releaseSchedule(env, subscription);
  await syncSubscription(env, subscription.id);
  return {status:'renewing', account:publicAccount(user, await membershipFor(user, env))};
}
async function billingAccount(env, user) {
  billingConfig(env);
  const customer = await findCustomer(user, env), selected = customer && await activeSubscription(env, customer.id);
  let subscription;
  if (selected) {
    assertSubscriptionOwner(selected, user, env);
    await syncSubscription(env, selected.id);
    subscription = await stripeRequest(env, subscriptionPath(selected.id));
  }
  const account = publicAccount(user, await membershipFor(user, env));
  if (!customer) return {account, subscription:null, customer:null, invoices:[]};
  const invoices = await stripeRequest(env, `invoices?customer=${encodeURIComponent(customer.id)}&limit=20`);
  const method = subscription?.default_payment_method || customer.invoice_settings?.default_payment_method;
  const paymentMethod = typeof method === 'string' ? await stripeRequest(env, `payment_methods/${encodeURIComponent(method)}`, undefined, undefined, true) : method;
  const item = subscription?.items?.data?.[0];
  const price = item && await priceDetails(env, objectID(item.price));
  return {account, customer:{name:customer.name || '', email:customer.email || '', address:customer.address || null,
    paymentMethod:paymentMethod?.card ? {brand:paymentMethod.card.brand, last4:paymentMethod.card.last4, expMonth:paymentMethod.card.exp_month, expYear:paymentMethod.card.exp_year} : null},
    subscription:subscription ? {plan:planForPrice(env, item.price), status:subscription.status, monthlyAmount:price.unit_amount, currency:price.currency,
      renewsAt:secondsISO(item.current_period_end), cancelAtPeriodEnd:subscription.cancel_at_period_end === true, scheduledChange:upcomingPlan(subscription, env),
      pendingPayment:subscription.pending_update ? subscription.latest_invoice?.hosted_invoice_url || null : null} : null,
    invoices:(invoices.data || []).map(invoice => ({id:invoice.id, number:invoice.number, createdAt:secondsISO(invoice.created), status:invoice.status,
      total:invoice.total, amountDue:invoice.amount_remaining, currency:invoice.currency, url:invoice.hosted_invoice_url, pdf:invoice.invoice_pdf})), hasMoreInvoices:invoices.has_more === true};
}

// Fetch current Stripe state and use Firestore preconditions so retries and
// out-of-order events cannot roll a newer subscription back to an old snapshot.
async function syncSubscription(env, subscriptionID) {
  let subscription = await stripeRequest(env, subscriptionPath(subscriptionID));
  if (!belongsToApp(subscription.metadata, env)) return;
  const uid = subscription.metadata.uid;
  if (typeof uid !== 'string' || !uid || uid.length > 128 || uid.includes('/')) throw billingFailure();
  for (let attempt = 0; attempt < 3; attempt++) {
    let record = await readBilling(env, uid);
    subscription = await stripeRequest(env, subscriptionPath(subscriptionID));
    if (!belongsToApp(subscription.metadata, env) || subscription.metadata.uid !== uid) throw billingFailure();
    if (objectID(subscription.customer) !== field(record, 'customerId')) {
      const linked = field(record, 'customerId') && await stripeRequest(env, `customers/${encodeURIComponent(field(record, 'customerId'))}`, undefined, undefined, true);
      if (linked && !linked.deleted) return;
      const customer = await stripeRequest(env, `customers/${encodeURIComponent(objectID(subscription.customer))}`);
      if (!customerOwnedBy(customer, {uid}, env)) throw billingFailure();
      await linkCustomer(env, uid, customer.id);
      record = await readBilling(env, uid);
    }
    const previousID = field(record, 'subscriptionId');
    if (previousID && previousID !== subscriptionID) {
      const previous = await stripeRequest(env, `subscriptions/${encodeURIComponent(previousID)}`, undefined, undefined, true);
      // An old cancellation must never revoke a replacement membership.
      if (previous && !['canceled', 'incomplete_expired'].includes(previous.status)) return;
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
    const scheduled = upcomingPlan(subscription, env);
    const writes = [billingWrite(env, uid, record, {subscriptionId:subscriptionID, status:subscription.status,
      cancelAtPeriodEnd:String(subscription.cancel_at_period_end === true), scheduledPlan:scheduled?.plan || '', scheduledAt:scheduled?.effectiveAt || ''}), {
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
  } else if (['customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted', 'customer.subscription.pending_update_applied', 'customer.subscription.pending_update_expired'].includes(event.type)) subscriptionID = object?.id;
  else if (['invoice.paid', 'invoice.payment_failed'].includes(event.type)) subscriptionID = objectID(object?.parent?.subscription_details?.subscription || object?.subscription);
  else if (['subscription_schedule.updated', 'subscription_schedule.released', 'subscription_schedule.completed'].includes(event.type)) subscriptionID = objectID(object?.subscription || object?.released_subscription);
  if (subscriptionID) await syncSubscription(env, subscriptionID);
  return {received:true};
}

export { createCheckout, createPortal, checkoutStatus, stripeWebhook, billingAccount, changePlan, setCancellation, removeScheduledChange };
