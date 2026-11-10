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
let documents, calls, subscriptions, sessions, customers, schedules, invoices, revision, failStripe, conflicts, failUpgrade, upgradeCharges;
const priceAmounts = {price_gold:1499, price_plus:1999, price_fantasy:2999, price_fantasy_plus:4999, price_platinum:9999};
function reset() {
  documents = new Map([['users/alice', {name:`${root}/users/alice`, updateTime:'version-0', fields:{plan:{stringValue:'guest'}, expiresAt:{nullValue:null},
    bankroll:{integerValue:'2500'}, betHistory:{arrayValue:{values:[{stringValue:'journal-to-preserve'}]}}, signupDate:{timestampValue:'2026-01-01T00:00:00Z'}}}]]);
  calls = []; subscriptions = new Map(); sessions = new Map(); revision = 0; failStripe = false; conflicts = 0;
  customers = new Map(); schedules = new Map(); invoices = []; failUpgrade = false; upgradeCharges = 0;
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
    if (path === 'customers/search') return Response.json({data:[...customers.values()], has_more:false});
    if (path === 'customers') {
      const customer = {id:'cus_alice',metadata:scope,email:'alice@example.test',name:'Alice',address:{line1:'123 Test St',city:'Test City'}, invoice_settings:{default_payment_method:{card:{brand:'visa',last4:'4242',exp_month:12,exp_year:2030}}}};
      customers.set(customer.id,customer);
      return Response.json(customer);
    }
    if (path.startsWith('customers/')) {
      const customer = customers.get(path.slice('customers/'.length));
      return customer ? Response.json(customer) : Response.json({}, {status:404});
    }
    if (path.startsWith('prices/')) {
      const id = path.slice('prices/'.length);
      return Response.json({id, active:true, currency:'usd',unit_amount:priceAmounts[id],recurring:{interval:'month',interval_count:1},product:'prod_'+id});
    }
    if (path === 'invoices/create_preview') return Response.json({amount_due:priceAmounts[params.get('subscription_details[items][0][price]')],currency:'usd'});
    if (path === 'invoices') return Response.json({data:invoices.filter(invoice=>invoice.customer===url.searchParams.get('customer')),has_more:false});
    if (/^invoices\/[^/]+\/void$/.test(path)) {
      const subscription=[...subscriptions.values()].find(row=>row.latest_invoice?.id===path.split('/')[1]);
      subscription.pending_update=null; subscription.latest_invoice.status='void';
      return Response.json(subscription.latest_invoice);
    }
    if (path === 'subscriptions') return Response.json({data:[...subscriptions.values()].filter(subscription=>subscription.customer===url.searchParams.get('customer')), has_more:false});
    if (path.startsWith('subscriptions/')) {
      const sub = subscriptions.get(path.slice('subscriptions/'.length));
      if (sub && options.method === 'POST') {
        if (params.has('cancel_at_period_end')) sub.cancel_at_period_end = params.get('cancel_at_period_end') === 'true';
        if (params.has('items[0][price]')) {
          upgradeCharges++;
          const price = params.get('items[0][price]');
          if (failUpgrade) {
            sub.pending_update={subscription_items:[{price}]};
            sub.latest_invoice={id:'in_upgrade',status:'open',hosted_invoice_url:'https://invoice.stripe.com/i/upgrade'};
          } else {
            sub.items.data[0].price={id:price};
            sub.items.data[0].current_period_end=future+86400;
            sub.latest_invoice={id:'in_upgrade',status:'paid'};
            sub.pending_update=null;
          }
        }
      }
      return sub ? Response.json(sub) : Response.json({}, {status:404});
    }
    if (path === 'subscription_schedules') {
      const subscription=subscriptions.get(params.get('from_subscription'));
      const schedule={id:'sub_sched_'+schedules.size,customer:subscription.customer,subscription:subscription.id,status:'active',current_phase:{start_date:subscription.items.data[0].current_period_start,end_date:subscription.items.data[0].current_period_end},phases:[]};
      schedules.set(schedule.id,schedule); subscription.schedule=schedule;
      return Response.json(schedule);
    }
    if (path.startsWith('subscription_schedules/')) {
      const [,id,action]=path.split('/'),schedule=schedules.get(id);
      if (!schedule) return Response.json({}, {status:404});
      if (action==='release') { schedule.status='released';subscriptions.get(schedule.subscription).schedule=null; }
      else if (options.method==='POST') {
        schedule.phases=[0,1].map(index=>({start_date:Number(params.get(`phases[${index}][start_date]`)),end_date:Number(params.get(`phases[${index}][end_date]`))||undefined,items:[{price:params.get(`phases[${index}][items][0][price]`),quantity:1}]}));
      }
      return Response.json(schedule);
    }
    if (path === 'checkout/sessions') return Response.json({id:'cs_test_created', url:'https://checkout.stripe.com/c/pay/cs_test_created'});
    if (path.startsWith('checkout/sessions/')) return Response.json(sessions.get(path.slice('checkout/sessions/'.length)));
    if (path === 'billing_portal/sessions') return Response.json({url:'https://billing.stripe.com/p/session/test'});
    if (path === 'billing_portal/configurations') return Response.json({id:'bpc_explicit',active:true});
  }
  throw new Error('Unexpected network request: '+url.origin+url.pathname);
};
const request = (path, options = {}, config = env) => worker.fetch(new Request(origin + path, options), config);
const signed = (path, options = {}, config) => request(path, {...options, headers:{authorization:`Bearer ${token}`, origin, ...options.headers}}, config);
const choose = (plan = 'gold', config) => signed('/api/billing/checkout', {method:'POST', body:JSON.stringify({plan, price:'price_attacker', uid:'bob', success_url:'https://evil.test'})}, config);
const currentSubscription = (patch = {}) => ({id:'sub_alice', customer:'cus_alice', metadata:scope, status:'active',
  cancel_at_period_end:false,collection_method:'charge_automatically',latest_invoice:{id:'in_paid', status:'paid'}, items:{data:[{id:'si_alice', quantity:1,price:{id:'price_gold'}, current_period_start:future-30*86400,current_period_end:future}]}, ...patch});
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
assert.ok(calls.some(call=>call.path==='invoices/create_preview'), 'Existing subscribers get an exact upgrade quote');
const fantasyQuote = await (await choose('fantasyplus')).json();
assert.equal(fantasyQuote.change.plan, 'fantasyplus');
assert.equal(fantasyQuote.change.amountDue,4999);
assert.equal((await signed('/api/billing/portal', {method:'POST'})).status, 200);
const portal = calls.find(call=>call.path==='billing_portal/sessions');
assert.equal(portal.params.get('configuration'),'bpc_explicit');
const configuration = calls.find(call=>call.path==='billing_portal/configurations');
assert.equal(configuration.params.get('features[subscription_cancel][mode]'),'at_period_end');
assert.equal(configuration.params.get('features[invoice_history][enabled]'),'true');
assert.equal(configuration.params.get('features[customer_update][enabled]'),'true');
assert.equal(configuration.params.get('features[payment_method_update][enabled]'),'true');
assert.match(configuration.params.get('business_profile[headline]'),/non-refundable/);

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

const confirm = quote => signed('/api/billing/change',{method:'POST',body:JSON.stringify({quote})});
const accountBilling = () => signed('/api/billing/account');
const cancel = value => signed('/api/billing/cancel',{method:'POST',body:JSON.stringify({cancel:value})});
for (const path of ['/api/billing/account','/api/billing/change','/api/billing/cancel','/api/billing/schedule']) {
  const method=path.endsWith('/account')?'GET':path.endsWith('/schedule')?'DELETE':'POST';
  assert.equal((await request(path,{method,headers:{origin},...(method==='POST'?{body:'{}'}:{})})).status,401);
  if (method!=='GET') assert.equal((await signed(path,{method,headers:{origin:'https://evil.test'},...(method==='POST'?{body:'{}'}:{})})).status,403);
}

reset();await prepareCustomer();subscriptions.set('sub_alice',currentSubscription());
const upgradedQuote=await (await choose('platinum')).json();
assert.equal(upgradedQuote.change.kind,'upgrade');
assert.equal(upgradedQuote.change.amountDue,9999,'Upgrade quotes charge a full new month');
assert.equal(upgradeCharges,0,'Choosing a plan only previews a charge');
const upgraded=await confirm(upgradedQuote.change.quote);
assert.equal(upgraded.status,200);
assert.equal((await upgraded.json()).status,'updated');
const upgradeCall=calls.find(call=>call.path==='subscriptions/sub_alice' && call.params.has('items[0][price]'));
assert.equal(upgradeCall.params.get('billing_cycle_anchor[type]'),'now','An upgrade starts a new billing month');
assert.equal(upgradeCall.params.get('proration_behavior'),'none','Upgrades do not credit unused old-plan time');
assert.equal(upgradeCall.params.get('payment_behavior'),'pending_if_incomplete','Unpaid upgrades cannot change the plan');
assert.equal(getField('users/alice','plan').stringValue,'platinum');
assert.equal(getField('users/alice','expiresAt').timestampValue,new Date((future+86400)*1000).toISOString());
await confirm(upgradedQuote.change.quote);
assert.equal(upgradeCharges,1,'A retried confirmation never charges twice');

reset();await prepareCustomer();subscriptions.set('sub_alice',currentSubscription());
const failedQuote=(await (await choose('plus')).json()).change.quote;
failUpgrade=true;
const declined=await (await confirm(failedQuote)).json();
assert.equal(declined.status,'payment_required');
assert.equal(declined.paymentUrl,'https://invoice.stripe.com/i/upgrade');
assert.equal(getField('users/alice','plan').stringValue,'gold');
assert.equal(getField('users/alice','expiresAt').timestampValue,expiry,'Card failures preserve the old paid term');
await confirm(failedQuote);
assert.equal(upgradeCharges,1,'Repeated confirmation of a pending invoice reuses the invoice');
assert.equal((await cancel(true)).status,200,'An unpaid upgrade can be abandoned when cancelling renewal');
assert.equal(subscriptions.get('sub_alice').pending_update,null);
assert.equal(subscriptions.get('sub_alice').cancel_at_period_end,true);
assert.equal(getField('users/alice','plan').stringValue,'gold');
assert.equal(getField('users/alice','expiresAt').timestampValue,expiry);

reset();await prepareCustomer();
const premium=currentSubscription();premium.items.data[0].price={id:'price_platinum'};
subscriptions.set('sub_alice',premium);
const downgrade=await (await choose('gold')).json();
assert.equal(downgrade.change.kind,'downgrade');
assert.equal(downgrade.change.amountDue,0);
assert.equal((await (await confirm(downgrade.change.quote)).json()).status,'scheduled');
assert.equal(subscriptions.get('sub_alice').items.data[0].price.id,'price_platinum','A downgrade preserves the current Stripe plan');
assert.equal(getField('users/alice','plan').stringValue,'platinum','The user keeps paid premium access until renewal');
assert.equal(getField('billingAccounts/alice','scheduledPlan').stringValue,'gold');
assert.equal(getField('billingAccounts/alice','scheduledAt').stringValue,expiry);
const scheduleCall=calls.find(call=>call.path.startsWith('subscription_schedules/') && call.params.has('phases[1][items][0][price]'));
assert.equal(scheduleCall.params.get('phases[0][items][0][price]'),'price_platinum');
assert.equal(scheduleCall.params.get('phases[1][items][0][price]'),'price_gold');
assert.equal(Number(scheduleCall.params.get('phases[1][start_date]')),future);
assert.equal(scheduleCall.params.get('phases[1][proration_behavior]'),'none');
assert.equal(upgradeCharges,0);
let details=await (await accountBilling()).json();
assert.equal(details.subscription.scheduledChange.plan,'gold');
assert.equal(details.subscription.monthlyAmount,9999);
assert.equal((await signed('/api/billing/schedule',{method:'DELETE'})).status,200);
assert.equal(getField('billingAccounts/alice','scheduledPlan').stringValue,'');
assert.equal(subscriptions.get('sub_alice').schedule,null);
const newDowngrade=(await (await choose('plus')).json()).change.quote;
await confirm(newDowngrade);
assert.equal((await cancel(true)).status,200);
assert.equal(subscriptions.get('sub_alice').schedule,null,'Cancellation removes any upcoming downgrade');
assert.equal(subscriptions.get('sub_alice').cancel_at_period_end,true);
assert.equal(getField('users/alice','plan').stringValue,'platinum');
assert.equal(getField('users/alice','expiresAt').timestampValue,expiry);
assert.equal(getField('billingAccounts/alice','cancelAtPeriodEnd').stringValue,'true');
assert.equal(calls.some(call=>/refund/.test(call.path)),false,'No operation creates a refund');
assert.equal((await cancel(false)).status,200);
assert.equal(subscriptions.get('sub_alice').cancel_at_period_end,false);

reset();await prepareCustomer();
const renewing=currentSubscription();renewing.items.data[0].price={id:'price_platinum'};
subscriptions.set('sub_alice',renewing);
await confirm((await (await choose('gold')).json()).change.quote);
renewing.items.data[0].price={id:'price_gold'};
renewing.items.data[0].current_period_start=future;
renewing.items.data[0].current_period_end=future+30*86400;
renewing.latest_invoice={id:'in_renewal',status:'open'};
renewing.status='past_due';
documents.get('users/alice').fields.expiresAt={timestampValue:'2020-01-01T00:00:00Z'};
await webhook('invoice.payment_failed',{subscription:'sub_alice'});
assert.equal(getField('users/alice','plan').stringValue,'guest','An unpaid downgrade renewal cannot extend access');
renewing.latest_invoice.status='paid';renewing.status='active';
await webhook('invoice.paid',{subscription:'sub_alice'});
assert.equal(getField('users/alice','plan').stringValue,'gold','The lower plan activates after its renewal is paid');
assert.equal(getField('users/alice','expiresAt').timestampValue,new Date((future+30*86400)*1000).toISOString());
assert.equal(getField('billingAccounts/alice','scheduledPlan').stringValue,'');

reset();await prepareCustomer();subscriptions.set('sub_alice',currentSubscription());
const secureQuote=(await (await choose('plus')).json()).change.quote;
const [quoteBody,quoteSignature]=secureQuote.split('.');
assert.equal((await confirm(quoteBody+'.'+quoteSignature.slice(0,-2)+'zz')).status,409);
const makeQuote=payload=>{const body=Buffer.from(JSON.stringify(payload)).toString('base64url');return body+'.'+createHmac('sha256',env.STRIPE_WEBHOOK_SECRET).update(body).digest('base64url')};
const payload=JSON.parse(Buffer.from(quoteBody,'base64url'));
assert.equal((await confirm(makeQuote({...payload,uid:'bob'}))).status,409);
assert.equal((await confirm(makeQuote({...payload,expiresAt:1}))).status,409);
assert.equal(upgradeCharges,0);
subscriptions.get('sub_alice').items.data[0].current_period_end++;
assert.equal((await confirm(secureQuote)).status,409,'A changed billing period requires a fresh quote');

reset();await prepareCustomer();subscriptions.set('sub_alice',currentSubscription());
documents.delete('billingAccounts/alice');
invoices=[{id:'in_alice',number:'INV-1',customer:'cus_alice',created:future-86400,total:1499,amount_remaining:0,currency:'usd',status:'paid',hosted_invoice_url:'https://invoice.stripe.com/i/one',invoice_pdf:'https://pay.stripe.com/invoice/one/pdf'},
  {id:'in_bob',customer:'cus_bob',total:9999,status:'paid'}];
details=await (await accountBilling()).json();
assert.equal(details.account.plan,'gold','Stripe recovers a paid membership when its Firestore billing link is missing');
assert.equal(getField('billingAccounts/alice','customerId').stringValue,'cus_alice');
assert.equal(details.customer.paymentMethod.last4,'4242');
assert.equal(details.customer.address.line1,'123 Test St');
assert.deepEqual(details.invoices.map(invoice=>invoice.id),['in_alice'],'Billing never returns another customer invoice');
assert.equal((await signed('/api/billing/portal',{method:'POST'})).status,200);
documents.delete('billingAccounts/alice');
assert.equal((await webhook('customer.subscription.updated',{id:'sub_alice'})).status,200,'Signed webhooks can recover missing billing links too');
assert.equal(getField('users/alice','plan').stringValue,'gold');

documents.get('billingAccounts/alice').fields.subscriptionId={stringValue:'sub_missing'};
assert.equal((await (await accountBilling()).json()).account.plan,'gold','A stale stored subscription ID is reconciled to the real active subscription');
assert.equal(getField('billingAccounts/alice','subscriptionId').stringValue,'sub_alice');
documents.get('billingAccounts/alice').fields.customerId={stringValue:'cus_missing'};
assert.equal((await (await accountBilling()).json()).account.plan,'gold','A missing Stripe customer ID is recovered without creating another customer');
assert.equal(getField('billingAccounts/alice','customerId').stringValue,'cus_alice');
assert.equal(calls.filter(call=>call.path==='customers').length,0,'Recovery reuses the existing customer');

reset();
documents.get('users/alice').fields.plan={stringValue:'gold'};
documents.get('users/alice').fields.expiresAt={timestampValue:expiry};
details=await (await accountBilling()).json();
assert.equal(details.account.plan,'gold','An administratively managed plan is still recognized without a Stripe customer');
assert.equal(details.customer,null);
customers.set('cus_other',{id:'cus_other',email:'alice@example.test',metadata:{...scope,uid:'bob'}});
details=await (await accountBilling()).json();
assert.equal(details.customer,null,'Matching email cannot claim another user billing account');
assert.equal(documents.has('billingAccounts/alice'),false);
console.log('Billing tests passed: authenticated plan checkout, server prices, customer reuse, portal changes, signed webhooks, renewals, cancellation, retries and verified returns.');
