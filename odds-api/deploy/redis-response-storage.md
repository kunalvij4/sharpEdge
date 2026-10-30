# Prepared Redis odds responses

The collector stores compressed event JSON in the public API hierarchy:
event fields → bookmakers → markets → outcomes. Decimal prices, ordering,
descriptions, and freshness fields are prepared during collection. Props and
game lines share the event document and the same atomic refresh.

Keys use `<REDIS_PREFIX>:event:<event-id>`. Values use the `zlib:1:` compression
envelope (base64-encoded zlib); the JSON's `_storage.version` identifies response
schema **2**.

## Public and private fields

Public fields match an event odds response: `id`, `sport_key`, `sport_title`,
`commence_time`, `home_team`, `away_team`, and `bookmakers`. Bookmakers contain
market arrays, and markets contain outcome arrays. Each prop outcome includes
`name`, decimal `price`, `point`, `description`, and `freshness`.

Small `_storage` sections retain data needed for future merges:

| Location | Private fields |
| --- | --- |
| Event | Schema version and canonical event identity/lifecycle metadata |
| Bookmaker | Canonical book ID |
| Outcome | Selection ID, player/period/alternate identity, exact decimal line, original American price, availability, source IDs, and deep link |
| Game outcome | Collection/source/expiry timestamps, since game outcomes have no public freshness object |

Prop timestamps live in their public freshness object. Canonical quotes can be
restored for collectors and diagnostics without storing another full copy of
each quote. Private sections are removed from HTTP responses.

## Read behavior and preservation

A default event props request performs one Redis GET, decompresses/parses the
event JSON, applies current freshness policy, removes private metadata, and
serializes the response. It avoids domain quote reconstruction, regrouping,
decimal conversion, and Pydantic response-object construction. American requests
select the exact retained American price.

Freshness and filtering still run on reads. `age_seconds`, `observed_at`, cached
price eligibility, source expiry, `freshOnly`, and kickoff eligibility depend on
the current time. Book/market filters and commence-time bounds apply to prepared
arrays. Group `last_update` reflects returned outcomes. An explicit bookmaker
filter also validates against the stored bookmaker catalog.

Reads and failed collections never advance collection/source timestamps.
Partial, empty, or narrower refreshes preserve absent quotes from both feeds.
Valid newer quotes pass the existing replacement policy. WATCH/MULTI protects
event merges from concurrent writers; Redis expiry remains the exact kickoff.

## Rollout and rollback

The reader accepts uncompressed and compressed legacy flat records. The next
collector write upgrades each touched event atomically. Existing data can also
be converted explicitly using the new image's runtime environment:

```sh
# Preview counts and encoded bytes without writing.
python -m scripts.rewrite_redis_odds --format response

# Apply the prepared response format.
python -m scripts.rewrite_redis_odds --format response --apply
```

The tool compares the current value atomically before replacing it with
`SET ... KEEPTTL`. Concurrent updates and expired keys are skipped. Quote values,
identities, timestamps, and the event index are preserved. Repeating a completed
migration finds no candidates. Output contains counts and sizes. Unlike the
shrink-only emergency compactor, a format conversion must fit within Redis's
memory limit; rejected writes leave the old value intact.

Older images require the legacy schema. Before rolling back to one, stop all
collectors, run the following using the new image, and then deploy the old image:

```sh
python -m scripts.rewrite_redis_odds --format legacy
python -m scripts.rewrite_redis_odds --format legacy --apply
```

Check `raced_events` and rerun if necessary before starting the old reader.
Collectors writing schema 2 must remain stopped during rollback conversion.
Use the existing [image deployment procedure](README.md#build-and-deploy) with
the existing Redis namespace and persistent artifact volume.

## Validation and benchmark

Compatibility tests compare Redis responses directly with the SQL API across
both price formats, market/book filters, periods/alternates, provider freshness
limits, cached props, source/explicit expiry, kickoff, validation errors, and
absent events. Other tests verify one-GET reads without quote reconstruction,
legacy upgrades, rollback, concurrent writes, and exact TTL/quote preservation.

Run the offline benchmark with development dependencies installed:

```sh
python -m scripts.benchmark_prepared_odds --selections 30000 --iterations 3
```

For 30,000 synthetic selections, the local median query assembly time over three
runs was **10.301 seconds** for the legacy path and **0.286 seconds** for the
prepared path (about **36× faster**). Compressed values used **1,576,343** and
**1,500,479 bytes**, respectively (about **4.8% smaller**), with identical public
payloads. Preparing and saving the event took **0.984 seconds**.

This uses in-memory Redis and measures query assembly before HTTP serialization.
Production latency also includes Redis network and HTTP costs.

Production deployment and live migration have not been performed because the
available production SSH credentials were rejected.
