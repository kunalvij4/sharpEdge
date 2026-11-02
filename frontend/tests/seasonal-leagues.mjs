import assert from 'node:assert/strict';
import fs from 'node:fs';
import worker from '../dist/server/index.js';
import {env, tokenFor, firebaseMock} from './firebase-fixture.mjs';

const token = tokenFor();
const ev = ['MLB', 'NCAAB'].map(league => ({
  id:`${league}-ev`, league, book:'FanDuel', wager_display:'Home ML', market:'moneyline',
  odds:2.1, model_probability:.55, match:`${league} sample matchup`
}));
const arbs = ['MLB', 'NCAAB'].map(league => ({
  id:`${league}-arb`, league, book1:'FanDuel', book2:'DraftKings', market:'moneyline',
  odds1:2.1, odds2:2.1, side1:'Home', side2:'Away', match:`${league} sample matchup`
}));
globalThis.fetch = firebaseMock({token, feed:async (_url, options) => {
  const [command, key] = JSON.parse(options.body);
  return Response.json({result:command === 'TYPE' ? 'string' : JSON.stringify({opportunities:key === 'EV' ? ev : arbs})});
}});
const headers = {authorization:`Bearer ${token}`};
const response = await worker.fetch(new Request('https://test.invalid/api/feeds', {headers}), env);
assert.equal(response.status, 200);
const feed = await response.json();
assert.deepEqual(feed.ev.map(row => row.league), ['NCAAB']);
assert.deepEqual(feed.arbs.map(row => row.league), ['NCAAB']);
for (const route of ['ev', 'arbitrage', 'parlay']) {
  const page = await worker.fetch(new Request(`https://test.invalid/${route}`, {headers}), env);
  const html = await page.text();
  assert.equal(page.status, 200);
  assert.match(html, /NCAAB sample matchup/);
  assert.doesNotMatch(html, /MLB sample matchup/);
}
const app = fs.readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
assert.match(app, /leagues=\['All leagues','NBA','NFL','NHL','NCAAF','NCAAB'\]/);
assert.match(app, /const words=\['NBA','NFL','NHL','NCAAF','NCAAB'\]/);
assert.doesNotMatch(app, /league:'MLB'/);
console.log('Seasonal league tests passed: NCAAB feed, filters and landing content; cached MLB rows hidden.');
