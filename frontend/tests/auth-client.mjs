import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

let releaseLogin;
const pendingLogin = new Promise(resolve => {releaseLogin = resolve});
let loginStarted;
const started = new Promise(resolve => {loginStarted = resolve});
const methods = [], writes = [];
const user = {uid:'alice',getIdToken:async()=> 'verified-token'};
const context = vm.createContext({
  window:{}, location:{search:'?next=https://evil.test',replace(){}},
  URLSearchParams, Headers, AbortSignal,
  fetch:async (_path, options) => {
    methods.push(options.method);
    if (options.method === 'POST') { loginStarted(); await pendingLogin; }
    return Response.json(options.method === 'POST' ? {uid:'alice',plan:'gold'} : {ok:true});
  },
  fakeAuth:{currentUser:user}, user,
  fakeSDK:{
    doc:(_db,...path)=>path.join('/'), serverTimestamp:()=> 'server-time',
    setDoc:async(path, value)=>{writes.push({path,value})}, signOut:async()=>{}
  }
});
const source = fs.readFileSync(new URL('../web/auth.js',import.meta.url),'utf8').replace(/\ninitialize\(\);\s*$/, '\n');
vm.runInContext(source,context);
assert.equal(vm.runInContext('safeNext()',context),'/ev','External return paths are rejected');
vm.runInContext("location.search='?next=%2Fanalysis'",context);
assert.equal(vm.runInContext('safeNext()',context),'/analysis');
vm.runInContext('sdk=fakeSDK;auth=fakeAuth;db={};authState.user=user;authState.account={uid:user.uid};authState.ready=true;',context);
await vm.runInContext('authState.saveState({bankroll:2500})',context);
assert.equal(writes[0].path,'users/alice');
assert.equal(writes[0].value.bankroll,2500);
assert.equal(vm.runInContext('authState.saved.bankroll',context),2500);
vm.runInContext('fakeSDK.setDoc=async()=>{throw new Error("offline")}',context);
await assert.rejects(vm.runInContext('authState.saveState({bankroll:9999})',context));
assert.equal(vm.runInContext('authState.saved.bankroll',context),2500, 'Failed writes do not replace the saved value');
assert.match(vm.runInContext('authState.dataError',context), /could not be saved/);
vm.runInContext("authState.account={uid:'alice',plan:'gold',membershipExpiresAt:'2000-01-01T00:00:00.000Z'};authState.expireMembership()",context);
assert.equal(vm.runInContext('authState.account.plan',context),'guest');
assert.equal(vm.runInContext('authState.user.uid',context),'alice','A membership expiration does not sign the user out');
const login = vm.runInContext('sessionFor(user)',context);
await started;
const logout = vm.runInContext('authState.signOut()',context);
await Promise.resolve();
assert.deepEqual(methods,['POST'],'Logout waits for the in-flight session refresh');
releaseLogin();
await login;
await logout;
assert.deepEqual(methods,['POST','DELETE'],'The last cookie operation must clear the session');
assert.equal(vm.runInContext('authState.account',context),null);
assert.equal(vm.runInContext('authState.user',context),null);
await assert.rejects(vm.runInContext('authState.saveState({bankroll:9999})',context));
// A server-side expiry can be earlier than the date the browser cached.
vm.runInContext("authState.account={uid:'alice',plan:'gold',membershipExpiresAt:'2099-01-01T00:00:00Z'};fakeAuth.currentUser=user",context);
context.fetch = async () => Response.json({account:{uid:'alice',plan:'guest',membershipExpiresAt:'2000-01-01T00:00:00.000Z'}}, {status:403});
await vm.runInContext("authState.fetch('/api/feeds')",context);
assert.equal(vm.runInContext('authState.account.plan',context),'guest','A server denial clears a stale paid membership');
assert.equal(vm.runInContext('authState.account.membershipExpiresAt',context),'2000-01-01T00:00:00.000Z');
// Retry one expired cached token using Firebase's forced refresh, then stop.
const refreshes = [];
user.getIdToken = async force => {refreshes.push(force); return force ? 'new-token' : 'old-token'};
let sessionAttempts = 0;
context.fetch = async () => ++sessionAttempts === 1
  ? Response.json({error:'Expired',code:'AUTH_TOKEN_EXPIRED'},{status:401})
  : Response.json({uid:'alice',plan:'guest'});
assert.equal((await vm.runInContext('sessionFor(user)',context)).plan,'guest');
assert.deepEqual(refreshes,[false,true]);
sessionAttempts = 0;
context.fetch = async () => {sessionAttempts++;return Response.json({error:'Account storage is unavailable.',code:'AUTH_PROFILE_READ_DENIED'},{status:503})};
await assert.rejects(vm.runInContext('sessionFor(user)',context),error => error.code==='AUTH_PROFILE_READ_DENIED' && error.serverMessage==='Account storage is unavailable.');
assert.equal(sessionAttempts,1,'A permissions error is not retried as a stale token');
console.log('Auth client tests passed: safe return paths, user-owned writes, save failures, membership expiration and logout/session-refresh ordering.');
