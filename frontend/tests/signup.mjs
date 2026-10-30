import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../web/auth.js',import.meta.url),'utf8').replace(/\ninitialize\(\);\s*$/, '\n');
const user = {uid:'new-user',displayName:'New User',email:'new@example.test',photoURL:'',getIdToken:async()=> 'test-id-token'};
const plain = value => JSON.parse(JSON.stringify(value));
function setup(initial = {}) {
  const docs = new Map(Object.entries(initial)), events = [], redirects = [], diagnostics = [];
  let stamp = 0, failProfile = false, failSession = false;
  const sdk = {
    doc:(_db,...parts)=>parts.join('/'), serverTimestamp:()=>`server-timestamp-${++stamp}`,
    runTransaction:async(_db, callback)=>{
      const writes = [];
      const result = await callback({
        get:async path=>{
          events.push(['get',path]);
          if (failProfile) throw Object.assign(new Error('denied'),{code:'permission-denied'});
          return {exists:()=>docs.has(path), data:()=>plain(docs.get(path))};
        },
        set:(path, fields)=>writes.push([path,plain(fields)])
      });
      for (const [path,fields] of writes) {
        events.push(['set',path]);
        docs.set(path,{...docs.get(path),...fields});
      }
      return result;
    },
    setDoc:async(path,fields)=>{events.push(['set',path]);docs.set(path,{...docs.get(path),...plain(fields)})}
  };
  const context = vm.createContext({
    window:{}, location:{pathname:'/signin',hash:'',search:'?next=%2Fanalysis',replace:path=>redirects.push(path)},
    URLSearchParams, Headers, AbortSignal, user, fakeSDK:sdk, fakeAuth:{currentUser:user},
    console:{error:(...args)=>diagnostics.push(args)},
    fetch:async(path,options)=>{
      assert.equal(path,'/api/session');
      assert.equal(options.headers.authorization,'Bearer test-id-token');
      events.push(['session']);
      // The Guest document must exist before the app session checks access.
      assert.ok(docs.has('users/new-user'));
      if (failSession) return Response.json({error:'Session unavailable'},{status:503});
      const profile = docs.get('users/new-user');
      return Response.json({uid:user.uid,email:user.email,displayName:user.displayName,photoURL:'',plan:profile.plan,membershipExpiresAt:profile.expiresAt});
    }
  });
  vm.runInContext(source,context);
  vm.runInContext('sdk=fakeSDK;auth=fakeAuth;db={}',context);
  return {context,docs,events,redirects,diagnostics,
    load:()=>vm.runInContext('loadUser(user,revision)',context),
    denyProfile:()=>{failProfile=true}, denySession:()=>{failSession=true}, allowSession:()=>{failSession=false}
  };
}

const fresh = setup();
await fresh.load();
const profile = fresh.docs.get('users/new-user');
assert.equal(profile.plan,'guest');
assert.equal(profile.expiresAt,null);
assert.match(profile.signupDate,/server-timestamp-/);
assert.deepEqual(profile.betHistory,[]);
assert.equal(profile.email,user.email);
assert.equal(fresh.docs.size,1,'Account data uses one users document');
assert.ok(fresh.events.findIndex(event=>event[0]==='set') < fresh.events.findIndex(event=>event[0]==='session'));
assert.deepEqual(fresh.redirects,['/#pricing'],'A first profile goes to pricing even if a tool was requested');
assert.equal(vm.runInContext('authState.ready && authState.account.plan',fresh.context),'guest');

await vm.runInContext("authState.selectPlan('gold')",fresh.context);
assert.equal(fresh.docs.get('users/new-user').requestedPlan,'gold');
assert.equal(fresh.docs.get('users/new-user').plan,'guest','Choosing a plan does not grant paid access');
assert.equal(fresh.docs.get('users/new-user').expiresAt,null);
await assert.rejects(vm.runInContext("authState.selectPlan('admin')",fresh.context));

const history = [{uid:123,name:'Example',bet:'Over 5.5',book:'FanDuel',odds:'+110',stake:10,close:null}];
fresh.context.history = history;
await vm.runInContext('authState.saveState({tracked:JSON.stringify(history),bankroll:2500})',fresh.context);
assert.deepEqual(fresh.docs.get('users/new-user').betHistory,history,'History is stored as a Firestore array');
assert.ok(!Object.hasOwn(fresh.docs.get('users/new-user'),'tracked'));

const signupDate = profile.signupDate, expiration = '2099-01-01T00:00:00.000Z';
Object.assign(fresh.docs.get('users/new-user'),{plan:'platinum',expiresAt:expiration});
vm.runInContext("location.search='?next=%2Fparlay'",fresh.context);
await fresh.load();
assert.equal(fresh.docs.get('users/new-user').signupDate,signupDate,'Repeat sign-in preserves signup date');
assert.equal(fresh.docs.get('users/new-user').plan,'platinum');
assert.equal(fresh.docs.get('users/new-user').expiresAt,expiration);
assert.deepEqual(fresh.docs.get('users/new-user').betHistory,history);
assert.equal(fresh.redirects.at(-1),'/parlay','Returning members retain their destination');

const old = setup({
  'users/new-user':{displayName:'New User',email:user.email,photoURL:'',provider:'google.com',lastSignInAt:'old'},
  'users/new-user/app/state':{bankroll:3300,tracked:JSON.stringify(history),savedEntry:JSON.stringify({legs:[],amount:10})}
});
await old.load();
assert.deepEqual(old.docs.get('users/new-user').betHistory,history);
assert.equal(old.docs.get('users/new-user').bankroll,3300);
assert.equal(old.docs.get('users/new-user').plan,'guest');
assert.ok(old.docs.has('users/new-user/app/state'),'Migration preserves the source document');
const legacyReads = old.events.filter(event=>event[1]==='users/new-user/app/state').length;
await old.load();
assert.equal(old.events.filter(event=>event[1]==='users/new-user/app/state').length,legacyReads,'Migration runs once');

const denied = setup();
denied.denyProfile();
await assert.rejects(denied.load(), error=>error.code==='account/profile' && /profile could not be saved/.test(error.message));
assert.equal(denied.events.some(event=>event[0]==='session'),false,'A failed profile cannot finish sign-up');
assert.deepEqual(denied.redirects,[]);
assert.equal(denied.diagnostics[0][1].code,'permission-denied');

const retry = setup();
retry.denySession();
await assert.rejects(retry.load(), error=>error.code==='account/session');
const originalDate = retry.docs.get('users/new-user').signupDate;
retry.allowSession();
await retry.load();
assert.equal(retry.docs.get('users/new-user').signupDate,originalDate);
assert.equal(retry.redirects.at(-1),'/#pricing','A retry after a failed session still onboards a Guest to pricing');
console.log('Sign-up tests passed: Guest creation before sessions, pricing redirect, plan requests, user-document history, repeat sign-in, migration and setup failure recovery.');
