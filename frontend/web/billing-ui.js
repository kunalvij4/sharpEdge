let billingPageData = null;
let billingPageLoading = false;
let billingPageError = '';
let pendingPlanChange = null;
const billingMoney = (cents, currency = 'usd') => Number.isFinite(cents)
  ? new Intl.NumberFormat(undefined, {style:'currency', currency:currency.toUpperCase()}).format(cents / 100) : '—';
const billingDate = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'}) : 'Not available';
function safeBillingURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && ['invoice.stripe.com', 'pay.stripe.com', 'billing.stripe.com'].includes(url.hostname) ? url.href : '';
  } catch { return ''; }
}
window.resetBillingView = () => { billingPageData = null; billingPageLoading = false; billingPageError = ''; pendingPlanChange = null; };
function billingPage() {
  if (!billingPageData && !billingPageLoading && !billingPageError && currentAccount) {
    billingPageLoading = true;
    Promise.resolve().then(() => loadBillingPage());
  }
  const intro = `<div class="eyebrow">SHARPEDGE / YOUR ACCOUNT</div><div class="page-title"><div><h1>Manage billing</h1><p>Your membership, billing details and invoices.</p></div><button onclick="loadBillingPage()" ${billingPageLoading||billingBusy?'disabled':''}>Refresh</button></div>`;
  const policy = `<section class="billing-policy"><h2>No-refund policy</h2><p>Membership payments are non-refundable. Upgrades take effect after payment succeeds. Downgrades start at your next renewal. Cancelling stops future renewals, and your access continues until the end of your current paid term.</p></section>`;
  if (!billingPageData) return intro + (billingPageError ? `<p class="auth-error" role="alert">${escapeAccountText(billingPageError)}</p><button onclick="loadBillingPage()">Try again</button>` : '<p role="status">Loading your billing account…</p>') + policy;
  const {account, subscription, customer, invoices} = billingPageData;
  const current = names[account.plan] || 'Guest';
  const address = customer?.address ? ['line1','line2','city','state','postal_code','country'].map(key => customer.address[key]).filter(Boolean).map(escapeAccountText).join(', ') : 'No billing address saved';
  const card = customer?.paymentMethod;
  const pendingInvoice = safeBillingURL(subscription?.pendingPayment);
  return intro + (billingPageError ? `<p class="auth-error" role="alert">${escapeAccountText(billingPageError)}</p>` : '') + `<div class="billing-grid"><section class="billing-card"><h2>Membership</h2><div class="account-membership"><span>Current plan</span><strong>${escapeAccountText(current)}</strong></div>${subscription?`<p>${billingMoney(subscription.monthlyAmount,subscription.currency)} / month</p><p>${subscription.cancelAtPeriodEnd?'Access ends':'Next renewal'}: <strong>${escapeAccountText(billingDate(subscription.renewsAt))}</strong></p>${subscription.cancelAtPeriodEnd?'<p role="status">Your membership is cancelled for renewal. You keep access through the end of your paid term.</p>':''}${subscription.scheduledChange?`<p role="status">${escapeAccountText(names[subscription.scheduledChange.plan] || subscription.scheduledChange.plan)} starts ${escapeAccountText(billingDate(subscription.scheduledChange.effectiveAt))}. Your current plan remains active until then.</p><button onclick="undoScheduledChange(this)" ${billingBusy?'disabled':''}>Keep current plan at renewal</button>`:''}${pendingInvoice?`<p>An upgrade is awaiting payment. Your current paid access is preserved.</p><a class="billing-link" href="${escapeAccountText(pendingInvoice)}" target="_blank" rel="noopener noreferrer">Complete upgrade payment ↗</a>`:''}<div class="actions"><button onclick="go('pricing')">Change plan</button><button onclick="${subscription.cancelAtPeriodEnd?'resumeMembership(this)':'confirmMembershipCancellation()'}" ${billingBusy?'disabled':''}>${subscription.cancelAtPeriodEnd?'Resume membership':'Cancel membership'}</button></div>`:`<p>${account.plan==='guest'?'You do not have a renewing membership.':'Your membership is active. A renewing Stripe subscription was not found for this account.'}</p>${account.membershipExpiresAt?`<p>Access until ${escapeAccountText(billingDate(account.membershipExpiresAt))}</p>`:''}<button onclick="go('pricing')">View plans</button>`}</section><section class="billing-card"><h2>Billing details</h2><p><strong>${escapeAccountText(customer?.name || account.displayName || 'Your account')}</strong><br>${escapeAccountText(customer?.email || account.email)}</p><p>${address}</p><p>${card?`${escapeAccountText(card.brand.toUpperCase())} ending ${escapeAccountText(card.last4)} · Expires ${escapeAccountText(card.expMonth)}/${escapeAccountText(card.expYear)}`:'No saved card shown'}</p>${customer?`<button onclick="openStripeBilling(this)" ${billingBusy?'disabled':''}>Update billing details & payment method</button>`:''}</section></div><section class="billing-card billing-invoices"><div class="section-head"><div><h2>Recent invoices</h2><p>View your payment history and download invoices.</p></div>${customer?'<button onclick="openStripeBilling(this)">Full invoice history ↗</button>':''}</div>${invoices?.length?`<div class="table-wrap"><table><thead><tr><th>Date</th><th>Invoice</th><th>Status</th><th>Total</th><th>Documents</th></tr></thead><tbody>${invoices.map(invoice=>{const url=safeBillingURL(invoice.url),pdf=safeBillingURL(invoice.pdf);return `<tr><td>${escapeAccountText(billingDate(invoice.createdAt))}</td><td>${escapeAccountText(invoice.number || invoice.id)}</td><td>${escapeAccountText(invoice.status)}</td><td>${billingMoney(invoice.total,invoice.currency)}</td><td>${url?`<a class="billing-link" href="${escapeAccountText(url)}" target="_blank" rel="noopener noreferrer">${invoice.amountDue>0?'View / pay':'View'}</a>`:''}${pdf?` <a class="billing-link" href="${escapeAccountText(pdf)}" target="_blank" rel="noopener noreferrer">PDF</a>`:''}</td></tr>`}).join('')}</tbody></table></div>`:'<p>No invoices were found for this billing account.</p>'}</section>${policy}`;
}
async function loadBillingPage() {
  if (!currentAccount || authLoading || billingBusy) return;
  const uid = currentAccount.uid;
  billingPageLoading = true; billingPageError = '';
  render();
  try {
    const data = await window.sharpAuth.getBilling();
    if (currentAccount?.uid !== uid) return;
    billingPageData = data;
  } catch (error) {
    if (currentAccount?.uid === uid) billingPageError = error.message || 'Your billing account could not be loaded. Please try again.';
  } finally {
    if (currentAccount?.uid === uid) { billingPageLoading = false; render(); }
  }
}
function showPlanChange(change) {
  pendingPlanChange = {...change, uid:currentAccount.uid};
  const upgrade = change.kind === 'upgrade', d = $('#modal');
  d.innerHTML = `<div class="eyebrow">SHARPEDGE / CHANGE MEMBERSHIP</div><h2>${upgrade?'Upgrade':'Schedule'} ${escapeAccountText(names[change.plan])}</h2><p>${escapeAccountText(names[change.currentPlan])} → ${escapeAccountText(names[change.plan])}</p><p>New monthly price: <strong>${billingMoney(change.monthlyAmount,change.currency)}</strong></p><p>${upgrade?`Due now: <strong>${billingMoney(change.amountDue,change.currency)}</strong>. This charges the full new monthly price and starts a new billing month after payment succeeds. There is no credit or refund for unused time on your previous plan.`:`Due now: <strong>${billingMoney(0,change.currency)}</strong>. Your current plan stays active until <strong>${escapeAccountText(billingDate(change.effectiveAt))}</strong>. Your new plan and lower price start at that renewal.`}</p><p>Payments are non-refundable.</p><p id="billing-action-error" class="auth-error" role="alert"></p><div class="actions"><button onclick="$('#modal').close()">Keep current plan</button><button class="primary" onclick="confirmPlanChange(this)">${upgrade?'Confirm upgrade & pay':'Confirm downgrade at renewal'}</button></div>`;
  if (!d.open) d.showModal();
}
async function confirmPlanChange(button) {
  if (billingBusy || !pendingPlanChange || currentAccount?.uid !== pendingPlanChange.uid) return;
  const uid = currentAccount.uid, change = pendingPlanChange;
  billingBusy = true; button.disabled = true;
  try {
    const result = await window.sharpAuth.changePlan(change.quote);
    if (currentAccount?.uid !== uid) return;
    $('#modal').close(); pendingPlanChange = null; billingPageData = null;
    if (result.status === 'payment_required') notify('Complete the upgrade invoice to activate your new plan.');
    else notify(result.status === 'scheduled' ? 'Your lower-priced plan is scheduled for renewal.' : 'Your upgraded membership is active.');
    go('account-billing');
    // Keep billing open so invoices requiring authentication can be completed in Stripe.
  } catch (error) {
    if (currentAccount?.uid === uid) $('#billing-action-error').textContent = error.message || 'Your plan could not be changed. Please try again.';
  } finally {
    if (currentAccount?.uid === uid) { billingBusy = false; button.disabled = false; render(); }
  }
}
function confirmMembershipCancellation() {
  const end = billingPageData?.subscription?.renewsAt, d = $('#modal');
  d.innerHTML = `<div class="eyebrow">SHARPEDGE / CANCEL MEMBERSHIP</div><h2>Cancel your next renewal?</h2><p>Your access continues until <strong>${escapeAccountText(billingDate(end))}</strong>. You will not be billed for another term. Any scheduled plan change will be removed.</p><p>Payments are non-refundable.</p><p id="billing-action-error" class="auth-error" role="alert"></p><div class="actions"><button onclick="$('#modal').close()">Keep membership</button><button onclick="cancelMembership(this)">Cancel at end of paid term</button></div>`;
  if (!d.open) d.showModal();
}
async function updateRenewal(button, action, success) {
  if (billingBusy || !currentAccount) return;
  const uid = currentAccount.uid;
  billingBusy = true; button.disabled = true;
  try {
    await action();
    if (currentAccount?.uid !== uid) return;
    $('#modal').close(); billingPageData = null; notify(success);
  } catch (error) {
    if (currentAccount?.uid === uid) notify(error.message || 'Your renewal settings could not be updated. Please try again.');
  } finally {
    if (currentAccount?.uid === uid) { billingBusy = false; button.disabled = false; render(); }
  }
}
const cancelMembership = button => updateRenewal(button, () => window.sharpAuth.setCancellation(true), 'Renewal cancelled. Your paid access continues until the end of the term.');
const resumeMembership = button => updateRenewal(button, () => window.sharpAuth.setCancellation(false), 'Your membership will renew as usual.');
const undoScheduledChange = button => updateRenewal(button, () => window.sharpAuth.removeScheduledChange(), 'Your current plan will continue at renewal.');
async function openStripeBilling(button) {
  if (billingBusy) return;
  const uid = currentAccount?.uid;
  billingBusy = true; button.disabled = true;
  try { await window.sharpAuth.manageBilling(); }
  catch (error) { if (currentAccount?.uid === uid) notify(error.message || 'Billing details could not be opened. Please try again.'); }
  finally { if (currentAccount?.uid === uid) { billingBusy = false; button.disabled = false; } }
}
window.addEventListener('focus', () => {
  if (currentAccount && !authLoading && !billingBusy && !billingPageLoading && route() === 'account-billing') loadBillingPage();
});
