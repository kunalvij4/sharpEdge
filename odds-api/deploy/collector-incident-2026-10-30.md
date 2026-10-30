# Collector incident: October 30, 2026

## Findings and confidence

The supplied logs show three separate conditions:

| Signal | Finding |
| --- | --- |
| Heartbeat `LockNotOwnedError` at `lease.ping()` after the 243.32-second NFL props attempt | Production lease ownership loss is confirmed by the subsequently supplied exception line. Response JSON decoding and Unabated normalization ran synchronously on the same event loop as the heartbeat; regression tests reproduced heartbeat starvation. The Redis ownership lease expires after 120 seconds without renewal, making delayed renewal the likely mechanism. |
| NBA/NFL moneyline `provider_operation_failed`, HTTP 200 | The provider returned an unsuccessful envelope. The adapter rejects this response before normalization. The logs do not establish the provider's internal cause, an entitlement issue, or an authentication issue. |
| NHL/NBA props `partial`, with 5,322 and 31,783 selections | These attempts persisted usable selections. Missing points, unsupported bet subtypes/mappings, and unresolved event context caused individual records to be skipped. They are coverage gaps, separate from the heartbeat failure. |

The NBA moneyline failure occurred at **14:42:46 EDT / 18:42:46 UTC**; the NFL
moneyline failure occurred at **14:44:10 EDT / 18:44:10 UTC**. Their paths were
`/market/nba/straight/odds` and `/market/nfl/straight/odds`.

The 243-second run duration covers the whole collection attempt; it does not
measure event-loop blocking alone. Likewise, `outcome:failed, selections:0`
can be emitted when heartbeat failure cancels an in-flight collection before
its result is counted. It does not prove the provider supplied an empty board.

The additional log excerpt confirms the immediate failure at
**14:48:14.992 EDT / 18:48:14.992 UTC**:

```text
redis.exceptions.LockNotOwnedError: Cannot extend a lock that's no longer owned
```

The failure came from `RedisLease.ping()` calling
`self.lock.extend(120, replace_ttl=True)`. The heartbeat task failed, collection
was cancelled during shutdown, and another traceback began while unwinding the
PropLine lease context. The original cleanup unconditionally released each
lease; releasing an expired lease can raise another `LockNotOwnedError` and
replace the initial error. A regression test reproduces that error replacement
and verifies that cleanup now preserves the original failure.

The exception confirms ownership loss, while the precise reason the Redis lock
disappeared remains inferred. Reproduced event-loop starvation and the long
collection attempt support expiry from delayed renewal. Redis restart,
eviction, and resource pressure cannot be ruled out without server telemetry.

Redis-py 6.4.0's [ownership implementation](https://github.com/redis/redis-py/blob/v6.4.0/redis/lock.py)
rejects extension of a missing or differently owned lock. Unabated's
[error contract](https://docs.unabated.com/guides/errors-and-limits) distinguishes
unsuccessful envelopes from HTTP authentication, coverage, and rate-limit
errors. The existing repeated `betTypeId` moneyline filter matches the
[documented request format](https://docs.unabated.com/guides/odds).

## Remediation in this change

- Decode Unabated JSON and normalize both odds boards and identity catalogs
  through the existing worker-thread helper, allowing heartbeat renewal to
  continue while those operations run.
- Use the helper for failure-state writes as well. Its cancellation behavior
  waits for worker completion before ownership and resources are released.
- Log cancelled collections as `cancelled` with `CancelledError`, and log
  heartbeat failures as `collector_heartbeat_failed` with the exception class.
- Preserve the original exception if releasing an already lost Redis lease
  fails. An old owner cannot reacquire or delete its successor's lock, and
  ownership loss on a normal exit still raises an error.

Failed provider responses continue to preserve stored quotes with their original
freshness timestamps. Unknown mapping IDs, subtypes, and missing points remain
explicit warnings: their settlement semantics cannot be inferred safely from
the IDs in the supplied logs. Unsuccessful HTTP-200 envelopes still fail the
scope without speculative retries or a different odds dataset.

## Validation

Regression tests reproduced heartbeat starvation in JSON decoding, board
normalization, and catalog normalization before the fix; all three pass after
it. Additional tests cover preserving the original lease error, protecting a
successor's ownership, reporting lease loss on normal exit, and cancellation
logging/cache preservation.

Full local suite: **281 passed, 15 skipped**. The skipped deployment tests require
Linux, Bash, and `flock`. PostgreSQL integration tests were not enabled because
no disposable test database was configured. Docker container validation was
unavailable because the local Docker engine was not running.

## Production follow-up

This change has not been deployed. SSH to the documented production target
rejected the available credentials, so current container logs and runtime state
could not be inspected.

1. Build and deploy this revision using the existing
   [image deployment workflow](README.md#build-and-deploy).
2. Use **Inspect odds API collector** and `/v1/status` to observe at least a full
   eight-minute feed cycle, including completion of NFL props. Check heartbeat
   continuity, `collector_healthy`, scope attempts, and collector child exits.
   API readiness alone does not establish collector health.
3. If moneyline envelopes still fail, provide Unabated the UTC times, endpoint
   paths, and discovered bet-type filters through an approved support channel.
   A provider-side cause remains unresolved; credentials and raw odds must stay
   out of application logs.
4. Review unsupported IDs against the account's bet/period discovery data before
   adding mappings. Missing over/under points or event identities require valid
   upstream fields before those selections can be published.
