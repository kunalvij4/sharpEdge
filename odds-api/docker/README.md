> Bet365 runs locally in the resource-limited service in `compose.bet365.yaml` and sends snapshots to the server over HTTPS; see [current collection setup](../PROPLINE.md).

# Application container

The API and API-feed collectors use `Dockerfile` and `compose.yaml`. Bet365
uses `Dockerfile.bet365` and `compose.bet365.yaml` on your local machine.

Verify headed Edge/Xvfb and protocol parsing with a synthetic local HTTP and
WebSocket fixture:

```sh
docker compose --env-file .env.bet365 -f compose.bet365.yaml run --rm --no-deps bet365 python -m scripts.smoke_bet365_container
```

This check does not start collectors or contact Bet365. It confirms that Edge
runs as UID 10001 with its browser sandbox enabled and without headless mode.

## Browser seccomp profile

`seccomp-browser.json` is the unmodified profile recommended by Playwright for
sandboxed browsers running as a non-root user. It allows browser user namespaces.

- [Upstream profile](https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json)
- [Docker documentation](https://playwright.dev/python/docs/docker#crawling-and-scraping)
- SHA-256: `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`
- License: Apache-2.0; see [LICENSE.playwright](LICENSE.playwright).
