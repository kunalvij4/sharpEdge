import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../web/auth.js', import.meta.url), 'utf8').replace(/\ninitialize\(\);\s*$/, '\n');
const redirects = [], requests = [], writes = [];
const user = {uid:'alice', getIdToken:async () => 'alice-token'};
let response = () => Response.json({url:'https://checkout.stripe.com/c/pay/cs_test_gold'});
const context = vm.createContext({window:{}, URL, URLSearchParams, Headers, AbortSignal, console,
  location:{search:'', assign:url=>redirects.push(url)}, fakeAuth:{currentUser:user}, user,
  fakeSDK:{setDoc:async (...args)=>writes.push(args)},
  fetch:async (path, options) => {requests.push({path, options}); return response();}
});
vm.runInContext(source, context);
vm.runInContext("auth=fakeAuth;sdk=fakeSDK;authState.user=user;authState.account={uid:'alice',plan:'guest'};authState.ready=true", context);
for (const plan of ['gold', 'plus', 'fantasy', 'fantasyplus', 'platinum']) {
  await vm.runInContext(`authState.selectPlan('${plan}')`, context);
  const request = requests.at(-1);
  assert.equal(request.path, '/api/billing/checkout');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers.get('authorization'), 'Bearer alice-token');
  assert.deepEqual(JSON.parse(request.options.body), {plan});
  assert.equal(vm.runInContext('authState.account.plan', context), 'guest');
}
assert.equal(writes.length, 0, 'The browser never writes an entitlement');
assert.equal(redirects.length, 5);
await assert.rejects(vm.runInContext("authState.selectPlan('fantasy_plus')", context));
response = () => Response.json({error:'This plan is not available for payment yet.'}, {status:503});
await assert.rejects(vm.runInContext("authState.selectPlan('gold')", context), /not available for payment/);
for (const url of ['https://evil.test/pay', 'javascript:alert(1)', 'https://checkout.stripe.com.evil.test/pay', 'http://checkout.stripe.com/pay']) {
  response = () => Response.json({url});
  await assert.rejects(vm.runInContext("authState.selectPlan('gold')", context), /could not be opened/);
}
assert.equal(redirects.length, 5, 'Untrusted redirect URLs are rejected');
response = () => Response.json({url:'https://billing.stripe.com/p/session/manage'});
await vm.runInContext('authState.manageBilling()', context);
assert.equal(requests.at(-1).path, '/api/billing/portal');
assert.equal(redirects.at(-1), 'https://billing.stripe.com/p/session/manage');

vm.runInContext("location.search='?next='+encodeURIComponent('/?plan=plus#pricing')", context);
assert.equal(vm.runInContext("safeNext({plan:'guest'},true)", context), '/?plan=plus#pricing', 'A chosen plan survives first-time Google sign-in');
vm.runInContext("location.search='?next='+encodeURIComponent('/?plan=fantasyplus#pricing')", context);
assert.equal(vm.runInContext("safeNext({plan:'guest'},true)", context), '/?plan=fantasyplus#pricing', 'Fantasy+ survives first-time Google sign-in');
vm.runInContext("location.search='?next='+encodeURIComponent('https://evil.test/?plan=plus#pricing')", context);
assert.equal(vm.runInContext("safeNext({plan:'guest'},true)", context), '/#pricing');
vm.runInContext("location.search='?next='+encodeURIComponent('/#account-billing')",context);
assert.equal(vm.runInContext("safeNext({plan:'guest'},true)",context),'/#account-billing','Billing remains reachable when the browser has a stale Guest plan');

response=()=>Response.json({change:{quote:'signed',plan:'plus',kind:'upgrade'},account:{uid:'alice',plan:'gold'}});
const review=await vm.runInContext("authState.selectPlan('plus')",context);
assert.equal(review.change.quote,'signed');
assert.equal(vm.runInContext('authState.account.plan',context),'gold','Plan review refreshes a stale browser membership');
response=()=>Response.json({account:{uid:'alice',plan:'gold'},invoices:[{id:'in_alice'}]});
assert.equal((await vm.runInContext('authState.getBilling()',context)).invoices[0].id,'in_alice');
response=()=>Response.json({status:'scheduled',account:{uid:'alice',plan:'gold'}});
await vm.runInContext("authState.changePlan('signed')",context);
assert.equal(requests.at(-1).path,'/api/billing/change');
assert.deepEqual(JSON.parse(requests.at(-1).options.body),{quote:'signed'});
await vm.runInContext('authState.setCancellation(true)',context);
assert.deepEqual(JSON.parse(requests.at(-1).options.body),{cancel:true});
await vm.runInContext('authState.removeScheduledChange()',context);
assert.equal(requests.at(-1).options.method,'DELETE');

response = () => Response.json({status:'paid', account:{uid:'alice', plan:'gold', membershipExpiresAt:'2099-01-01T00:00:00Z'}});
await vm.runInContext("authState.confirmCheckout('cs_test_paid')", context);
assert.equal(requests.at(-1).path, '/api/billing/checkout?session_id=cs_test_paid');
assert.equal(vm.runInContext('authState.account.plan', context), 'gold');
response = () => Response.json({status:'paid', account:{uid:'bob', plan:'platinum'}});
await assert.rejects(vm.runInContext("authState.confirmCheckout('cs_test_bob')", context), /could not be verified/);
assert.equal(vm.runInContext('authState.account.plan', context), 'gold');

let release;
response = () => new Promise(resolve => {release = resolve});
const pending = vm.runInContext("authState.selectPlan('plus')", context);
while (!release) await Promise.resolve();
const before = redirects.length;
vm.runInContext("revision++;authState.account={uid:'bob',plan:'guest'}", context);
release(Response.json({url:'https://checkout.stripe.com/c/pay/cs_test_alice'}));
await assert.rejects(pending, /account changed/);
assert.equal(redirects.length, before, 'Account switching prevents a stale payment redirect');

let finishCheckout, checkoutCalls = 0, renders = 0;
const notices = [];
const ui = vm.createContext({
  window:{sharpAuth:{selectPlan:async () => {checkoutCalls++; await new Promise(resolve=>{finishCheckout=resolve})}}, addEventListener(){}},
  location:{href:'', search:'', pathname:'/', hash:'#pricing'}, URLSearchParams, console,
  currentAccount:{uid:'alice', plan:'guest'}, authLoading:false, render:()=>renders++, notify:message=>notices.push(message),
  names:{gold:'Gold', plus:'Gold Plus', fantasy:'Fantasy Package', fantasyplus:'Fantasy+', platinum:'Platinum'}
});
vm.runInContext(fs.readFileSync(new URL('../web/account-ui.js', import.meta.url), 'utf8'), ui);
const firstClick = vm.runInContext("requestMembership('gold')", ui);
assert.equal(vm.runInContext('billingBusy', ui), true);
await vm.runInContext("requestMembership('plus')", ui);
assert.equal(checkoutCalls, 1, 'Repeated clicks are disabled while opening Checkout');
finishCheckout(); await firstClick;
assert.equal(vm.runInContext('billingBusy', ui), false);
vm.runInContext("window.sharpAuth.selectPlan=async()=>{throw new Error('Payments are temporarily unavailable.')}", ui);
await vm.runInContext("requestMembership('gold')", ui);
assert.equal(vm.runInContext('billingError', ui), 'Payments are temporarily unavailable.');
assert.equal(vm.runInContext('billingBusy', ui), false, 'Errors allow the user to retry');
vm.runInContext('currentAccount=null', ui);
await vm.runInContext("requestMembership('fantasyplus')", ui);
assert.equal(ui.location.href, '/signin?next=' + encodeURIComponent('/?plan=fantasyplus#pricing'));
vm.runInContext("currentAccount={uid:'alice',plan:'guest'};location.search='?checkout=cancelled'", ui);
await vm.runInContext('handleBillingReturn()', ui);
assert.match(vm.runInContext('billingNotice', ui), /cancelled/);
assert.equal(ui.currentAccount.plan, 'guest', 'A cancelled checkout never grants access');
const resumed = [];
ui.window.sharpAuth.selectPlan = async plan => resumed.push(plan);
vm.runInContext("billingReturnHandled=false;location.search='?plan=fantasyplus'", ui);
await vm.runInContext('handleBillingReturn()', ui);
assert.deepEqual(resumed, ['fantasyplus'], 'A Fantasy+ selection continues to Checkout after sign-in');
assert.ok(renders > 0);
console.log('Billing client tests passed: plan redirects, safe URLs, sign-in continuation, account switching, loading, retry and cancellation.');
