# SharpEdge

SharpEdge is a sports betting analytics tool that fetches live odds from various sportsbooks, analyzes markets (moneyline, spreads, totals), and identifies +EV (positive expected value) betting opportunities. The scheduled pipeline calculates in memory and publishes current results to S3 and Redis.

## Features
- Fetch live odds for multiple sports (e.g., NFL, NBA).
- Analyze moneyline, spreads, and totals markets.
- Identify +EV opportunities using a weighted model.
- Publish current EV and arbitrage opportunities to S3 and Redis.

## Requirements
- Python 3.11+
- `.env` file for environment variables.

## Installation
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd sharpEdge
   ```
2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3. Set up your .env file:
    ```bash
    ODDS_API_KEY=your_api_key_here
    ```

DynamoDB bet and closing-odds storage has been disabled, including the legacy
`/storeBet` endpoint. See the [pipeline deployment notes](lambda/retrieveOdds/README.md)
for rollout and cleanup of previously retained tables.

