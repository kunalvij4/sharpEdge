# SharpEdge — full project

Exported source commit: 5847ec2c79e99113a5ddce9c9a06edfcf4b271da (published version 25).

## Run locally

Install Node.js 22 or newer. No third-party npm dependencies are required.

1. Extract this ZIP and open a terminal in the SharpEdge folder.
2. Copy `.env.example` to `.env` and enter your Layerbase REST endpoint and token. Keep this file private.
3. Run `node --env-file=.env scripts/dev.mjs`.
4. Open http://localhost:4173.

EV, arbitrage and parlay pages require Google sign-in and a server-managed membership with an unexpired `expiresAt` Firestore Timestamp before reading the `EV` and `arbitrage` Redis keys. Analysis requires sign-in and is available to free accounts. The browser refreshes the feed every five minutes and supports manual refresh. Missing credentials deny access and never fall back to demo opportunities.

Follow [AUTH-SETUP.md](AUTH-SETUP.md) to finish configuring project `YOUR_FIREBASE_PROJECT_ID`, enable Google sign-in, publish Firestore rules and enable cloud recovery. Copy `.env.example` to your ignored `.env` and fill in your Firebase values there. Managed Cloud Firestore stores each user's profile, bankroll, bet journal and saved entry; `FIREBASE_DATABASE_ID` lets both the browser and Worker switch to a restored database. The existing Sites hosting configuration remains unchanged.

The current backend uses the Redis REST endpoint, not a native Redis TCP driver. Production credentials are configured on the hosted Site and are not included in this download.

## Build and verify

```sh
npm run build
npm test
```

The build emits `dist/server/index.js`, a Worker-compatible server containing the frontend assets. The test uses fixtures and requires no live credentials. `npm run dev` also starts the local server if environment variables have already been set in your shell. Restart the development server after editing source files.

## Included

- `web/`: all frontend source, sportsbook assets, policy pages, live Parlay Builder and scroll-driven illustrative bankroll chart.
- `worker/`: server rendering and Redis REST feed adapter.
- `scripts/`: local development and build scripts.
- `tests/`: authentication, session handling, account isolation and parlay/feed checks.
- `firestore.rules`, `firebase.json`: user data access rules and Firebase CLI configuration.
- `.env.example`, `AUTH-SETUP.md`: configuration template and setup guide.
- `data/`: state/book display filter data.
- `.openai/hosting.json`: the existing hosted Site identity; preserve it when updating that Site.

Memberships are read from private Firebase records on the server; the browser cannot grant access through the pricing selector. Billing is not connected. State coverage and policies require operator review before production launch. Branding assets are included as currently used in the project; this archive does not grant third-party trademark or asset rights.

New Google sign-ups create a Guest account in `users/<UID>` and go to pricing. Signup date, plan, expiration and the bet-history array live on that document. Plan selection saves a preference; activation requires a trusted administrator or billing backend. Publish the updated `firestore.rules` and restart the frontend before retrying sign-up.
