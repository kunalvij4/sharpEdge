// Explicit integration check. Uses disposable Stripe TEST objects and an
// in-memory Firestore; it never writes to the application's real database.
import assert from 'node:assert/strict';
import {generateKeyPairSync, randomUUID} from 'node:crypto';
import {createCheckout, changePlan, billingAccount, setCancellation, createPortal} from '../worker/billing.js';

if (!/^(sk|rk)_test_/.test(process.env.STRIPE_SECRET_KEY || '')) throw new Error('This check requires a Stripe test-mode secret key. Live keys are refused.');
const key = generateKeyPairSync('rsa', {modulusLength:2048}).privateKey.export({type:'pkcs8', format:'pem'});
const env = {...process.env, APP_URL:'https://sharpedge-billing-qa.example', FIREBASE_PROJECT_ID:'sharpedge-billing-qa', FIREBASE_DATABASE_ID:'billing-qa',
  FIREBASE_CLIENT_EMAIL:'qa@sharpedge-billing-qa.iam.gserviceaccount.com', FIREBASE_PRIVATE_KEY:key, STRIPE_WEBHOOK_SECRET:'qa_quote_secret'};
const uid = 'billing-qa-'+randomUUID(), user = {uid, email:'billing-qa@example.invalid', token:'qa-token'};
env.APP_URL=`https://${uid}.billing-qa.example`;
const root = `projects/${env.FIREBASE_PROJECT_ID}/databases/${env.FIREBASE_DATABASE_ID}/documents`;
const docs = new Map([[`users/${uid}`, {name:`${root}/users/${uid}`,updateTime:'v0',fields:{plan:{stringValue:'guest'},expiresAt:{nullValue:null},bankroll:{integerValue:'1000'}}}]]);
const actualFetch = globalThis.fetch;
let version = 0, customerID, subscriptionID;
const configurations = [];
async function stripe(path, params, method = params ? 'POST' : 'GET') {
  const response = await actualFetch('https://api.stripe.com/v1/'+path, {method,headers:{authorization:`Bearer ${env.STRIPE_SECRET_KEY}`,'Stripe-Version':'2026-10-28.endive','content-type':'application/x-www-form-urlencoded'},
    ...(params ? {body:new URLSearchParams(params)} : {}),signal:AbortSignal.timeout(20000)});
  const result = await response.json();
  if (!response.ok) throw new Error(`Stripe sandbox ${response.status}: ${result.error?.code || result.error?.type} ${result.error?.param || ''} ${result.error?.message || ''}`);
  return result;
}
globalThis.fetch = async (input, options = {}) => {
  const url = new URL(input);
  if (url.hostname === 'oauth2.googleapis.com') return Response.json({access_token:'qa-access',expires_in:3600});
  if (url.hostname === 'firestore.googleapis.com') {
    const path = decodeURIComponent(url.pathname).split('/documents')[1];
    if (path !== ':commit') return docs.has(path.slice(1)) ? Response.json(docs.get(path.slice(1))) : Response.json({}, {status:404});
    const {writes} = JSON.parse(options.body);
    for (const write of writes) {
      const old = docs.get(write.update.name.slice(root.length+1));
      if ((write.currentDocument?.exists === false && old) || (write.currentDocument?.updateTime && old?.updateTime !== write.currentDocument.updateTime)) return Response.json({}, {status:409});
    }
    for (const write of writes) {
      const name = write.update.name.slice(root.length+1), old = docs.get(name);
      docs.set(name, {name:write.update.name,updateTime:'v'+(++version),fields:{...old?.fields,...write.update.fields}});
    }
    return Response.json({writeResults:[]});
  }
  if (url.hostname !== 'api.stripe.com') throw new Error('Unexpected sandbox request');
  const response = await actualFetch(input, options);
  if (!response.ok) {
    const detail = await response.clone().json().catch(()=>({}));
    console.error('Sandbox Stripe error', {status:response.status,code:detail.error?.code,type:detail.error?.type,param:detail.error?.param,message:detail.error?.message});
  }
  if (url.pathname === '/v1/billing_portal/configurations' && options.method === 'POST' && response.ok) configurations.push((await response.clone().json()).id);
  return response;
};
try {
  for (const name of ['STRIPE_PRICE_GOLD','STRIPE_PRICE_PLUS']) {
    const price = await stripe('prices/'+encodeURIComponent(env[name] || ''));
    assert.equal(price.livemode,false,'Live prices are refused');
    assert.equal(price.recurring.interval,'month');
  }
  const metadata = {'metadata[uid]':uid,'metadata[project]':env.FIREBASE_PROJECT_ID,'metadata[database]':env.FIREBASE_DATABASE_ID};
  const customer = await stripe('customers',{name:'SharpEdge disposable billing QA',email:user.email,payment_method:'pm_card_visa','invoice_settings[default_payment_method]':'pm_card_visa',...metadata});
  assert.equal(customer.livemode,false); customerID = customer.id;
  docs.set(`billingAccounts/${uid}`,{name:`${root}/billingAccounts/${uid}`,updateTime:'v'+(++version),fields:{customerId:{stringValue:customer.id}}});
  let subscription = await stripe('subscriptions',{customer:customer.id,'items[0][price]':env.STRIPE_PRICE_GOLD,payment_behavior:'error_if_incomplete','expand[0]':'latest_invoice',...metadata});
  subscriptionID = subscription.id;
  assert.equal(subscription.latest_invoice.status,'paid');
  const request = new Request(env.APP_URL+'/api/billing/checkout');
  const preview = await createCheckout(request, env, user, 'plus');
  const plus = await stripe('prices/'+env.STRIPE_PRICE_PLUS);
  assert.equal(preview.change.amountDue,plus.unit_amount);
  assert.equal((await changePlan(env,user,preview.change.quote)).status,'updated');
  subscription = await stripe('subscriptions/'+subscription.id+'?expand[]=latest_invoice');
  assert.equal(subscription.items.data[0].price.id,env.STRIPE_PRICE_PLUS);
  assert.equal(subscription.latest_invoice.amount_paid,plus.unit_amount,'The full new monthly price is collected');
  assert.equal(docs.get(`users/${uid}`).fields.plan.stringValue,'plus');
  const paidInvoice = subscription.latest_invoice.id;
  await changePlan(env,user,preview.change.quote);
  assert.equal((await stripe('subscriptions/'+subscription.id)).latest_invoice,paidInvoice,'Retries do not create another invoice');
  console.log('Stripe sandbox: full-price immediate upgrade and retry verified.');

  const downgrade = await createCheckout(request,env,user,'gold');
  assert.equal(downgrade.change.amountDue,0);
  assert.equal((await changePlan(env,user,downgrade.change.quote)).status,'scheduled');
  subscription = await stripe('subscriptions/'+subscription.id+'?expand[]=schedule');
  assert.equal(subscription.items.data[0].price.id,env.STRIPE_PRICE_PLUS);
  assert.equal(subscription.schedule.phases[1].items[0].price,env.STRIPE_PRICE_GOLD);
  assert.equal(subscription.schedule.phases[1].start_date,subscription.items.data[0].current_period_end);
  assert.equal(docs.get(`users/${uid}`).fields.plan.stringValue,'plus');
  console.log('Stripe sandbox: downgrade starts at renewal and preserves paid premium access.');

  const details = await billingAccount(env,user);
  assert.ok(details.invoices.length>=2);
  assert.equal(details.customer.paymentMethod.last4,'4242');
  assert.ok((await createPortal(request,env,user)).url.startsWith('https://billing.stripe.com/'));
  await setCancellation(env,user,true);
  subscription=await stripe('subscriptions/'+subscription.id);
  assert.equal(subscription.cancel_at_period_end,true);
  assert.equal(subscription.schedule,null);
  assert.equal(docs.get(`users/${uid}`).fields.plan.stringValue,'plus');
  await setCancellation(env,user,false);
  assert.equal((await stripe('subscriptions/'+subscription.id)).cancel_at_period_end,false);
  console.log('Stripe sandbox: billing details, invoices, portal configuration, term-end cancellation and resumption verified.');

  const declinedCard=await stripe('payment_methods/pm_card_chargeCustomerFail/attach',{customer:customer.id});
  await stripe('customers/'+customer.id,{'invoice_settings[default_payment_method]':declinedCard.id});
  const oldExpiry=docs.get(`users/${uid}`).fields.expiresAt.timestampValue;
  const failedPreview=await createCheckout(request,env,user,'platinum');
  const failed=await changePlan(env,user,failedPreview.change.quote);
  assert.equal(failed.status,'payment_required');
  assert.equal(docs.get(`users/${uid}`).fields.plan.stringValue,'plus');
  assert.equal(docs.get(`users/${uid}`).fields.expiresAt.timestampValue,oldExpiry);
  await setCancellation(env,user,true);
  subscription=await stripe('subscriptions/'+subscription.id);
  assert.equal(subscription.pending_update,null);
  assert.equal(subscription.cancel_at_period_end,true);
  assert.equal(docs.get(`users/${uid}`).fields.expiresAt.timestampValue,oldExpiry);
  await setCancellation(env,user,false);
  assert.equal((await createCheckout(request,env,user,'gold')).change.kind,'downgrade','A void upgrade invoice does not block future plan changes');
  console.log('Stripe sandbox: a real test-card decline preserves the old paid plan; cancellation voids the unpaid upgrade.');
} finally {
  globalThis.fetch=actualFetch;
  if (subscriptionID) await stripe('subscriptions/'+subscriptionID,undefined,'DELETE');
  if (customerID) await stripe('customers/'+customerID,undefined,'DELETE');
  for (const id of configurations) await stripe('billing_portal/configurations/'+id,{active:'false'});
  console.log('Disposable Stripe sandbox customer and subscription cleaned up. Real Firestore was not modified.');
}
