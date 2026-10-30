// Only Firebase's public web configuration is returned by the server.
const authState = window.sharpAuth = {ready:false, user:null, account:null, profile:{}, error:'', dataError:''};
let sdk, auth, db, revision = 0, writeQueue = Promise.resolve(), sessionQueue = Promise.resolve();
const pendingSignups = new Set();
const update = () => window.authChanged?.(authState);
const messages = {
  'auth/popup-closed-by-user':'Sign-in was cancelled. You can try again.',
  'auth/popup-blocked':'Allow pop-ups for SharpEdge, then try again.',
  'auth/cancelled-popup-request':'A sign-in window is already open.',
  'auth/unauthorized-domain':'Sign-in is not available on this address yet.',
  'auth/network-request-failed':'Check your connection and try again.',
  'auth/operation-not-allowed':'Google sign-in is not available yet.',
  'auth/configuration-not-found':'Google sign-in is not available yet.',
  'auth/user-disabled':'This account has been disabled.'
};
function report(error, fallback) {
  authState.error = messages[error?.code] || (error?.code?.startsWith('account/') ? error.message : fallback);
  update();
}
function accountFailure(stage, error) {
  console.error('SharpEdge account setup failed', {stage, code:error?.code || 'unknown'});
  const failure = new Error(stage === 'session' && error?.serverMessage ? error.serverMessage : stage === 'profile'
    ? 'Google sign-in succeeded, but your profile could not be saved. Try again or contact support.'
    : 'Google sign-in succeeded, but your session could not be started. Try again.');
  failure.code = `account/${stage}`;
  return failure;
}
async function sessionFor(user) {
  const next = sessionQueue.catch(() => {}).then(async () => {
    if (authState.signingOut || auth.currentUser?.uid !== user.uid) throw new Error('Your session has ended.');
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = await fetch('/api/session', {method:'POST', headers:{authorization:`Bearer ${await user.getIdToken(attempt > 0)}`}, signal:AbortSignal.timeout(30000)});
      let account;
      try { account = await response.json(); }
      catch {
        const error = new Error('The sign-in server returned an unexpected response. Reload SharpEdge and try again.');
        error.code = `session/http-${response.status}`;
        error.serverMessage = error.message;
        throw error;
      }
      if (response.ok) return account;
      if (attempt === 0 && response.status === 401 && ['AUTH_TOKEN_EXPIRED', 'AUTH_INVALID_ID_TOKEN', 'AUTH_TOKEN_NOT_YET_VALID'].includes(account.code)) continue;
      const error = new Error(account.error || 'Unable to sign in. Please try again.');
      error.code = account.code || `session/http-${response.status}`;
      error.serverMessage = typeof account.error === 'string' ? account.error : 'Your session could not be started. Please try again.';
      throw error;
    }
  });
  sessionQueue = next;
  return next;
}
function safeNext(account = authState.account, isNewProfile = false) {
  const next = new URLSearchParams(location.search).get('next');
  if (isNewProfile || (account?.plan === 'guest' && next !== '/analysis')) return '/#pricing';
  return ['/ev', '/arbitrage', '/parlay', '/analysis', '/#pricing'].includes(next) ? next : '/ev';
}
function savedFromProfile(profile) {
  return {bankroll:profile.bankroll ?? 1000, tracked:JSON.stringify(profile.betHistory ?? []), savedEntry:JSON.stringify(profile.savedEntry ?? {})};
}
async function ensureProfile(user) {
  const ref = sdk.doc(db, 'users', user.uid);
  return sdk.runTransaction(db, async transaction => {
    const snapshot = await transaction.get(ref), existing = snapshot.exists() ? snapshot.data() : {};
    let legacy = {};
    // Older accounts kept their journal in a nested state document. Read it
    // before any transaction writes and copy it only when the new field is absent.
    if (snapshot.exists() && !Object.hasOwn(existing, 'betHistory')) {
      const old = await transaction.get(sdk.doc(db, 'users', user.uid, 'app', 'state'));
      if (old.exists()) {
        const state = old.data();
        legacy = {bankroll:state.bankroll ?? 1000, betHistory:JSON.parse(state.tracked || '[]'), savedEntry:JSON.parse(state.savedEntry || 'null')};
      }
    }
    const identity = {displayName:user.displayName || '', email:user.email || '', photoURL:user.photoURL || '', provider:'google.com', lastSignInAt:sdk.serverTimestamp()};
    const defaults = {signupDate:sdk.serverTimestamp(), plan:'guest', expiresAt:null, bankroll:1000, betHistory:[], savedEntry:null};
    const missing = Object.fromEntries(Object.entries(defaults).filter(([key]) => !Object.hasOwn(existing, key)));
    const patch = {...missing, ...legacy, ...identity};
    transaction.set(ref, patch, {merge:true});
    return {created:!snapshot.exists(), profile:{...existing, ...patch}};
  });
}
async function loadUser(user, current) {
  await writeQueue.catch(() => {});
  if (current !== revision) return;
  let result, account;
  try { result = await ensureProfile(user); }
  catch (error) { throw accountFailure('profile', error); }
  if (result.created) pendingSignups.add(user.uid);
  if (current !== revision) return;
  try { account = await sessionFor(user); }
  catch (error) { throw accountFailure('session', error); }
  if (current !== revision) return;
  authState.user = user;
  authState.account = account;
  authState.profile = result.profile;
  authState.saved = savedFromProfile(result.profile);
  authState.error = '';
  authState.dataError = '';
  authState.ready = true;
  update();
  const isNewProfile = pendingSignups.has(user.uid);
  if (isNewProfile || location.pathname === '/signin' || location.hash === '#signin') {
    pendingSignups.delete(user.uid);
    location.replace(safeNext(account, isNewProfile));
  }
}
authState.signIn = async () => {
  if (!auth || !sdk) return;
  authState.error = '';
  authState.signingIn = true;
  update();
  try {
    const provider = new sdk.GoogleAuthProvider();
    provider.setCustomParameters({prompt:'select_account'});
    await sdk.signInWithPopup(auth, provider);
  } catch (error) { report(error, 'Unable to sign in. Please try again.'); }
  finally { authState.signingIn = false; update(); }
};
authState.signOut = async () => {
  // Finish any earlier cookie refresh before clearing it, so a late response
  // cannot restore the session after logout.
  authState.signingOut = true;
  revision++;
  try {
    await sessionQueue.catch(() => {});
    const response = await fetch('/api/session', {method:'DELETE', signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Unable to sign out. Please try again.');
    authState.account = null;
    authState.user = null;
    authState.profile = {};
    authState.saved = {};
    update();
    await sdk.signOut(auth);
    location.replace('/');
  } finally { authState.signingOut = false; }
};
authState.retry = async () => {
  if (!auth?.currentUser) return location.reload();
  authState.ready = false;
  update();
  try { await loadUser(auth.currentUser, ++revision); }
  catch (error) { authState.ready = true; report(error, 'Unable to load your account. Please try again.'); }
};
authState.fetch = async (path, options = {}) => {
  if (!authState.account || !auth?.currentUser) throw new Error('Sign in to continue.');
  const headers = new Headers(options.headers);
  headers.set('authorization', `Bearer ${await auth.currentUser.getIdToken()}`);
  const response = await fetch(path, {...options, headers, cache:'no-store'});
  if (response.status === 401) {
    authState.account = null;
    authState.user = null;
    authState.profile = {};
    authState.saved = {};
    authState.error = 'Your session has ended. Please sign in again.';
    update();
  }
  if (response.status === 403) {
    const denied = await response.clone().json();
    if (authState.account && denied.account?.uid === authState.account.uid) {
      authState.account = denied.account;
      update();
    }
  }
  return response;
};
authState.expireMembership = () => {
  const account = authState.account;
  if (account && Date.parse(account.membershipExpiresAt) <= Date.now()) {
    authState.account = {...account, plan:'guest'};
    update();
  }
};
authState.saveState = patch => {
  const user = authState.user, current = revision;
  const write = writeQueue.catch(() => {}).then(async () => {
    if (!user || !authState.account || current !== revision || !authState.ready || authState.signingOut) throw new Error('Sign in before saving.');
    const fields = {};
    if (Object.hasOwn(patch, 'bankroll')) fields.bankroll = patch.bankroll;
    if (Object.hasOwn(patch, 'tracked')) fields.betHistory = JSON.parse(patch.tracked);
    if (Object.hasOwn(patch, 'savedEntry')) fields.savedEntry = JSON.parse(patch.savedEntry);
    await sdk.setDoc(sdk.doc(db, 'users', user.uid), {...fields, updatedAt:sdk.serverTimestamp()}, {merge:true});
    authState.profile = {...authState.profile, ...fields};
    authState.saved = {...authState.saved, ...patch};
    authState.dataError = '';
  });
  writeQueue = write;
  return write.catch(error => {
    if (current === revision) {
      authState.dataError = 'Your changes could not be saved. Check your connection and try again.';
    }
    throw error;
  });
};
authState.selectPlan = async plan => {
  if (!['gold', 'plus', 'fantasy', 'fantasyplus', 'platinum'].includes(plan)) throw new Error('Choose an available plan.');
  const user = authState.user, current = revision;
  if (!user || !authState.account || !authState.ready || authState.signingOut) throw new Error('Sign in before choosing a plan.');
  await sdk.setDoc(sdk.doc(db, 'users', user.uid), {requestedPlan:plan, planRequestedAt:sdk.serverTimestamp()}, {merge:true});
  if (current !== revision) return;
  authState.profile = {...authState.profile, requestedPlan:plan};
  update();
};
async function initialize() {
  try {
    const response = await fetch('/api/auth/config', {cache:'no-store'});
    if (!response.ok) throw new Error('Sign-in is temporarily unavailable. Please try again later.');
    const {databaseId, ...config} = await response.json();
    const [appSDK, authSDK, firestoreSDK] = await Promise.all([
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js'),
      import('https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js')
    ]);
    sdk = {...authSDK, ...firestoreSDK};
    const app = appSDK.initializeApp(config);
    auth = sdk.getAuth(app);
    db = sdk.initializeFirestore(app, {}, databaseId || '(default)');
    authState.available = true;
    // Session storage avoids leaving a signed-in account on a shared device.
    await sdk.setPersistence(auth, sdk.browserSessionPersistence);
    sdk.onIdTokenChanged(auth, async user => {
      const current = ++revision;
      if (authState.signingOut) return;
      if (!user) {
        authState.user = null;
        authState.account = null;
        authState.profile = {};
        authState.saved = {};
        authState.ready = true;
        // Also clear a cookie left over from a closed browser session.
        try { await fetch('/api/session', {method:'DELETE'}); } catch {}
        if (current === revision) update();
        return;
      }
      authState.ready = false;
      update();
      try { await loadUser(user, current); }
      catch (error) {
        if (current !== revision) return;
        authState.account = null;
        authState.user = null;
        authState.profile = {};
        authState.saved = {};
        authState.ready = true;
        report(error, 'Unable to load your account. Please try again.');
      }
    });
  } catch (error) {
    authState.ready = true;
    report(error, 'Sign-in is temporarily unavailable. Please try again later.');
  }
}
initialize();
