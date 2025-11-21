from flask import Flask, jsonify, request
from apis.odds_api import OddsAPI
from db.dynamodb_store_ev_bets import DynamoDBClient
from services.sharpedge_model import SharpEdge
import os

app = Flask(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
odds_api = OddsAPI(ODDS_API_KEY)

region = "us-east-2"  # Replace with your AWS region
table_name = "EV_Bets"
dynamo_client = DynamoDBClient(region_name=region, table_name=table_name)

@app.route("/")
def hello_world():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SharpEdge</title>
    </head>
    <body>
        <h1>SharpEdge Default Route</h1>
    </body>
    </html>
    """


# ---- Odds API Routes ----

@app.route("/nfl/games", methods=["GET"])
def nfl_games():
    # call the imported function and return its result
    return odds_api.get_nfl_games()

@app.route("/nba/games", methods=["GET"])
def nba_games():
    return odds_api.get_nba_games()

@app.route("/nfl/markets", methods=["GET"])
def nfl_markets():
    return odds_api.get_nfl_all_markets()

@app.route("/nba/markets", methods=["GET"])
def nba_markets():
    return odds_api.get_nba_all_markets()

@app.route("/storeBet", methods=["PUT"])
def storeBets():
    # Extract JSON payload sent by client
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body sent"}), 400
    
    try:
        # Pass the data into your Dynamo function
        result = dynamo_client.store_data(data)
        
        return jsonify({
            "status": "success",
            "stored": result
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Define the markets we have weights for
# For each market create an API route to retrieve EV Bets for that market 
# For each route, you need a function that will create a new instance of SharpEdge and then use the data to generate those bets. You then return those bets back


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6061, debug=True)
