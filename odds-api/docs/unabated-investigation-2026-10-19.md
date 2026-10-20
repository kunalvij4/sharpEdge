# Unabated collection investigation — 2026-10-19

## Findings

The event lookup failure was reproduced directly against Unabated using the existing collector credentials and configuration. The collector was paused during the probes and restarted afterward. The API and database stayed running. Probes were spaced at least six seconds apart after each response, and no probe returned HTTP 429.

| Request | UTC request time | HTTP | Envelope | Result |
|---|---|---|---|---|
| `/league` | 14:47:34 | 200 | `success: true` | Discovery succeeded; NBA/NFL/MLB were returned |
| `/market-type` | 14:47:40 | 200 | `success: true` | Names include `Straight` and `Player Props` |
| `/bettype` | 14:47:46 | 200 | `success: true` | Moneyline definitions discovered |
| `/event/nba/upcoming` | 14:47:53 | 200 | `success: false` | Generic processing error; no data |
| `/event/NBA/upcoming` | 14:48:02 | 200 | `success: false` | Same error; capitalization did not fix it |
| `/event/nfl/upcoming` | 14:48:10 | 200 | `success: false` | Same error |
| `/event/mlb/upcoming` | 14:48:17 | 200 | `success: false` | Same error |
| `/market/nba/straight/odds?betTypeId=369&betTypeId=1` | 14:48:23 | 200 | `success: true` | Odds available: 85 distinct event IDs, 122 market groups |

All four failed event requests returned:

```json
{"success": false, "messages": ["An error occurred while processing your request."]}
```

The response summaries contained no request/correlation ID in the inspected headers. Server Date headers were present. No credential or raw odds payload is stored in this report.

## What this establishes

- The credentials are accepted by discovery and the NBA moneyline odds endpoint. A blanket invalid-key diagnosis does not fit the observed responses.
- The same event lookup failed across three leagues and with both NBA capitalizations, even when paced independently of the collector.
- The public OpenAPI contract requires only the string `league` path parameter for this operation. `changedSince` and API-version parameters are optional. There is no missing required date or season parameter in our request.
- This is a provider application error inside an HTTP 200 response, not an HTTP transport failure. The response does not identify Unabated's internal exception. Its server logs are required to distinguish an account-specific defect from a wider event-service failure.
- The adapter currently makes `/event/{league}/upcoming` a mandatory dependency before requesting a board. Therefore a failing event lookup prevents ingestion even while the odds endpoint itself is working. A regression test now demonstrates this exact behavior.

## Independent adapter defect corrected locally

The `/market-type` discovery response uses display names `Straight` and `Player Props`, while REST routes use `straight` and `props`. The previous comparison required exact equality with route tokens and raised `market_type_not_discovered` after otherwise successful requests. This explains that separate outcome in the existing collector logs.

The workspace adapter now maps those explicit display-name aliases case-insensitively, while continuing to discover numeric IDs. Regression tests cover both board kinds and disabled-market IDs with deliberately changed IDs to rule out hardcoding. The observed public market-type definitions were captured as a fixture. This correction was subsequently deployed by rebuilding and starting the Docker Compose stack on 2026-10-19, and its presence was confirmed in the running collector.

Validation after the correction: **89 offline/SQLite tests passed**; lint and formatting checks passed. This investigation did not rerun PostgreSQL integration or container smoke tests.

Existing logs also contained `rate_limited` outcomes. Those are a separate observation: the slow isolated event probes still failed without 429 responses, so rate limiting alone does not explain this event error.

## Next action

Provide Unabated support with the failing paths, UTC times above, exact generic message, and the fact that discovery and moneyline odds succeeded with the same account. Share the account identifier through their support channel; do not send the API key.

An application workaround can use event metadata embedded in successful odds groups, combined with team discovery. Such a change must handle missing identities and lifecycle information conservatively and must not treat the failed event-discovery scope as complete or remove cached selections. The current investigation does not change that completeness policy.

`python -m scripts.diagnose_unabated` repeats the bounded read-only probes using local environment settings. Pause any other collector using the same key before running it. The command prints sanitized response summaries, not credentials or raw odds.

References: [Unabated discovery guide](https://docs.unabated.com/guides/discovery), [odds guide](https://docs.unabated.com/guides/odds), [error semantics](https://docs.unabated.com/guides/errors-and-limits), and [OpenAPI contract](https://data.unabated.com/swagger/v1/swagger.json).
