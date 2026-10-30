// Generated asset map is inserted by scripts/build.mjs. Credentials exist only in env.
import { AuthError, firebaseConfig, sessionCookie, sameOrigin, authenticate, membershipFor, publicAccount, authorizeFeed, PAID_PLANS } from './auth.js';
const assets = __ASSETS__;
const headers = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };
const states = JSON.parse(assets['data/state-platform-filter-2026-10-26.json'].text).states;
const stateNames = Object.fromEntries(states.map(s => [s.state, s.state_name]));
const aliases = {
  'Underdog Fantasy': "Underdog Pick'em", 'Underdog': "Underdog Pick'em",
  'PrizePicks': 'PrizePicks Player Picks', 'Hard Rock': 'Hard Rock Bet',
  'DraftKings': 'DraftKings Sportsbook', 'FanDuel': 'FanDuel Sportsbook',
  'BetMGM': 'BetMGM Sportsbook', 'Fanatics': 'Fanatics Sportsbook',
  'Caesars': 'Caesars Sportsbook', 'Bet365': 'bet365 Sportsbook',
  'theScore Bet': 'theScore Bet', 'Polymarket US': 'Polymarket US Sports',
  'Kalshi': 'Kalshi Sports'
};
const visible = new Set(['Y', 'U', 'C', 'L']);
const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[ch]);
// The existing prototype also interpolates feed text into inline handlers. Keep
// untrusted provider strings out of HTML and JavaScript syntax until that UI is
// migrated to DOM-bound event listeners.
const clean = value => String(value ?? '').replace(/[<>&"'`]/g, '').slice(0, 300);
const canonicalBook = value => { const name = clean(value); return name === 'NoVig' ? 'Novig' : name === 'Underdog Fantasy' ? 'Underdog' : name; };
const marketLabels = {
  moneyline:'Moneyline', spreads:'Spread', player_points:'points', player_assists:'assists', player_rebounds:'rebounds',
  player_threes:'three-pointers', player_goals:'goals', player_shots_on_goal:'shots on goal', player_blocked_shots:'blocked shots',
  player_power_play_points:'power-play points', goalie_saves:'saves', player_receptions:'receptions',
  player_reception_yds:'receiving yards', player_pass_yds:'passing yards', player_rush_yds:'rushing yards',
  player_pass_tds:'passing touchdowns', player_anytime_td:'touchdowns', player_rush_attempts:'rush attempts',
  player_pass_completions:'pass completions', batter_home_runs:'home runs', batter_total_bases:'total bases',
  batter_hits:'hits', batter_rbis:'RBIs', batter_hits_runs_rbis:'hits + runs + RBIs', batter_stolen_bases:'stolen bases',
  batter_runs_scored:'runs scored', pitcher_earned_runs:'earned runs', pitcher_outs:'pitcher outs',
  pitcher_hits_allowed:'hits allowed', pitcher_strikeouts:'strikeouts'
};
function marketLabel(value) {
  const key = String(value ?? '').replace(/_alternate$/, '');
  return marketLabels[key] ?? clean(key.replace(/^(player|batter|pitcher|goalie)_/, '').replace(/_/g, ' '));
}
const number = value => { const n = Number(value); return Number.isFinite(n) ? n : null; };
function decimal(value) {
  if (value == null) return null;
  const n = Number(String(value).replace(/[−–]/g, '-'));
  if (!Number.isFinite(n) || n === 0) return null;
  if (n >= 1.01) return n;
  if (n > 0) return null;
  return n <= -100 ? 1 + 100 / -n : null;
}
function decimalOdds(value) {
  if (value == null) return null;
  const raw = String(value).replace(/[−–]/g, '-');
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  if (raw.startsWith('+') || n <= -100) return n > 0 ? 1 + n / 100 : 1 + 100 / -n;
  return n > 1 ? n : null;
}
function american(d) {
  if (!d || d <= 1) return '—';
  const n = d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1));
  return n > 0 ? '+' + n : String(n);
}
function probability(value) {
  const n = number(value);
  return n == null || n <= 0 ? null : n > 1 ? n <= 100 ? n / 100 : null : n;
}
function suppliedKelly(row) {
  const fraction = number(row.kelly_fraction ?? row.full_kelly_fraction);
  if (fraction != null) return Math.max(0, Math.min(1, fraction));
  const pct = number(row.kelly_pct ?? row.kelly_percentage);
  if (pct != null) return Math.max(0, Math.min(1, pct / 100));
  const raw = number(row.kelly);
  return raw == null ? null : Math.max(0, Math.min(1, raw > 1 ? raw / 100 : raw));
}
function parse(value) {
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { return value; }
}
function unwrap(response) {
  let value = response;
  for (let i = 0; i < 3 && value && typeof value === 'object'; i++) {
    if ('result' in value) value = value.result;
    else if ('rows' in value && Array.isArray(value.rows)) value = value.rows.length === 1 && value.rows[0].length === 1 ? value.rows[0][0] : value.rows;
    else break;
  }
  return parse(value);
}
function flatten(value, inherited = {}, result = []) {
  value = parse(value);
  if (result.length >= 3000 || value == null) return result;
  if (Array.isArray(value)) {
    // HGETALL may return alternating field/value entries.
    if (value.length && value.length % 2 === 0 && value.every((v, i) => i % 2 === 0 ? typeof v === 'string' && !v.startsWith('{') : true)) {
      for (let i = 0; i < value.length; i += 2) flatten(value[i + 1], { ...inherited, source: value[i] }, result);
    } else for (const item of value) flatten(item, inherited, result);
  } else if (typeof value === 'object') {
    if (Array.isArray(value.opportunities)) {
      for (const item of value.opportunities) flatten(item, { ...inherited, league: value.league ?? inherited.league, market: value.market ?? inherited.market, updated_at: value.updated_at ?? inherited.updated_at }, result);
    } else if ('event_id' in value || 'book' in value || 'book1' in value || 'wager_display' in value) result.push({ ...inherited, ...value });
    else for (const [field, item] of Object.entries(value)) flatten(item, { ...inherited, source: field }, result);
  }
  return result;
}
function normalizeEv(row, id) {
  const offered = decimalOdds(row.odds ?? row.best_odds ?? row.odds_decimal ?? row.decimal_odds ?? row.price);
  const p = probability(row.fair_probability ?? row.model_probability ?? row.fair_prob ?? row.win_probability ?? row.true_probability)
    ?? (decimalOdds(row.fair_odds) ? 1 / decimalOdds(row.fair_odds) : null);
  const provided = suppliedKelly(row);
  const fullKelly = provided ?? (p && offered ? Math.max(0, Math.min(1, (p * offered - 1) / (offered - 1))) : null);
  const evValue = number(row.ev_pct ?? row.ev_percentage ?? row.expected_value_pct ?? row.ev ?? row.expected_value);
  const ev = evValue ?? (p && offered ? (p * offered - 1) * 100 : 0);
  const display = clean(row.wager_display ?? row.selection ?? row.bet ?? row.side ?? 'Selection');
  const label = marketLabel(row.market);
  const bet = /\b(?:Over|Under)\s+\d/i.test(display) && label && !display.toLowerCase().includes(label.toLowerCase()) ? `${display} ${label}` : display;
  const book = canonicalBook(row.book ?? row.sportsbook ?? row.app ?? 'Unknown');
  const quotes = [{ book, odds: offered }, ...(Array.isArray(row.other_books) ? row.other_books.map(q => ({ book: canonicalBook(q.book), odds: decimalOdds(q.odds) })) : [])]
    .filter(q => q.book && q.odds).sort((a, b) => b.odds - a.odds)
    .map(q => ({ book: q.book, odds: american(q.odds) }));
  return { id, sourceId: row.id ?? null, ev, kellyFull: fullKelly, modelP: p, name: clean(row.player ?? display.split(/\s+(?:Over|Under)\s/i)[0] ?? ''), bet, game: clean(row.match ?? row.event ?? ''), league: clean(row.league ?? row.sport ?? ''), book, odds: offered ? american(offered) : '—', fair: p ? american(1 / p) : '—', quotes, time: clean(row.time ?? ''), live: Boolean(row.live ?? row.is_live ?? row.in_play), market: clean(row.market ?? ''), updatedAt: row.updated_at ?? null };
}
function normalizeArb(row, id) {
  const d1 = decimalOdds(row.odds1), d2 = decimalOdds(row.odds2);
  if (!d1 || !d2) return null;
  const market = clean(row.market ?? '');
  const prop = row.line == null ? marketLabel(market) : `${clean(row.line)} ${marketLabel(market)}`;
  return { id, sourceId: row.id ?? null, name: clean(row.player ?? row.side1 ?? 'Market'), prop, market, game: clean(row.match ?? ''), league: clean(row.league ?? row.sport ?? ''), left: canonicalBook(row.book1 ?? ''), right: canonicalBook(row.book2 ?? ''), side1: clean(row.side1 ?? 'Side A'), side2: clean(row.side2 ?? 'Side B'), line1:row.line1, line2:row.line2, a: american(d1), b: american(d2), ev: number(row.arb_margin) ?? (1 / (1 / d1 + 1 / d2) - 1) * 100, kellyFull: suppliedKelly(row), time: clean(row.time ?? ''), updatedAt: row.updated_at ?? null };
}
function permitted(book, state) {
  if (!state) return true;
  if (book === 'Kalshi' || book === 'Polymarket US') return true;
  const operator = aliases[book] ?? book;
  const entry = states.find(s => s.state === state)?.display_products.find(p => p.operator.toLowerCase() === operator.toLowerCase());
  return !!entry && visible.has(entry.status) && !entry.requires_premises;
}
async function query(env, command) {
  if (!env.LAYERBASE_REST_URL || !env.LAYERBASE_REST_TOKEN) throw new Error('Feed configuration missing');
  const response = await fetch(env.LAYERBASE_REST_URL, {
    method: 'POST', headers: { Authorization: `Bearer ${env.LAYERBASE_REST_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(command), cache: 'no-store', signal: AbortSignal.timeout(12000)
  });
  if (!response.ok) {
    const detail = (await response.text()).replace(/[^a-zA-Z0-9 _.,:()/-]/g, '').slice(0, 180);
    throw new Error(`Feed ${command[0]} failed (${response.status}): ${detail}`);
  }
  return unwrap(await response.json());
}
async function readKey(env, key) {
  const kind = String(await query(env, ['TYPE', key])).toLowerCase();
  if (kind.includes('none')) return [];
  if (kind.includes('hash')) return flatten(await query(env, ['HGETALL', key]));
  if (kind.includes('list')) return flatten(await query(env, ['LRANGE', key, '0', '2999']));
  if (kind.includes('zset')) return flatten(await query(env, ['ZRANGE', key, '0', '2999']));
  return flatten(await query(env, ['GET', key]));
}
async function loadFeed(env) {
  const [evRows, arbRows] = await Promise.all([readKey(env, 'EV'), readKey(env, 'arbitrage')]);
  const ev = evRows.map(normalizeEv).filter(d => d.odds !== '—').sort((a, b) => (b.kellyFull ?? -1) - (a.kellyFull ?? -1) || b.ev - a.ev);
  const arbs = arbRows.map(normalizeArb).filter(Boolean).sort((a, b) => (b.kellyFull ?? -1) - (a.kellyFull ?? -1) || b.ev - a.ev);
  return { ev, arbs, fetchedAt: new Date().toISOString(), status:'ok' };
}
function eventTime(value, timezone = 'UTC') {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return clean(value || 'Time TBD');
  try {
    const parts = new Intl.DateTimeFormat('en-US', { hour:'numeric', minute:'2-digit', hour12:true, timeZoneName:'short', timeZone:timezone }).formatToParts(date);
    const part = type => parts.find(p => p.type === type)?.value ?? '';
    return `${part('hour')}:${part('minute')} ${part('dayPeriod')} ${part('timeZoneName')}`.trim();
  } catch { return eventTime(value, 'UTC'); }
}
function renderServerPage(route, feed, state, timezone) {
  const rows = route !== 'arbitrage' ? feed.ev.filter(d => permitted(d.book, state) && (route !== 'parlay' || !d.live)) : feed.arbs.filter(d => permitted(d.left, state) && permitted(d.right, state));
  const label = route === 'parlay' ? 'Parlay Builder' : route === 'ev' ? 'Positive EV bets' : 'Arbitrage';
  const items = route !== 'arbitrage' ? rows.map(d => `<tr><td class="ev">${safe(d.kellyFull == null ? '—' : (d.kellyFull * 25).toFixed(2) + '%')}</td><td><strong>${safe(d.bet)}</strong><small>${safe(d.name)}</small></td><td>${safe(d.game)}<small>${safe(d.league)} · ${safe(eventTime(d.time, timezone))}</small></td><td>${safe(d.book)}</td><td class="odds-cell"><strong class="best-odds">${safe(d.odds)}</strong></td><td class="ev">${safe(d.ev.toFixed(2))}%</td></tr>`)
    : rows.map(d => `<tr><td>${safe(d.left)} <strong>${safe(d.a)}</strong></td><td>${safe(d.side1)}</td><td>${safe(d.game)}<small>${safe(d.prop)} · ${safe(d.league)} · ${safe(eventTime(d.time, timezone))}</small></td><td>${safe(d.side2)}</td><td>${safe(d.right)} <strong>${safe(d.b)}</strong></td><td class="ev">${safe(d.ev.toFixed(2))}%</td></tr>`);
  const headings = route !== 'arbitrage' ? '<th>¼ Kelly ↓</th><th>Selection</th><th>Event</th><th>Book</th><th>Best odds</th><th>EV</th>' : '<th>Side A</th><th>Selection</th><th>Event</th><th>Opposite</th><th>Side B</th><th>Return</th>';
  return `<div class="demo">${feed.status === 'error' ? 'FEED TEMPORARILY UNAVAILABLE' : `LIVE FEED · Updated ${safe(feed.fetchedAt)}`}</div><div class="page"><div class="eyebrow">SHARPEDGE / LIVE DATA</div><div class="page-title"><div><h1>${label}</h1><p>Data from the latest market snapshot.</p></div></div><div class="preview table-wrap">${items.length ? `<table class="feed-table"><thead><tr>${headings}</tr></thead><tbody>${items.join('')}</tbody></table>` : `<div class="empty"><h2>${feed.status === 'error' ? 'Feed temporarily unavailable.' : 'No opportunities right now.'}</h2><p>Check back later.</p></div>`}</div></div>`;
}
function pageHtml(route, feed, state, timezone, account = null) {
  let html = assets['index.html'].text;
  html = html.replace(/href="#(ev|arbitrage|parlay)"/g, (_, p) => `href="/${p}"`).replace(/href="#(home|pricing|analysis|coverage|privacy|terms|cookies|billing|accessibility|copyright|responsible)"/g, (_, p) => `href="/#${p}"`);
  html = html.replace('</head>', `<script>window.__SHARPEDGE_SERVER__=true;window.__SHARPEDGE_ACCOUNT__=${JSON.stringify(account).replace(/</g, '\\u003c')};</script></head>`);
  if (feed && (route === 'ev' || route === 'arbitrage' || route === 'parlay')) {
    html = html.replace('<main id="app" tabindex="-1"></main>', `<main id="app" tabindex="-1">${renderServerPage(route, feed, state, timezone)}</main>`);
    const boot = JSON.stringify(feed).replace(/</g, '\\u003c');
    html = html.replace('</head>', `<script>window.__SHARPEDGE_FEED__=${boot};</script></head>`);
  }
  return html;
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url), path = url.pathname.replace(/^\//, '');
    const json = (body, status = 200, extra = {}) => Response.json(body, { status, headers:{...headers, ...extra} });
    const page = (route, feed, account) => new Response(pageHtml(route, feed, '', 'UTC', account), {headers:{...headers, 'content-type':'text/html; charset=utf-8'}});
    try {
      if (path === 'api/auth/config') {
        if (request.method !== 'GET') return json({error:'Method not allowed'}, 405, {allow:'GET'});
        return json(firebaseConfig(env));
      }
      if (path === 'api/session') {
        if (!['POST', 'DELETE'].includes(request.method)) return json({error:'Method not allowed'}, 405, {allow:'POST, DELETE'});
        sameOrigin(request);
        if (request.method === 'DELETE') return json({ok:true}, 200, {'set-cookie':sessionCookie()});
        if (!request.headers.has('authorization')) throw new AuthError(401, 'Sign in to continue.');
        const user = await authenticate(request, env), membership = await membershipFor(user, env);
        return json(publicAccount(user, membership), 200, {'set-cookie':sessionCookie(user.token, Math.min(3600, user.expiresAt - Math.floor(Date.now() / 1000)))});
      }
      if (path === 'api/account') {
        if (request.method !== 'GET') return json({error:'Method not allowed'}, 405, {allow:'GET'});
        const user = await authenticate(request, env);
        return json(publicAccount(user, await membershipFor(user, env)));
      }
      if (['api/feeds', 'ev', 'arbitrage', 'parlay', 'analysis'].includes(path)) {
        if (request.method !== 'GET') return json({error:'Method not allowed'}, 405, {allow:'GET'});
        const user = await authenticate(request, env), membership = await membershipFor(user, env), account = publicAccount(user, membership), plan = membership.plan;
        if (path === 'analysis') return page(path, null, account);
        if (!PAID_PLANS.has(plan)) {
          if (path === 'api/feeds') return json({error:'An unexpired membership is required to view market data.', account}, 403);
          return page(path, null, account);
        }
        if ((path === 'arbitrage' && !['plus', 'platinum'].includes(plan)) || (path === 'parlay' && !['fantasy', 'fantasyplus', 'platinum'].includes(plan))) return page(path, null, account);
        try {
          const feed = authorizeFeed(await loadFeed(env), plan);
          if (path === 'api/feeds') return json(feed);
          const cookie = request.headers.get('cookie');
          const region = cookie?.match(/(?:^|;\s*)se-region=([A-Z]{2})/)?.[1];
          const state = stateNames[region] ? region : '';
          let timezone = 'UTC';
          try { timezone = decodeURIComponent(cookie?.match(/(?:^|;\s*)se-timezone=([^;]+)/)?.[1] ?? 'UTC').slice(0, 80); } catch {}
          return new Response(pageHtml(path, feed, state, timezone, account), { headers: { ...headers, 'content-type':'text/html; charset=utf-8' } });
        } catch (error) {
          console.error('SharpEdge feed query:', error instanceof Error ? error.message : 'Unknown error');
          // Do not expose credentials, provider responses, or internal errors to visitors.
          if (path === 'api/feeds') return json({error:'Feed temporarily unavailable'}, 503);
          return page(path, {ev:[], arbs:[], fetchedAt:'Unavailable', status:'error'}, account);
        }
      }
    } catch (error) {
      const status = error instanceof AuthError ? error.status : 503;
      if (!path.startsWith('api/') && status === 401) return new Response(null, {status:302, headers:{...headers, location:'/signin?next='+encodeURIComponent(url.pathname + url.search), 'set-cookie':sessionCookie()}});
      if (path.startsWith('api/')) return json({error:error instanceof AuthError ? error.message : 'Your account is temporarily unavailable.', code:error instanceof AuthError ? error.code : 'AUTH_UNAVAILABLE'}, status);
      return page('signin');
    }
    if (path === 'signin') return page('signin');
    if (path.startsWith('api/')) return json({error:'Not found'}, 404);
    const name = path || 'index.html', asset = assets[name];
    if (name === 'index.html') return new Response(pageHtml('home'), { headers: { ...headers, 'content-type':'text/html; charset=utf-8' } });
    if (!asset || name.startsWith('data/')) return new Response('Not found', { status:404 });
    return new Response(asset.text ?? Uint8Array.from(atob(asset.base64), c => c.charCodeAt(0)), { headers: { ...headers, 'content-type': asset.type } });
  }
};
