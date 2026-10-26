# Retrieve Odds Lambda

All three Lambda functions are scheduled every five minutes. The collector
continues storing raw odds snapshots in DynamoDB. EV calculation fetches fresh
moneyline odds and all supported player props for NBA, NFL, NHL, MLB, and NCAAF directly from the in-house OddsAPI, sharing
that response across its calculations for each sport. EV also stores each fetched
game, including market lines and bookmaker prices, as a timestamped DynamoDB
snapshot before calculating bets. S3 stores only EV and
arbitrage results. Existing raw-odds S3 objects are not deleted by this change.

The EV function receives `ODDS_API_KEY`, `ODDS_API_BASE_URL`, `TABLE_NAME`,
and DynamoDB write access through SAM.
Its deployment package includes the shared API client and player-props loader;
its timeout is 300 seconds to allow for the API requests.

The retrieve-odds function calls the in-house odds API. It sends the product key
as `X-API-Key` and requests the API's `/v1/sports/{sport}/odds` route. The base
URL is the API's HTTPS origin, without a trailing `/v1` path.

## Configuration

- `ODDS_API_KEY`: a product key configured in the in-house API's `API_KEYS`.
- `ODDS_API_BASE_URL`: the reachable HTTPS origin of the deployed in-house API.

The function obtains these from the `OddsApiKey` and `OddsApiBaseUrl` SAM
parameters. The local `lambda/.env` file is not read by AWS Lambda or SAM
automatically. For deployment, provide both parameters to `sam deploy`.
For SAM local invocation, copy `env.example.json`, fill in the values, and pass
the resulting JSON file with `sam local invoke --env-vars <file>`. Keep the
filled-in file private; it contains the product key.

The current in-house all-sports odds route supports moneyline (`h2h`) requests;
the collector requests that market. The in-house API uses `nba_basketball`,
`nfl_football`, `nhl_hockey`, `mlb_baseball`, and `ncaaf_football` as sport keys. Event-specific prop requests
use `/v1/events/{event_id}/odds`.

All leagues use the same PlayerPropsModel for over/under props. Props are requested
with `markets=all_props`; events without moneyline quotes are included.
