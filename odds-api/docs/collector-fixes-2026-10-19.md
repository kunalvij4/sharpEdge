# Follow-up collector fixes, 2026-10-19

The new logs had three separate causes: upstream unsuccessful responses, local rate-limit coordination, and incomplete normalization of successful boards.

## Rate-limit coordination

The pre-fix diagnostic recorded 173 requests, 43 HTTP-429 responses, and 42 retries. The shared admission lock was held while an odds request waited for its interval, blocking unrelated discovery calls. A waiter also used a deadline calculated before sleeping, even if another request extended the shared cooldown during that sleep. Odds requests were admitted by start time without serializing the HTTP response lifecycle.

Odds requests now share a serialized HTTP slot and wait the configured interval from completion. Discovery is admitted separately under the same general limit and shared cooldown, without waiting for an odds-only interval. Every waiter rechecks admission after waking. Cancellation releases the odds slot and retains the interval. Bounded retries and authorization checks are unchanged.

At 18:15:22 UTC, the first rebuilt collector had made **545 requests with no recorded rate-limit responses**, compared with 43 in the pre-fix diagnostic. This is an observation for that run, not a promise about other users of the same provider key.

The original six fixed 30-second schedule deadlines remain. Serial response time plus the provider interval can exceed the available cycle; overdue jobs are recorded and overlapping scopes are skipped. Request limits take precedence over catching up.

## Successful-board normalization

Live discovery confirmed MLB names absent from the previous semantic aliases: `RBIs`, `Pitcher Outs`, `Pitcher Hits Allowed`, `Pitcher Earned Runs`, and `Hitter Walks`. These now map to their corresponding existing public market keys. IDs still come from discovery.

Period discovery confirmed `Second Inning`, `First Five Innings`, `First Three Innings`, and `First Seven Innings` in the warning logs. Named individual innings and first-three/five/seven periods now have separate keys; full-game identity is retained. NBA period ID 3 remains unresolved because NBA discovery omits it. Its meaning is not inferred from another league's catalog.

An isolated MLB props response also confirmed subtypes `Milestone`, `Milestone-Alt`, and `strikeouts`. These remain explicitly unsupported; subtype names alone do not prove standard over/under settlement or side semantics. These warnings make a board partial, preserving missing stored selections.

After rate coordination improved, successful NBA and NFL responses exposed a further blocker: one prop line without `points` rejected the whole board. The normalizer now skips that unusable quote, emits `missing_prop_points:bet=<id>:source=<id>`, and retains valid selections, including an alternate with its own points. The board remains partial, so absent quotes are not erased.

## Upstream failures and observability

`GET /market/{league}/props/odds` is the documented upstream route. It has no arbitrary event filter. Successful responses are normalized and filtered by event in the local API:

```text
GET /v4/sports/{sport}/events/{event_id}/odds?markets=player_points&oddsFormat=american
X-API-Key: <product key>
```

The provider continues to return intermittent HTTP-200 envelopes with `success:false`, including when isolated requests are spaced six seconds apart. Some odds and event discovery requests succeed later. A generic unsuccessful response does not establish the provider's internal cause or an account coverage denial. These remain visible errors rather than empty successful boards. Logs now include the safe reason `upstream_unsuccessful_response`, and `/status` counts `operation_failures` independently of `rate_limits`. Raw error bodies and credentials stay out of collection logs.

Official sources: [odds request format](https://docs.unabated.com/guides/odds), [errors and shared request limits](https://docs.unabated.com/guides/errors-and-limits), and [API reference](https://docs.unabated.com/reference).

Read-only diagnostic evidence is in `collector-audit-2026-10-19.jsonl` and `collector-audit-mlb-2026-10-19.jsonl`. The diagnostic scripts automatically restarted the regular collector after the isolated probes. They do not write provider results into the database.

## Validation

**124 offline/SQLite tests passed**, including deterministic concurrent admission, extended cooldown, slow-response serialization, cancellation, discovered MLB aliases, distinct period identity, subtype exclusion, and recovery around missing prop points. Ruff lint and formatting passed. The API and collector images were rebuilt against the persistent database.

The rebuilt image passed isolated Docker checks for two API workers, authentication, persisted moneylines/props, OpenAPI, database/API restart persistence, provider outage caching, exclusive collector ownership, credential redaction, and graceful shutdown. These checks use synthetic data and separate disposable resources.

At **18:23:41 UTC**, the final deployment reported a healthy API and collector heartbeat. PostgreSQL was healthy and migrations had exited successfully. Its 97 provider requests recorded 54 unsuccessful operations and no rate-limit responses. Public moneyline queries returned actionable results for 44 NBA events, 19 NFL events, and one MLB event. Current props scopes still reported upstream operation failures; the sampled event props endpoints had zero actionable outcomes. Previously stored MLB `selection_count=2825` is retained diagnostic history, not a claim of fresh live props. No successful live NBA/NFL props refresh after the missing-points fix has yet been verified.

The safe final snapshot is `collector-after-fixes-2026-10-19.jsonl`. Full live props acceptance remains blocked by the unsuccessful upstream responses; this deployment does not claim to have repaired the provider's internal failure.
