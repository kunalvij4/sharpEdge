# Application container

The API and both collectors run together using the root `Dockerfile` and
`compose.yaml`. See [configuration, coverage, and operations](INTEGRATION.md).

Verify headed Edge/Xvfb and protocol parsing with a synthetic local HTTP and
WebSocket fixture:

```sh
docker compose run --rm --no-deps api python -m scripts.smoke_bet365_container
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
