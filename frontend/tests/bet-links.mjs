import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import worker from '../dist/server/index.js';

const app = fs.readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const links = fs.readFileSync(new URL('../web/bet-links.js', import.meta.url), 'utf8');
const opened = [];
const context = vm.createContext({URL, window:{__SHARPEDGE_SERVER__:true,open:(...args)=>opened.push(args)},
  notify:message=>assert.fail(message), bookCategory:()=> 'Sportsbook',
  data:[{id:1,book:'FanDuel',betUrl:'https://sportsbook.fanduel.com/addToBetslip?marketId=42&selectionId=7',
    quotes:[{book:'DraftKings',betUrl:'https://sportsbook.draftkings.com/slip/selection-8'}]}],
  arbs:[{id:2,left:'FanDuel',right:'DraftKings',betUrl1:'https://sportsbook.fanduel.com/slip/left',betUrl2:'https://sportsbook.draftkings.com/slip/right'}],
});
vm.runInContext(links, context);
vm.runInContext(app.slice(app.indexOf('function openBet(')).split(/(?:async )?function track\(/)[0], context);
vm.runInContext(app.slice(app.indexOf('function arbBet('), app.indexOf('function builderSource(')), context);
vm.runInContext("openBet(1,'FanDuel')",context);
assert.equal(opened.at(-1)[0],context.data[0].betUrl);
assert.deepEqual(opened.at(-1).slice(1),['_blank','noopener,noreferrer']);
vm.runInContext("openBet(1,'DraftKings','+125')",context);
assert.equal(opened.at(-1)[0],context.data[0].quotes[0].betUrl,'Comparison opens its own book selection');
vm.runInContext("openBet(1,'BetMGM')",context);
assert.equal(opened.at(-1)[0],'https://sports.betmgm.com/','Missing selection goes to the selected sportsbook');
vm.runInContext("data[0].betUrl='javascript:alert(1)';openBet(1,'FanDuel')",context);
assert.equal(opened.at(-1)[0],'https://sportsbook.fanduel.com/');
vm.runInContext("arbBet(2,'b')",context);
assert.equal(opened.at(-1)[0],context.arbs[0].betUrl2,'Arbitrage uses the selected side');
vm.runInContext("arbBet(2,'a','BetMGM','+130')",context);
assert.equal(opened.at(-1)[0],'https://sports.betmgm.com/','Never borrow a different book or side link');
for (const url of ['http://book.example/','javascript:alert(1)','https://user:secret@book.example/','https://[']) {
  context.candidate=url;
  assert.equal(vm.runInContext('safeBetURL(candidate)',context),null);
}
vm.runInContext(fs.readFileSync(new URL('../web/book-catalog.js',import.meta.url),'utf8'),context);
const missing=vm.runInContext('Object.keys(bookCatalog).filter(book=>!sportsbookURL(book))',context);
assert.deepEqual(Array.from(missing),[],'Every listed book has a site fallback');
assert.ok(app.includes("?'Place bet':'View bet'"));

const fixtures = [{id:'link-test',book:'FanDuel',league:'NBA',market:'player_points',wager_display:'Player Over 20.5',
  odds:2.2,fair_prob:.55,bet_link:{status:'full_support',url:'https://sportsbook.fanduel.com/slip/7?x=1&y=2'},
  other_books:[{book:'DraftKings',odds:2.1,bet_link:{status:'provided',url:'https://sportsbook.draftkings.com/slip/8'}}]},
  {id:'event',book:'BetMGM',league:'NBA',odds:2.2,bet_link:{status:'event_support',url:'https://sports.betmgm.com/event/1'}},
  {id:'gambly',book:'FanDuel',league:'NBA',odds:2.2,bet_link:{status:'provided',url:'https://www.gambly.com/deeplink/odds/7/8/20.5?utm_campaign=old&x=1'}},
  {id:'partial',book:'BetMGM',league:'NBA',odds:2.2,bet_link:{status:'partial_support',url:'https://sports.betmgm.com/partial'}},
  {id:'app-only',book:'Courtside',league:'NBA',odds:2.2,bet_link:{provider:'propline',status:'event_support',app_url:'courtside://fixture/abc'}},
  {id:'wrong-app',book:'FanDuel',league:'NBA',odds:2.2,bet_link:{provider:'propline',status:'event_support',app_url:'courtside://fixture/abc'}},
  {id:'unsafe',book:'BetMGM',league:'NBA',odds:2.2,bet_link:{url:'javascript:alert(1)'}}];
const env={LAYERBASE_REST_URL:'https://feed.invalid',LAYERBASE_REST_TOKEN:'test'};
const feed=async (_url,options)=>{const [command,key]=JSON.parse(options.body);return Response.json({result:command==='TYPE'?'string':JSON.stringify({opportunities:key==='EV'?fixtures:[]})})};
let headers={};
if(fs.existsSync(new URL('./firebase-fixture.mjs',import.meta.url))){
  const auth=await import('./firebase-fixture.mjs');Object.assign(env,auth.env);const token=auth.tokenFor();
  headers={authorization:`Bearer ${token}`};globalThis.fetch=auth.firebaseMock({token,feed});
}else globalThis.fetch=feed;
const result=await worker.fetch(new Request('https://test.invalid/api/feeds',{headers}),env);
assert.equal(result.status,200);
const payload=await result.json(),row=payload.ev.find(d=>d.sourceId==='link-test');
assert.equal(row.betUrl,fixtures[0].bet_link.url);
assert.equal(row.quotes.find(q=>q.book==='DraftKings').betUrl,fixtures[0].other_books[0].bet_link.url);
assert.equal(payload.ev.find(d=>d.sourceId==='event').betUrl,'https://sports.betmgm.com/event/1');
assert.equal(payload.ev.find(d=>d.sourceId==='unsafe').betUrl,null);
console.log('Bet links passed: direct handoff, sportsbook fallback, exact book/side, safe URLs, feed propagation, all catalog destinations.');

const trackedURL=new URL(payload.ev.find(d=>d.sourceId==='gambly').betUrl);
assert.deepEqual(trackedURL.searchParams.getAll('utm_campaign'),['sharpedge']);
assert.equal(trackedURL.pathname,'/deeplink/odds/7/8/20.5');
assert.equal(trackedURL.searchParams.get('x'),'1');
assert.equal(payload.ev.find(d=>d.sourceId==='partial').betUrl,null);

const court=payload.ev.find(d=>d.sourceId==='app-only');
assert.equal(court.betUrl,null);
assert.equal(court.appUrl,'courtside://fixture/abc');
assert.equal(payload.ev.find(d=>d.sourceId==='wrong-app').appUrl,null);
const navigated=[];
context.window.location={assign:url=>navigated.push(url)};
context.navigator={userAgent:'iPhone'};
context.data[0].betUrl='https://sportsbook.fanduel.com/event/1';
context.data[0].appUrl='https://mobile.fanduel.com/event/1';
vm.runInContext("openBet(1,'FanDuel')",context);
assert.equal(navigated.at(-1),'https://mobile.fanduel.com/event/1');
vm.runInContext("handoffBet('Courtside',null,'courtside://fixture/abc')",context);
assert.equal(navigated.at(-1),'courtside://fixture/abc');
context.navigator={userAgent:'Windows'};
vm.runInContext("handoffBet('Courtside',null,'courtside://fixture/abc')",context);
assert.equal(opened.at(-1)[0],'https://www.courtside.app/');
assert.equal(vm.runInContext("safeAppURL('courtside://fixture/abc','FanDuel')",context),null);
assert.equal(vm.runInContext("safeAppURL('javascript:alert(1)','Courtside')",context),null);
console.log('App links passed: mobile preference, Courtside native link, desktop web fallback, provider/book isolation.');
