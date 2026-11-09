// Public sportsbook destinations. Selection URLs always take precedence.
const sportsbookSites = {
  'DraftKings':'https://sportsbook.draftkings.com/', 'FanDuel':'https://sportsbook.fanduel.com/',
  'BetMGM':'https://sports.betmgm.com/', 'Fanatics':'https://sportsbook.fanatics.com/',
  'Caesars':'https://www.caesars.com/sportsbook-and-casino', 'BetRivers':'https://www.betrivers.com/',
  'Hard Rock Bet':'https://www.hardrock.bet/sportsbook', 'Bet365':'https://www.bet365.com/',
  'theScore Bet':'https://www.thescore.bet/', 'TheScore CA':'https://www.thescore.bet/',
  'Novig':'https://www.novig.com/', 'ProphetX':'https://www.prophetx.co/',
  'Kalshi':'https://kalshi.com/', 'Polymarket US':'https://polymarket.us/', 'Polymarket':'https://polymarket.com/',
  'Fliff':'https://www.getfliff.com/', 'ReBet':'https://rebet.app/', 'Sportzino':'https://sportzino.com/',
  'Thrillzz':'https://www.thrillzz.com/', 'PrizePicks':'https://app.prizepicks.com/',
  'Courtside':'https://www.courtside.app/', 'Jouez Sport':'https://jeux.loro.ch/',
  'YouWager':'https://www.youwager.ag/', 'LV BET':'https://lvbet.pl/',
  'Underdog':'https://underdogfantasy.com/', 'DraftKings Pick6':'https://pick6.draftkings.com/',
  'Pinnacle':'https://www.pinnacle.com/', 'Bovada':'https://www.bovada.lv/',
  'BetOnline':'https://www.betonline.ag/', 'BookMaker.eu':'https://www.bookmaker.eu/',
  'BetUS':'https://www.betus.com.pa/', 'Betfair Exchange':'https://www.betfair.com/exchange/',
  'AdmiralBet DE':'https://www.admiralbet.de/', 'Bet25':'https://bet25.dk/', 'Bet99':'https://bet99.ca/',
  'Bet9ja':'https://www.bet9ja.com/', 'bet-at-home':'https://www.bet-at-home.com/',
  'Betclic PT':'https://www.betclic.pt/', 'Betika':'https://www.betika.com/', 'Betr AU':'https://betr.com.au/',
  'Betway':'https://www.betway.com/', 'Betway ZA':'https://www.betway.co.za/',
  'Codere MX':'https://www.codere.mx/', 'Danske Spil':'https://danskespil.dk/',
  'Fortuna CZ':'https://www.ifortuna.cz/', 'Heritage Sports':'https://www.heritagesports.eu/',
  'Jazz Sports':'https://www.jazzsports.ag/', 'Ladbrokes AU':'https://www.ladbrokes.com.au/',
  'LiveScore Bet':'https://www.livescorebet.com/', 'LowVig.ag':'https://www.lowvig.ag/',
  'Marca Apuestas':'https://www.marcaapuestas.es/', 'Meridianbet':'https://www.meridianbet.com/',
  'Mise-o-jeu':'https://miseojeu.lotoquebec.com/', 'NetBet RO':'https://www.netbet.ro/',
  'Norsk Tipping':'https://www.norsk-tipping.no/', 'Novibet':'https://www.novibet.com/',
  'OlyBet':'https://www.olybet.eu/', '1xBet':'https://www.1xbet.com/',
  'Paddy Power':'https://www.paddypower.com/', 'Palmerbet':'https://www.palmerbet.com/',
  'Pame Stoixima':'https://www.pamestoixima.gr/', 'Placard':'https://www.placard.pt/',
  'PlayAlberta':'https://www.playalberta.ca/', 'PlayNow':'https://www.playnow.com/',
  'PlayUp':'https://www.playup.com.au/', 'PMU':'https://www.pmu.fr/', 'PSK':'https://www.psk.hr/',
  'SBOBET':'https://www.sbobet.com/', 'Sportium':'https://www.sportium.es/',
  'SportyBet NG':'https://www.sportybet.com/ng/', 'Star Sports':'https://www.starsports.bet/',
  'Strendus':'https://www.strendus.com.mx/', 'STS':'https://www.sts.pl/',
  'Supabets':'https://www.supabets.co.za/', 'Superbet PL':'https://superbet.pl/',
  'Superbet RO':'https://superbet.ro/', 'SuperSport':'https://www.supersport.hr/', 'SX Bet':'https://sx.bet/',
  'Synot Tip':'https://www.synottip.cz/', 'TAB':'https://www.tab.com.au/', 'Te Apuesto':'https://www.teapuesto.pe/',
  'Tipico':'https://www.tipico.de/', 'tipp3':'https://www.tipp3.at/', 'Tippmix':'https://www.tippmixpro.hu/',
  'TonyBet':'https://www.tonybet.com/', 'Totalbet':'https://totalbet.pl/', 'TOTO':'https://www.toto.nl/',
  'Veikkaus':'https://www.veikkaus.fi/', 'Winamax':'https://www.winamax.fr/', 'Wplay':'https://www.wplay.co/',
};
function safeBetURL(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
function sportsbookURL(book, selectionURL = null) {
  const aliases = {'Hard Rock':'Hard Rock Bet', 'TheScore US':'theScore Bet', 'NoVig':'Novig',
    'Prophet Exchange':'ProphetX', 'ProphetXchange':'ProphetX', 'BetOnline.ag':'BetOnline',
    'Caesars Sportsbook':'Caesars', 'Underdog Fantasy':'Underdog', 'DK Pick6':'DraftKings Pick6'};
  return safeBetURL(selectionURL) ?? sportsbookSites[aliases[book] ?? book] ?? null;
}
function safeAppURL(value, book) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value), native = {Courtside:'courtside:', ProphetX:'prophetx:'};
    if (url.username || url.password) return null;
    return url.protocol === 'https:' || url.protocol === native[book] ? url.href : null;
  } catch { return null; }
}
function mobileBetDevice() {
  if (typeof navigator === 'undefined') return false;
  return navigator.userAgentData?.mobile ?? (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent ?? '')
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));
}
function handoffBet(book, selectionURL, appURL = null) {
  const app = mobileBetDevice() ? safeAppURL(appURL, book) : null;
  if (app) { window.location.assign(app); return; }
  const url = sportsbookURL(book, selectionURL);
  if (!url) { notify('Sportsbook website is not configured for this book.'); return; }
  window.open(url, '_blank', 'noopener,noreferrer');
}
