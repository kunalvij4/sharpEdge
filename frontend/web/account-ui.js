let loadedAccountSnapshot;
let membershipTimer;
const escapeAccountText = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
function signInPage() {
  const state = window.sharpAuth;
  return `<section class="auth-page"><div class="auth-card"><a class="brand" href="/">SHARP<span>EDGE</span></a><div class="eyebrow">YOUR EDGE STARTS HERE</div><h1>One account.<br><em>Your advantage.</em></h1><p>Sign in to access your workspace and keep your settings and bet journal together across devices.</p>${authLoading?'<p class="auth-status" role="status">Connecting to your account…</p>':`<button class="google-signin" onclick="signInWithGoogle()" ${!state?.available||state?.signingIn?'disabled':''}><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285f4" d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4Z"/><path fill="#34a853" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.9-1.8-5.7-4.2H3v2.6A10 10 0 0 0 12 22Z"/><path fill="#fbbc05" d="M6.3 13.9a6 6 0 0 1 0-3.8V7.5H3a10 10 0 0 0 0 9l3.3-2.6Z"/><path fill="#ea4335" d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.8-2.8A9.6 9.6 0 0 0 12 2a10 10 0 0 0-9 5.5l3.3 2.6A6 6 0 0 1 12 5.9Z"/></svg>${state?.signingIn?'Signing in…':'Continue with Google'}</button>`}${authError?`<p class="auth-error" role="alert">${escapeAccountText(authError)}</p><button class="auth-retry" onclick="window.sharpAuth.retry()">Try again</button>`:''}<p class="auth-note">New here? Your account is created when you sign in.<br>By continuing, you agree to our <a href="/#terms">Terms</a> and acknowledge our <a href="/#privacy">Privacy Policy</a>.</p><a class="auth-back" href="/">← Back to SharpEdge</a></div><aside class="auth-aside"><span class="mark">ϟ</span><h2>Less guesswork.<br>More edge.</h2><p>Your process, saved.<br>Your next opportunity, in focus.</p><span class="eyebrow">SPORTSBOOKS + FANTASY APPS</span></aside></section>`;
}
function signInWithGoogle() { window.sharpAuth?.signIn(); }
function showAccount() {
  if (!currentAccount) {
    location.href = '/signin?next=' + encodeURIComponent(['/ev','/arbitrage','/parlay','/analysis'].includes(location.pathname) ? location.pathname : '/ev');
    return;
  }
  const d = $('#modal');
  d.innerHTML = `<div class="eyebrow">SHARPEDGE / YOUR ACCOUNT</div><h2>${escapeAccountText(currentAccount.displayName || 'Your account')}</h2><p>${escapeAccountText(currentAccount.email)}</p><div class="account-membership"><span>Membership</span><strong>${currentAccount.plan==='guest'?'Guest':escapeAccountText(names[currentAccount.plan] || 'Guest')}</strong></div>${membershipExpiration()}<p>Your bankroll, bet journal and saved entry are stored privately in your account.</p>${savedEntryPanel()}${window.sharpAuth?.dataError?`<p class="auth-error" role="alert">${escapeAccountText(window.sharpAuth.dataError)}</p>`:''}<div class="actions"><button onclick="$('#modal').close()">Close</button><button onclick="signOutOfAccount(this)">Sign out</button></div>`;
  if (!d.open) d.showModal();
}
async function signOutOfAccount(button) {
  button.disabled = true;
  try { await window.sharpAuth.signOut(); }
  catch { button.disabled = false; notify('Unable to sign out. Check your connection and try again.'); }
}
async function requestMembership(p) {
  if (!currentAccount) return showAccount();
  if (currentAccount.plan === p) return notify('This is your current membership.');
  try {
    await window.sharpAuth.selectPlan(p);
    notify(`${names[p]} selected. Payment and activation are not available yet; no charge was made.`);
  } catch { notify('Your plan choice could not be saved. Please try again.'); }
}
function membershipExpiration() {
  const expiry = new Date(currentAccount?.membershipExpiresAt ?? '');
  if (!Number.isFinite(expiry.getTime())) return '';
  return `<p class="membership-expiration">${expiry.getTime() <= Date.now() ? 'Membership expired' : 'Access until'} <time datetime="${expiry.toISOString()}">${escapeAccountText(expiry.toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'}))}</time></p>`;
}
function scheduleMembershipExpiration() {
  clearTimeout(membershipTimer);
  const remaining = Date.parse(currentAccount?.membershipExpiresAt) - Date.now();
  if (!currentAccount || currentAccount.plan === 'guest' || !Number.isFinite(remaining)) return;
  // Long memberships need another timer after the browser's maximum delay.
  membershipTimer = setTimeout(() => {
    if (Date.parse(currentAccount?.membershipExpiresAt) <= Date.now()) window.sharpAuth?.expireMembership();
    else scheduleMembershipExpiration();
  }, Math.max(0, Math.min(remaining, 2147483647)));
}
function readTracked(value) {
  try {
    const rows = JSON.parse(value || '[]');
    if (!Array.isArray(rows)) return [];
    const text = value => String(value ?? '').replace(/[<>&"'`]/g, '').slice(0,300);
    const odds = value => Number.isFinite(Number(value)) && Math.abs(Number(value)) >= 100 ? text(value) : null;
    return rows.slice(0,500).filter(row => row && Number.isSafeInteger(row.uid) && Number.isFinite(row.stake) && row.stake > 0 && odds(row.odds)).map(row => ({
      uid:row.uid, name:text(row.name), bet:text(row.bet), game:text(row.game), league:text(row.league), book:text(row.book),
      odds:odds(row.odds), stake:row.stake, close:row.close === null ? null : odds(row.close)
    }));
  } catch { return []; }
}
function savedEntryPanel() {
  try {
    const entry = JSON.parse(window.sharpAuth?.saved?.savedEntry || '{}');
    if (!Array.isArray(entry.legs) || !entry.legs.length || !Number.isFinite(entry.amount) || entry.amount <= 0) return '';
    return `<section class="saved-entry"><h3>Your saved entry</h3><p>${money(entry.amount)} · ${entry.legs.length} selections · No wager placed</p><ul>${entry.legs.slice(0,6).map(leg => `<li>${escapeAccountText(leg.bet)} <small>${escapeAccountText(leg.book)}</small></li>`).join('')}</ul></section>`;
  } catch { return ''; }
}
function authChanged(state) {
  const previousUID = currentAccount?.uid;
  const previousPlan = plan;
  authLoading = !state.ready;
  authError = state.error || '';
  currentAccount = state.account;
  plan = currentAccount?.plan || 'guest';
  if (!currentAccount || currentAccount.uid !== previousUID) {
    tracked = []; bankroll = 1000;
  }
  if (!currentAccount || currentAccount.uid !== previousUID || plan !== previousPlan) {
    legs = []; payoutOverride = null; legProbOverrides = {};
    data = []; arbs = []; window.__SHARPEDGE_FEED__ = null;
    $('#modal').close();
  }
  if (currentAccount && state.saved !== loadedAccountSnapshot) {
    loadedAccountSnapshot = state.saved;
    tracked = readTracked(state.saved?.tracked);
    const amount = Number(state.saved?.bankroll);
    bankroll = Number.isFinite(amount) && amount >= 1 && amount <= 1000000000 ? amount : 1000;
  }
  render();
  scheduleMembershipExpiration();
  if (state.dataError) notify(state.dataError);
  if (currentAccount && !authLoading && (currentAccount.uid !== previousUID || plan !== previousPlan) && ['ev','arbitrage','parlay'].includes(route())) refreshAccountFeed();
}
async function refreshAccountFeed() {
  if (!currentAccount || !window.sharpAuth?.ready) return;
  const uid = currentAccount.uid;
  const requestedPlan = plan;
  try {
    const response = await window.sharpAuth.fetch('/api/feeds');
    if (!response.ok) return;
    const feed = await response.json();
    if (currentAccount?.uid !== uid || plan !== requestedPlan || !(Date.parse(currentAccount.membershipExpiresAt) > Date.now())) return;
    window.__SHARPEDGE_FEED__ = feed; data = feed.ev; arbs = feed.arbs; render();
  } catch { notify('Could not refresh market data. Try again shortly.'); }
}
// Clear private DOM before a page can enter the browser's back/forward cache.
window.addEventListener('pagehide', () => {
  if (currentAccount) {
    $('#modal').close();
    $('#modal').innerHTML = '';
    $('#app').innerHTML = '';
    $('.signin').textContent = 'Sign in';
  }
});
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
