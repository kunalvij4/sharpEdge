# SharpEdge

SharpEdge is a sports betting analytics tool that fetches live odds from various sportsbooks, analyzes markets (moneyline, spreads, totals), and identifies +EV (positive expected value) betting opportunities. It integrates with AWS DynamoDB to store betting data.

## Features
- Fetch live odds for multiple sports (e.g., NFL, NBA).
- Analyze moneyline, spreads, and totals markets.
- Identify +EV opportunities using a weighted model.
- Store betting data in AWS DynamoDB under the `EV_Bets` table.

## Requirements
- Python 3.11+
- AWS DynamoDB
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

