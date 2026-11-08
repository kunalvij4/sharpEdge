from flask import Flask, jsonify
from apis.odds_api import OddsAPI
import os

app = Flask(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
odds_api = OddsAPI(ODDS_API_KEY)

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
        <h2>This route is for testing purposes</h2>
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
    return jsonify({"error": "Bet storage has been disabled", "stored": False}), 410


# Define the markets we have weights for
# For each market create an API route to retrieve EV Bets for that market 
# For each route, you need a function that will create a new instance of SharpEdge and then use the data to generate those bets. You then return those bets back


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
