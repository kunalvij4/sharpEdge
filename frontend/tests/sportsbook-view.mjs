import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import worker from '../dist/server/index.js';

const app = fs.readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const compliance = fs.readFileSync(new URL('../web/compliance.js', import.meta.url), 'utf8');
const projections = [
  {id:1, book:'FanDuel', league:'NBA', live:false, ev:2, quotes:[{book:'FanDuel', odds:'-110'}, {book:'PrizePicks', odds:'+100'}, {book:'Underdog', odds:'-105'}, {book:'DraftKings Pick6', odds:'+100'}]},
  {id:2, book:'PrizePicks', league:'NBA', live:false, ev:3, quotes:[{book:'PrizePicks', odds:'+100'}, {book:'FanDuel', odds:'-110'}]},
  {id:3, book:'DraftKings Pick6', league:'NBA', live:false, ev:2, quotes:[{book:'DraftKings Pick6', odds:'+100'}, {book:'FanDuel', odds:'-110'}]},
];
const context = vm.createContext({
  localStorage:{getItem:()=>''}, platformFilter:{states:{}}, data:projections,
  window:{__SHARPEDGE_SERVER__:true}, plan:'platinum', market:'sportsbook', mode:'prematch',
  book:'All books', league:'All leagues', empty:false, books:['All books','FanDuel','PrizePicks','Underdog','DraftKings Pick6'],
  names:{platinum:'Platinum'}, can:()=>true, head:()=>'', toolbar:()=>'', metric:()=>'', bankrollControl:()=>'',
  evTable:rows=>JSON.stringify(rows.map(row=>row.book)), route:()=> 'ev', badge:book=>book,
  decimal:value=>Number(value)>0?1+Number(value)/100:1+100/Math.abs(Number(value)),
});
vm.runInContext(compliance.slice(0, compliance.indexOf('function regionEmpty(')), context);
for (const name of ['filtered', 'evPage', 'evQuotes', 'filterOptions', 'quoteCards']) {
  const start = app.indexOf(`function ${name}(`);
  const end = app.indexOf('function ', start + 9);
  vm.runInContext(app.slice(start, end), context);
}
assert.doesNotMatch(vm.runInContext('evPage()', context), /PrizePicks/);
assert.doesNotMatch(vm.runInContext('evPage()', context), /DraftKings Pick6/);
assert.doesNotMatch(vm.runInContext("filterOptions('book','')", context), /PrizePicks/);
assert.doesNotMatch(vm.runInContext("filterOptions('book','')", context), /DraftKings Pick6/);
assert.deepEqual(Array.from(vm.runInContext('evQuotes(1)', context), row=>row.book), ['FanDuel'], 'Sportsbook comparisons exclude fantasy app prices');
assert.deepEqual(Array.from(vm.runInContext('evQuotes(1,false)', context), row=>row.book), ['FanDuel'], 'Showing other regions must not reintroduce fantasy prices');
vm.runInContext("market='fantasy'", context);
assert.match(vm.runInContext('evPage()', context), /PrizePicks/);
assert.match(vm.runInContext("filterOptions('book','')", context), /PrizePicks/);
assert.match(vm.runInContext('evPage()', context), /DraftKings Pick6/);
assert.match(vm.runInContext("filterOptions('book','')", context), /DraftKings Pick6/);
assert.deepEqual(Array.from(vm.runInContext('evQuotes(2)', context), row=>row.book), ['FanDuel'], 'Expanded fantasy bets skip fantasy apps in fixed-price comparisons');
assert.deepEqual(Array.from(vm.runInContext('evQuotes(3)', context), row=>row.book), ['FanDuel']);
assert.doesNotMatch(vm.runInContext("quoteCards(data[0].quotes,'ev',1)",context), /PrizePicks|Underdog|DraftKings Pick6/, 'Expanded quote cards contain sportsbook prices only');
vm.runInContext(app.slice(app.indexOf('function oddsPanel('),app.indexOf('// Additional illustrative')),context);
assert.match(vm.runInContext("oddsPanel('ev',3)",context), /No comparable fixed odds/);
const logos=fs.readFileSync(new URL('../web/book-catalog.js',import.meta.url),'utf8');
assert.match(logos, /"DraftKings Pick6":"dk-pick6.png"/);
assert.ok(fs.statSync(new URL('../web/assets/logos/dk-pick6.png',import.meta.url)).size>100);

const fixtures = projections.map(row=>({
  id:`${row.book}-source`, book:row.book, league:'NBA', market:'player_points',
  player:`${row.book} Player`, wager_display:'Over 20.5', odds:2, model_probability:.6,
  match:'Away vs Home',
}));
const env = {LAYERBASE_REST_URL:'https://feed.invalid', LAYERBASE_REST_TOKEN:'test-only'};
const feedMock = async (_url, options) => {
  const [command, key] = JSON.parse(options.body);
  return Response.json({result:command === 'TYPE' ? 'string' : JSON.stringify({opportunities:key === 'EV' ? fixtures : []})});
};
let headers = {};
if (fs.existsSync(new URL('./firebase-fixture.mjs', import.meta.url))) {
  const auth = await import('./firebase-fixture.mjs');
  Object.assign(env, auth.env);
  const token = auth.tokenFor();
  headers = {authorization:`Bearer ${token}`};
  globalThis.fetch = auth.firebaseMock({token, feed:feedMock});
} else globalThis.fetch = feedMock;
const page = await worker.fetch(new Request('https://test.invalid/ev', {headers}), env);
assert.equal(page.status, 200);
const html = await page.text();
const initialRows = html.match(/<main id="app" tabindex="-1">([\s\S]*?)<\/main>/)?.[1];
assert.ok(initialRows);
assert.match(initialRows, /FanDuel/);
assert.doesNotMatch(initialRows, /PrizePicks/, 'Initial sportsbook rows exclude PrizePicks before client rendering');
assert.doesNotMatch(initialRows, /DraftKings Pick6/);
assert.match(html, /PrizePicks-source/, 'Fantasy data stays available for switching tabs');
const parlay = await worker.fetch(new Request('https://test.invalid/parlay', {headers}), env);
assert.match(await parlay.text(), /PrizePicks-source/, 'The fantasy builder keeps PrizePicks data');
console.log('Sportsbook view checks passed: rows, book filters, comparisons, initial rendering and fantasy availability.');
