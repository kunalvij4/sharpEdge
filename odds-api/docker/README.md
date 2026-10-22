# Headed Edge collection in Docker

Verified locally on Docker Desktop's Linux/amd64 engine using Microsoft Edge **155.0.4283.62**, Playwright **1.64.0**, and Xvfb. This uses an actual headed Edge process attached through loopback CDP. The final smoke check confirmed an Edge user agent, no `--headless` process flag, HTTP and WebSocket capture, display `:99`, UID `10001`, and an enabled browser sandbox.

## Start and inspect

From `odds-api`:

```powershell
docker compose -f compose.bet365.yaml up --build --detach
docker compose -f compose.bet365.yaml logs --follow --tail 40 bet365
```

The separate Compose project is `sharpedge-bet365`; the service container is `sharpedge-bet365-bet365-1`. It does not restart or modify the existing API, database, or Unabated collector. It does not receive their provider/database credentials or publish a browser/debugging port.

The worker starts a collection cycle every **120 seconds**. Each cycle captures the NJ homepage's NBA/NFL/MLB markets and NBA Points O/U, organizes the HTTP snapshots, and verifies selection references. A cycle publishes `latest.json` only after finding moneylines, props, complete O/U pairs, passing source checks, and no normalization errors. A failed attempt records its status and preserves the last verified pointer; it does not make that older data fresh.

The host output is `artifacts/bet365-docker/collector/`:

- `worker-status.json`: collecting, verified, failed, or stopped, with run timing.
- `latest.json`: timestamp, counts, and relative paths to the latest verified JSON and its verification report.
- `runs/<UTC-run-id>/verified/odds.json`: organized selections and source references.
- `runs/<UTC-run-id>/verified/nba.json`, `nfl.json`, `mlb.json`: per-league files.
- `runs/<UTC-run-id>/homepage/` and `nba/`: raw protocol records, text, screenshots, and browser diagnostics.

The worker retains the five most recent generated runs and protects the currently published run. It ignores directories not named using its UTC run-ID format. Dedicated browser profiles are stored inside the worker container's `/app/.cache/`; personal browser profiles are not mounted.

Stop it with:

```powershell
docker compose -f compose.bet365.yaml stop bet365
```

`init: true` and `docker/bet365-entrypoint.sh` forward shutdown to the worker first and keep Xvfb alive until browser cleanup finishes. The display uses an ephemeral xauth cookie and does not listen on TCP. The service uses `restart: unless-stopped`; an explicit stop remains stopped until restarted.

## Validation results

The initial default-sandbox container launch failed with `Operation not permitted` while creating browser namespaces. The [Playwright-recommended browser seccomp profile](https://playwright.dev/python/docs/docker#crawling-and-scraping) resolved that without disabling the browser sandbox. The vendored profile and its source/hash/license are in `docker/`.

An initial container session in UTC loaded homepage data but left NBA league content blank. The working configuration sets `TZ=America/New_York`. A longer-settling run then loaded league/O/U markets, and a fresh container using the original eight-second waits also passed. These observations establish a working configuration; they do not prove which site heuristic caused the earlier failure.

The local fixture smoke test and the live collection tests ran inside the image, not through a Windows browser. The two-cycle verification run used:

```powershell
docker compose -f compose.bet365.yaml run --rm --no-deps bet365 python -m scripts.collect_bet365_container --cycles 2 --output-dir /app/artifacts/repeat-check
```

Both cycles passed, beginning at `2026-10-22T05:12:08Z` and `2026-10-22T05:14:08Z`:

| Result | Each cycle |
|---|---:|
| Moneyline games / outcomes | 19 / 38 |
| Prop selections | 1,174 |
| Complete NBA Points O/U pairs / selections | 28 / 56 |
| Exported source references checked | 1,212 |
| Source verification errors | 0 |
| Normalization errors | 0 |
| Moneyline pairs also matching page text | 18 / 19 |

Cycle durations were **39.14s** and **36.43s**. These are local measurements, not an AWS latency guarantee. One moneyline pair did not match the captured page-text excerpt and remains explicitly flagged; source ID/price verification passed for all outcomes. O/U verification checks player descriptors, column positions, side labels, and line values against the captured protocol, rather than claiming independent UI verification for every price.

The separate full homepage-tab test collected 17 games and 1,124 prop selections, with all 1,158 outcome references verified. Counts vary with time and offered markets; captures from different runs must not be presented as simultaneous prices.

The final headed-runtime check can be repeated without contacting Bet365:

```powershell
docker compose -f compose.bet365.yaml run --rm --no-deps bet365 python -m scripts.smoke_bet365_container --output-dir /app/artifacts/smoke
```

To verify a saved run, substitute its container-relative path:

```powershell
docker compose -f compose.bet365.yaml run --rm --no-deps bet365 python -m scripts.verify_bet365_dump --input-dir /app/artifacts/collector/runs/<run-id>/verified
```

## Implementation and scope

`Dockerfile.bet365` adds the optional browser dependencies, system Edge, Xvfb and xauth. Its entrypoint supervises Xvfb and the collector. [Playwright documents Xvfb for headed Linux execution](https://playwright.dev/python/docs/ci#running-headed) and [its Edge installer](https://playwright.dev/python/docs/browsers#installing-google-chrome--microsoft-edge). The regular API Dockerfile remains unchanged. `.dockerignore` excludes browser caches and generated artifacts from both build contexts.

`compose.bet365.yaml` selects Linux/amd64, a 1GB shared-memory area, the browser seccomp profile, New York time, and an artifact-only bind mount. Edge is installed from Microsoft's stable package repository at build time; the exact tested version above is recorded by the smoke test. Rebuilding later can install a newer stable Edge version and requires another validation run.

`scripts/bet365_browser_runtime.py` supplies the same native headed launch/cleanup to both extractors. `scripts/collect_bet365_container.py` runs the repeat loop and publishes an atomic pointer to verified output. Fully unpriced suspended fixture rows are recorded under `source_unavailable_moneylines`; they are not exported as empty games or invented prices.

This is a verification collector. Production API/database integration remains separate, as does AWS deployment. The scheduled scope includes homepage threshold/yes-no props for all three leagues and NBA Points O/U. It does not yet collect every NBA combo or all NFL/MLB standalone O/U markets. Threshold props are not relabeled as O/U. Stable player identity, settlement rules, standalone availability, source start-time timezone, and lifecycle filtering still require validation before publishing through the API.

# Browser seccomp profile

`seccomp-browser.json` is the profile recommended by the Playwright Docker documentation for running sandboxed browsers as a non-root user. It permits creation of user namespaces while retaining a syscall allowlist.

Upstream: https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json

Documentation: https://playwright.dev/python/docs/docker#crawling-and-scraping

Downloaded profile SHA-256: `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.

Upstream license: Apache-2.0; see `LICENSE.playwright`. The profile is copied without modifications.
