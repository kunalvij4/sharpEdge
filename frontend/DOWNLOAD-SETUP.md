# SharpEdge — full project

Exported source commit: 5847ec2c79e99113a5ddce9c9a06edfcf4b271da (published version 25).

## Run locally

Install Node.js 22 or newer. No third-party npm dependencies are required.

1. Extract this ZIP and open a terminal in the SharpEdge folder.
2. Copy `.env.example` to `.env` and enter your Layerbase REST endpoint and token. Keep this file private.
3. Run `node --env-file=.env scripts/dev.mjs`.
4. Open http://localhost:4173.

EV, arbitrage and parlay pages read the `EV` and `arbitrage` Redis keys on the server. The browser refreshes the feed every five minutes and supports manual refresh. Missing credentials show an unavailable state, not demo opportunities.

The current backend uses the Redis REST endpoint, not a native Redis TCP driver. Production credentials are configured on the hosted Site and are not included in this download.

## Build and verify

```sh
npm run build
node tests/parlay-feed.mjs
```

The build emits `dist/server/index.js`, a Worker-compatible server containing the frontend assets. The test uses fixtures and requires no live credentials. `npm run dev` also starts the local server if environment variables have already been set in your shell. Restart the development server after editing source files.

## Included

- `web/`: all frontend source, sportsbook assets, policy pages, live Parlay Builder and scroll-driven illustrative bankroll chart.
- `worker/`: server rendering and Redis REST feed adapter.
- `scripts/`: local development and build scripts.
- `tests/`: parlay/feed integration checks.
- `data/`: state/book display filter data.
- `.openai/hosting.json`: the existing hosted Site identity; preserve it when updating that Site.

Membership selection remains a client-side prototype, not secure authentication or subscription enforcement. State coverage and policies require operator review before production launch. Branding assets are included as currently used in the project; this archive does not grant third-party trademark or asset rights.
