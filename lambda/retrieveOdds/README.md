# Retrieve Odds Lambda

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
`nfl_football`, and `mlb_baseball` as sport keys. Event-specific prop requests
use `/v1/events/{event_id}/odds`.
