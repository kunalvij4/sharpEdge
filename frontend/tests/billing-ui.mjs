import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements = new Map(), notices = [], navigations = [], events = new Map();
const element = key => {
  if (!elements.has(key)) elements.set(key, {innerHTML:'',textContent:'',open:false,close(){this.open=false},showModal(){this.open=true}});
  return elements.get(key);
};
const account = {uid:'alice',plan:'gold',email:'alice@example.test',displayName:'Alice',membershipExpiresAt:'2099-01-01T00:00:00Z'};
const fixture = {account,customer:{name:'Alice <script>bad()</script>',email:'alice@example.test',address:{line1:'123 Test St'},paymentMethod:{brand:'visa',last4:'4242',expMonth:12,expYear:2030}},
  subscription:{plan:'gold',status:'active',currency:'usd',monthlyAmount:1499,renewsAt:'2099-01-01T00:00:00Z',cancelAtPeriodEnd:false,scheduledChange:null},
  invoices:[{id:'in_alice',number:'INV-1',status:'paid',createdAt:'2026-11-09T00:00:00Z',currency:'usd',total:1499,amountDue:0,url:'https://invoice.stripe.com/i/test',pdf:'https://pay.stripe.com/invoice/test/pdf'}]};
const text = value => String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let confirmCalls=0, requestedQuote, cancellation, removed=false;
const context = vm.createContext({URL,Intl,console,Promise,
  window:{addEventListener:(name,handler)=>events.set(name,handler),sharpAuth:{
    getBilling:async()=>structuredClone(fixture),
    changePlan:async quote=>{confirmCalls++;requestedQuote=quote;return {status:'updated'}},
    setCancellation:async cancel=>{cancellation=cancel},removeScheduledChange:async()=>{removed=true},manageBilling:async()=>{}
  }}, currentAccount:account,authLoading:false,billingBusy:false,
  $:element,escapeAccountText:text,render(){},notify:message=>notices.push(message),
  go:path=>navigations.push(path),route:()=> 'account-billing',
  names:{guest:'Guest',gold:'Gold',plus:'Gold Plus',fantasy:'Fantasy Package',fantasyplus:'Fantasy+',platinum:'Platinum'}
});
vm.runInContext(fs.readFileSync(new URL('../web/billing-ui.js',import.meta.url),'utf8'),context);
await vm.runInContext('loadBillingPage()',context);
let html=vm.runInContext('billingPage()',context);
for(const expected of ['Manage billing','Gold','4242','123 Test St','INV-1','Full invoice history','Cancel membership','No-refund policy','non-refundable']) assert.ok(html.includes(expected),expected);
assert.doesNotMatch(html,/<script>bad\(\)<\/script>/,'Billing identity fields are escaped');
assert.match(html,/&lt;script&gt;/);
assert.equal(vm.runInContext("safeBillingURL('javascript:alert(1)')",context),'');
assert.equal(vm.runInContext("safeBillingURL('https://invoice.stripe.com.evil.test/pay')",context),'');
vm.runInContext("billingPageData.subscription.scheduledChange={plan:'fantasy',effectiveAt:'2099-01-01T00:00:00Z'}",context);
html=vm.runInContext('billingPage()',context);
assert.match(html,/Fantasy Package starts/);
assert.match(html,/current plan remains active/);
vm.runInContext('billingPageData.subscription.cancelAtPeriodEnd=true',context);
html=vm.runInContext('billingPage()',context);
assert.match(html,/Resume membership/);
assert.match(html,/Access ends/);

context.quote={quote:'signed-upgrade-quote',kind:'upgrade',currentPlan:'gold',plan:'plus',monthlyAmount:1999,amountDue:1999,currency:'usd'};
vm.runInContext('showPlanChange(quote)',context);
assert.match(element('#modal').innerHTML,/full new monthly price/);
assert.match(element('#modal').innerHTML,/new billing month/);
assert.match(element('#modal').innerHTML,/no credit or refund/);
assert.equal(confirmCalls,0,'Opening a confirmation must not charge the saved card');
context.button={disabled:false};
await vm.runInContext('confirmPlanChange(button)',context);
assert.equal(confirmCalls,1);
assert.equal(requestedQuote,'signed-upgrade-quote');
assert.equal(navigations.at(-1),'account-billing');
assert.equal(context.button.disabled,false);

context.quote={...context.quote,quote:'signed-downgrade-quote',kind:'downgrade',currentPlan:'platinum',plan:'gold',monthlyAmount:1499,amountDue:0,effectiveAt:'2099-01-01T00:00:00Z'};
vm.runInContext('showPlanChange(quote)',context);
assert.match(element('#modal').innerHTML,/Confirm downgrade at renewal/);
assert.match(element('#modal').innerHTML,/current plan stays active/);
context.window.sharpAuth.changePlan=async()=>{throw new Error('This quote expired. Choose your plan again.')};
await vm.runInContext('confirmPlanChange(button)',context);
assert.match(element('#billing-action-error').textContent,/quote expired/);
assert.equal(element('#modal').open,true,'A failed confirmation remains open for the error');
assert.equal(context.button.disabled,false);

await vm.runInContext('loadBillingPage()',context);
vm.runInContext('confirmMembershipCancellation()',context);
assert.match(element('#modal').innerHTML,/access continues until/);
assert.match(element('#modal').innerHTML,/Cancel at end of paid term/);
await vm.runInContext('cancelMembership(button)',context);
assert.equal(cancellation,true);
assert.match(notices.at(-1),/paid access continues/);
await vm.runInContext('resumeMembership(button)',context);
assert.equal(cancellation,false);
await vm.runInContext('undoScheduledChange(button)',context);
assert.equal(removed,true);

let resolve;
context.window.sharpAuth.getBilling=()=>new Promise(done=>{resolve=done});
const oldLoad=vm.runInContext('loadBillingPage()',context);
context.currentAccount={uid:'bob',plan:'guest'};
context.window.resetBillingView();
resolve(structuredClone(fixture));
await oldLoad;
assert.equal(vm.runInContext('billingPageData',context),null,'A late billing response cannot display the previous user invoices');
console.log('Billing UI tests passed: details/invoices, safe links, upgrade consent, scheduled downgrade, cancellation, resumption and account switching.');
