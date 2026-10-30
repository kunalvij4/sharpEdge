import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements = new Map();
const events = new Map();
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, {innerHTML:'', textContent:'', style:{}, close(){this.open=false}, showModal(){this.open=true}});
  return elements.get(selector);
};
const context = vm.createContext({
  window:{__SHARPEDGE_SERVER__:true, __SHARPEDGE_ACCOUNT__:null, addEventListener(name,handler){events.set(name,handler)}, scrollTo(){}, sharpAuth:{ready:true, available:true, saved:{}}},
  location:{pathname:'/signin',hash:'',search:'',href:'',replace(){}},
  document:{querySelector:element, querySelectorAll:()=>[], addEventListener(){}, cookie:''},
  localStorage:{getItem(){throw new Error('Account state must not come from browser-local demo storage')},setItem(){throw new Error('Account state must not be stored as a global demo profile')}},
  bookCatalog:{}, bookCategory:()=> 'Sportsbook', stopHighlightReel(){},
  matchMedia:()=>({matches:true}), setTimeout:()=>1, clearTimeout(){}, setInterval(){},
  console, Intl, URLSearchParams, Map, Set
});
vm.runInContext(fs.readFileSync(new URL('../web/account-ui.js',import.meta.url),'utf8'), context);
vm.runInContext(fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8'), context);
assert.equal(vm.runInContext("can('ev')",context),false);
assert.match(element('#app').innerHTML, /Connecting to your account/);
context.state = {ready:true,available:true,account:null,saved:{},error:''};
vm.runInContext('authChanged(state)',context);
assert.match(element('#app').innerHTML, /Continue with Google/);
context.state = {ready:true, account:{uid:'alice',email:'alice@example.test',displayName:'Alice',plan:'gold',membershipExpiresAt:new Date(Date.now()+86400000).toISOString()},saved:{bankroll:2500,tracked:JSON.stringify([{uid:1,name:'<img onerror="alert(1)">',bet:'Over 5.5',book:'FanDuel',odds:'+110',stake:10,close:null}])}};
vm.runInContext('authChanged(state)', context);
assert.equal(vm.runInContext('bankroll',context),2500);
assert.equal(vm.runInContext('tracked.length',context),1);
assert.doesNotMatch(vm.runInContext('tracked[0].name',context), /[<>"']/);
assert.equal(vm.runInContext("can('ev')",context),true);
assert.equal(vm.runInContext("can('arbitrage')",context),false);
vm.runInContext("choose('platinum')",context);
assert.equal(vm.runInContext('plan',context),'gold', 'The pricing selector cannot grant a membership');
vm.runInContext('explore()',context);
assert.equal(vm.runInContext('plan',context),'gold', 'Explore cannot grant demo Platinum');
vm.runInContext('showAccount()',context);
assert.match(element('#modal').innerHTML,/Access until <time datetime=/);
// Expiration removes market access while preserving account data.
context.state.account = {...context.state.account,plan:'guest',membershipExpiresAt:'2000-01-01T00:00:00.000Z'};
vm.runInContext("data=[{private:true}];arbs=[{private:true}];legs=['private'];authChanged(state);showAccount()",context);
assert.equal(vm.runInContext("can('ev')",context),false);
assert.equal(vm.runInContext('data.length+arbs.length+legs.length',context),0);
assert.equal(vm.runInContext('tracked.length',context),1,'Expiration preserves the bet journal');
assert.equal(vm.runInContext('bankroll',context),2500,'Expiration preserves bankroll settings');
assert.match(element('#modal').innerHTML,/Membership expired/);
events.get('pagehide')();
assert.equal(element('#app').innerHTML,'', 'Private content is cleared before browser page caching');
context.state = {ready:true,account:{uid:'bob',email:'bob@example.test',plan:'guest'},saved:{}};
vm.runInContext('authChanged(state)',context);
assert.equal(vm.runInContext('tracked.length',context),0,'Switching users clears the previous journal');
assert.equal(vm.runInContext('bankroll',context),1000,'Switching users clears the previous bankroll');
assert.equal(vm.runInContext("can('analysis')",context),true, 'A signed-in free account can open its journal');
vm.runInContext("data=[{private:true}]; arbs=[{private:true}]; legs=['private'];",context);
context.state = {ready:true,account:null,saved:{}};
vm.runInContext('authChanged(state)',context);
for (const collection of ['tracked','data','arbs','legs']) assert.equal(vm.runInContext(collection+'.length',context),0);
assert.equal(vm.runInContext("can('analysis')",context),false);
assert.equal(vm.runInContext('window.__SHARPEDGE_FEED__',context),null);
console.log('Account UI tests passed: sign-in gates, membership bypass removal, saved-data validation, account switching and logout cleanup.');
