// User-supplied state/platform display matrix, dated 2026-10-26.
const stateNames={AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',CO:'Colorado',CT:'Connecticut',DE:'Delaware',DC:'District of Columbia',FL:'Florida',GA:'Georgia',HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',MT:'Montana',NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming'};
// Product identity matters: a brand's sportsbook, fantasy and prediction markets
// are separate entries in the user-provided state/platform matrix.
const catalogProducts={
 DraftKings:'DraftKings Sportsbook',FanDuel:'FanDuel Sportsbook',BetMGM:'BetMGM Sportsbook',
 'Hard Rock':'Hard Rock Bet','Hard Rock Bet':'Hard Rock Bet',Fanatics:'Fanatics Sportsbook',
 BetRivers:'BetRivers Sportsbook',Bet365:'bet365 Sportsbook',Caesars:'Caesars Sportsbook',
 'theScore Bet':'theScore Bet','TheScore US':'theScore Bet',PrizePicks:'PrizePicks Player Picks',
 Underdog:"Underdog Pick'em",Fliff:'Fliff Cash',Kalshi:'Kalshi Sports',Novig:'Novig',
 'Polymarket US':'Polymarket US Sports',ProphetX:'ProphetX',ReBet:'Rebet',Thrillzz:'Thrillzz Sports'
};
const visibleStatuses=new Set(['Y','U','C','L']);
const nationwidePredictionMarkets=new Set(['Kalshi','Polymarket US']);
function availability(name,code=region){const product=catalogProducts[name];const row=product&&platformFilter.states[code]?.[product];return row?{product,status:row[0],category:row[1],description:row[2],requiresPremises:!!row[3],unverified:!!row[4],legalDispute:!!row[5]}:null}
let region=stateNames[localStorage.getItem('se-region')]?localStorage.getItem('se-region'):'';
function bookCategory(name){return nationwidePredictionMarkets.has(name)?'Prediction/exchange':availability(name)?.category||(['PrizePicks','Underdog'].includes(name)?'Fantasy player picks':'Sportsbook')}
function bookAllowed(name){if(!region||nationwidePredictionMarkets.has(name))return true;const entry=availability(name);return !!entry&&visibleStatuses.has(entry.status)}
function offerAllowed(d){if(!region)return !(d.book==='PrizePicks'&&['NCAAF','NCAAB'].includes(d.league));const entry=availability(d.book);return !!entry&&visibleStatuses.has(entry.status)&&!entry.requiresPremises&&!(d.book==='PrizePicks'&&['NCAAF','NCAAB'].includes(d.league))}
function regionEmpty(){if(window.__SHARPEDGE_SERVER__){const unavailable=window.__SHARPEDGE_FEED__?.status!=='ok';return '<div class="empty"><div class="symbol">⌖</div><h2>'+(unavailable?'Feed temporarily unavailable.':'No opportunities right now.')+'</h2><p>'+(unavailable?'The live feed could not be loaded. Try refreshing shortly.':'Nothing matches this view'+(region?' for '+stateNames[region]:'')+' at the moment. Check back later or adjust your filters.')+'</p><button onclick="refreshOdds(this)">Refresh odds ↻</button></div>'}return '<div class="empty"><div class="symbol">⌖</div><h2>No offers in this view right now.</h2><p>No matching sample opportunities are available'+(region?' for '+stateNames[region]:'')+'. Try a different view or check back later.</p><button onclick="book=\'All books\';league=\'All leagues\';render()">Reset filters →</button></div>'}
function coveragePage(){return '<div class="legal-page coverage-page"><div class="eyebrow">SHARPEDGE / STATE COVERAGE</div><h1>Books by state</h1><p class="legal-lead">Sportsbooks from the supplied state coverage file, plus prediction markets shown nationwide.</p><div class="coverage-grid">'+Object.entries(stateNames).sort((a,b)=>a[1].localeCompare(b[1])).map(([code,label])=>{const products=platformFilter.states[code]||{};const sportsbook=Object.entries(products).filter(([,v])=>v[1]==='Sportsbook'&&visibleStatuses.has(v[0])).map(([name,v])=>name+(v[0]==='Y'?'':v[0]==='U'?' (unverified)':v[0]==='C'?' (disputed)':' (in-person only)'));return '<section id="coverage-'+code+'"><h2>'+label+' <small>'+code+'</small></h2><p><b>Sportsbooks:</b> '+(sportsbook.join(' · ')||'None listed')+'</p><p><b>Prediction markets:</b> Kalshi · Polymarket US</p></section>'}).join('')+'</div><p class="mobile-note">Prediction markets are shown for discovery in every state; this does not confirm eligibility for every user or contract. Confirm availability with each operator. Polymarket US is distinct from the international Polymarket platform.</p></div>'}
function setRegion(code){region=stateNames[code]?code:'';if(region)localStorage.setItem('se-region',region);else localStorage.removeItem('se-region');document.cookie='se-region='+region+'; Path=/; SameSite=Lax';book='All books';league='All leagues';legs=[];payoutOverride=null;render();syncRegion()}
function syncRegion(){const selector=document.querySelector('#state-select');if(selector)selector.value=region}
function initRegion(){const selector=document.querySelector('#state-select');for(const [code,name] of Object.entries(stateNames).sort((a,b)=>a[1].localeCompare(b[1])))selector.add(new Option(name,code));syncRegion();if(!region&&!sessionStorage.getItem('se-location-attempted')){sessionStorage.setItem('se-location-attempted','1');setTimeout(()=>locateRegion(true),700)}}
function censusStateForCoordinates(longitude,latitude){return new Promise((resolve,reject)=>{
  const callback='sharpedgeGeo'+Math.random().toString(36).slice(2),script=document.createElement('script');
  const cleanup=()=>{clearTimeout(timer);delete window[callback];script.remove()};
  const timer=setTimeout(()=>{cleanup();reject(new Error('Geocoder timeout'))},9500);
  window[callback]=payload=>{cleanup();resolve(payload.result?.geographies?.States?.[0]?.STUSAB)};
  script.onerror=()=>{cleanup();reject(new Error('Geocoder unavailable'))};
  const params=new URLSearchParams({x:String(longitude),y:String(latitude),benchmark:'Public_AR_Current',vintage:'Current_Current',format:'jsonp',callback});
  script.src='https://geocoding.geo.census.gov/geocoder/geographies/coordinates?'+params;
  document.head.append(script);
})}
async function locateRegion(automatic=false){
 if(!navigator.geolocation){if(!automatic)notify('Location unavailable. Please select your state.');return}
 const button=document.querySelector('.locate-button');button?.setAttribute('aria-busy','true');
 navigator.geolocation.getCurrentPosition(async position=>{
   try{
     const found=await censusStateForCoordinates(position.coords.longitude,position.coords.latitude);
     if(!stateNames[found])throw new Error('Location outside supported states');
     setRegion(found);notify('Viewing '+stateNames[found]+' based on your location');
   }catch(e){notify('Could not determine your state. Select it manually.')}
   finally{button?.removeAttribute('aria-busy')}
 },()=>{button?.removeAttribute('aria-busy');if(!automatic)notify('Location was unavailable. Select a state manually.')},{enableHighAccuracy:false,timeout:9000,maximumAge:300000});
}
function privacyBanner(){if(localStorage.getItem('se-privacy-notice'))return;const el=document.querySelector('#privacy-banner');el.hidden=false;el.innerHTML='<div><strong>Privacy at SharpEdge</strong><p>SharpEdge uses Google sign-in and Firebase to store your profile, bankroll, bet journal and saved entry. Essential browser storage keeps your sign-in session, state selection and privacy preferences. It does not run advertising, analytics, pixels, session replay or non-essential cookies. If you use location, your browser asks permission and coordinates go to the U.S. Census geocoder to identify a state.</p><a href="#privacy">Privacy details</a> · <a href="#cookies">Cookie details</a></div><div class="privacy-actions"><button onclick="ackPrivacy()">Continue with essential storage</button><button onclick="openPrivacyChoices()">Privacy choices</button></div>'}
function ackPrivacy(){localStorage.setItem('se-privacy-notice','seen');document.querySelector('#privacy-banner').hidden=true}
function openPrivacyChoices(){const d=document.querySelector('#modal');d.innerHTML='<div class="eyebrow">PRIVACY CHOICES</div><h2>Your browser, your choices.</h2><p>Analytics, advertising pixels, chat recording and session replay are off and are not integrated in this prototype. Essential browser storage keeps your sign-in session, selected state and this notice preference. Your account profile, bankroll, bet journal and saved entry are stored in Firebase under your user ID.</p><p>You can sign out and clear site data in your browser settings. Clearing browser data does not delete your Firebase account or cloud records. We will ask for a new choice before adding optional tracking.</p><div class="actions"><button onclick="document.querySelector(\'#modal\').close()">Close</button><button class="primary" onclick="ackPrivacy();document.querySelector(\'#modal\').close()">Continue with essential storage</button></div>';d.showModal()}
function legalPage(kind){
 const sections={
 privacy:['Privacy Policy','What this prototype does with information',[
 ['Information stored here','Google sign-in creates a Firebase Authentication account. We store your Google display name, email address, profile photo URL and last sign-in time in a private Firestore profile. Your bankroll, bet journal and saved entry are stored under your Firebase user ID. State selection and privacy-notice preferences remain in browser storage. Payment collection and contact forms are not connected. Your browser and the hosting provider may process IP address and ordinary request logs to deliver this site.'],
 ['Location','If you permit browser location, precise coordinates are sent directly from your browser to the U.S. Census geocoding service to resolve a state. We save only the resulting state abbreviation locally; coordinates are not saved by SharpEdge. You can instead choose a state manually.'],
 ['Third parties and tracking','Google and Firebase process sign-in and account data to provide authentication and storage. This site also loads Google Fonts and the Firebase SDK from Google; your browser makes requests to those providers. Sportsbook marks are bundled assets. No analytics, ad pixels, session replay, chat widget, newsletter or optional tracking cookies are installed. Third-party sites opened from links have their own policies.'],
 ['Your choices','Use Privacy choices in the footer to review storage. Sign out to clear your active session. Clearing browser data removes local preferences but does not delete your cloud records or Google account. A support contact and account data deletion process still need to be supplied by the SharpEdge operator.']
 ]],
 terms:['Terms of Service','Preview terms for the design prototype',[
 ['What this service currently is','SharpEdge here is an interactive prototype with a public illustrative market preview and membership-controlled live market tools. Google sign-in authenticates users and Firebase stores their private account data. The site does not accept subscriptions, process payments, place wagers or provide verified sportsbook links. Displayed prices, fair probabilities, Kelly stakes and returns are examples, not current offers or guaranteed outcomes.'],
 ['Eligibility and use','The intended audience is adults 21 and older. Do not use this prototype to circumvent geographic, age or operator eligibility rules. Your state selection is an informational filter, not a location check. Always verify markets and eligibility directly with the operator.'],
 ['Intellectual property','SharpEdge design and original copy are reserved by their owner. Sportsbook names and marks belong to their respective owners; their appearance does not imply endorsement. Do not reproduce third-party marks without authorization.'],
 ['Production terms still needed','Before any paid launch, the operator must identify its legal entity, contact address, governing law, dispute process, liability language, subscription terms and applicable rights. This preview does not create a paid customer agreement.']
 ]],
 cookies:['Cookie & Tracking Policy','Essential storage, optional tracking off',[
 ['Current storage','SharpEdge uses Firebase session storage and a Secure, HttpOnly session cookie for sign-in. Local storage keeps your selected state and privacy notice; session storage records the one-time location attempt. Account records are stored in Firestore. It does not set advertising or analytics cookies. The hosting provider may use technically necessary delivery mechanisms.'],
 ['Analytics and ads','There are no Meta, Google or TikTok pixels, session-replay scripts, advertising identifiers or analytics tags in the current site. A future integration must be disclosed with a refreshed policy and appropriate choice before loading.'],
 ['Control','Use the footer Privacy choices link to review the current setup. Browser settings can clear local storage or block site data. The banner provides notice about essential storage and does not claim consent to future vendors.']
 ]],
 billing:['Subscriptions & Email','No checkout or marketing email in this prototype',[
 ['Monthly plan preview','Pricing displays $14.99 Gold, $19.99 Gold Plus, $29.99 Fantasy Package and $99.99 Platinum per month. Selecting a tier cannot grant paid access. Memberships are activated through a server-managed account record; checkout is not connected. No card is charged, no subscription begins and no sales tax is calculated here. Fantasy+ pricing is available only through a future sales process.'],
 ['Before paid launch','The actual checkout must show the full recurring price, billing interval, applicable tax, renewal terms, trial terms if any, and a working way to cancel. The operator must adopt and publish specific refund, effective cancellation and service-access policies before charging anyone.'],
 ['Commercial email','Google sign-in supplies your email address for account identification. This site does not send marketing messages. A future email program must identify the sender, use accurate subject lines, include a valid postal address and provide a working opt-out for commercial email.']
 ]],
 accessibility:['Accessibility Statement','Building for keyboard and assistive technology',[
 ['Approach','We aim to make SharpEdge usable with a keyboard, clear focus indicators, readable contrast, reduced-motion preferences and text alternatives for meaningful logos. We use WCAG 2.1 Level AA as a design target, but have not completed an independent conformance audit.'],
 ['Known limitations','Some prototype market tables scroll horizontally on small screens. Market access requires an authenticated account and a server-managed membership. If a control or page creates a barrier, please report the page, device, browser and issue once the operator publishes an accessibility contact channel.'],
 ['Feedback contact','A direct support email or feedback endpoint has not been connected yet. This must be supplied by the SharpEdge operator before customer launch.']
 ]],
 copyright:['Copyright & Takedown','Rights and submissions',[
 ['Original and third-party assets','© 2026 SharpEdge for original interface design and copy. Team, sportsbook and fantasy-app names and logos identify their owners; display here does not confer a license or endorsement. The site uses DM Sans and Manrope fonts delivered through Google Fonts. Asset rights should be reviewed before commercial launch.'],
 ['Copyright reports','This prototype does not accept public user-generated content. If uploads or public submissions are introduced, the operator must publish a designated takedown contact, a counter-notice process and, if seeking DMCA safe harbor, register an agent with the U.S. Copyright Office.'],
 ['Contact pending','No DMCA agent or copyright email has been designated for this prototype.']
 ]],
 responsible:['Responsible Play','Know the limits of a price estimate',[
 ['Age and location','This experience is designed for adults 21+. State availability is only a curated display filter and can be incomplete or out of date. Actual eligibility, location and permissible markets are determined by the licensed operator and applicable law.'],
 ['Risk','Positive expected value and Kelly-based stake estimates are model outputs, not profit guarantees. Full or fractional Kelly can still lose substantially when probabilities are wrong. Set limits and never stake money needed for essentials.'],
 ['Support','If gambling is causing harm, visit <a href="https://www.ncpgambling.org/help-treatment/" target="_blank" rel="noopener noreferrer">National Council on Problem Gambling support</a> for current help options.']
 ]]
 };
 const [title,lead,items]=sections[kind]||sections.privacy;
 return '<div class="legal-page"><div class="eyebrow">SHARPEDGE / SITE INFORMATION</div><h1>'+title+'</h1><p class="legal-lead">'+lead+'</p><div class="legal-status">Prototype disclosure · Updated October 26, 2026 · Requires operator and legal review before paid launch</div>'+items.map(([heading,body])=>'<section><h2>'+heading+'</h2><p>'+body+'</p></section>').join('')+(kind==='responsible'?'<section><h2>Coverage source</h2><p>See the <a href="#coverage">state/platform coverage matrix</a> for product-specific status. Confirm current eligibility with the operator and regulator.</p></section>':'')+'</div>'
}
document.addEventListener('DOMContentLoaded',()=>{initRegion();privacyBanner()});
