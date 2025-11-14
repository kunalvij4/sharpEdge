from flask import Flask
from apis.odds_api import OddsAPI
import os

app = Flask(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
odds_api = OddsAPI(ODDS_API_KEY)

@app.route("/")
def hello_world():
    return "SharpEdge Default Route"

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

if __name__ == "__main__":
    app.run(debug=True)
