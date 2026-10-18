import time
import requests
import numpy as np
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nba"

def fetch_sleeper_active_players():
    """
    Pulls the active NBA player registry directly from Sleeper's public API.
    Returns a dictionary of {full_name: sleeper_player_data}.
    """
    print("Fetching active NBA player directory from Sleeper API...")
    resp = requests.get(SLEEPER_PLAYERS_URL)
    if resp.status_code != 200:
        raise Exception(f"Sleeper API failed with status {resp.status_code}")
    
    data = resp.json()
    active_players = {}
    for pid, info in data.items():
        if info.get("active") and info.get("first_name") and info.get("last_name"):
            full_name = f"{info['first_name']} {info['last_name']}".strip()
            active_players[full_name] = {
                "sleeper_id": pid,
                "team": info.get("team"),
                "position": info.get("position"),
                "status": info.get("status")
            }
    return active_players

def get_nba_player_recent_stats(player_name: str, last_n_games: int = 10):
    """
    Pulls recent game-by-game log stats using the official NBA stats feed.
    Returns per-game lists for points, assists, rebounds, blocks, and steals.
    """
    nba_player = players.find_players_by_full_name(player_name)
    if not nba_player:
        return None
    
    player_id = nba_player[0]["id"]
    time.sleep(0.5)  # Respect NBA rate limit

    try:
        gamelog = playergamelog.PlayerGameLog(player_id=player_id, season="2025-26")
        df = gamelog.get_data_frames()[0]
    except Exception as e:
        print(f"Failed to fetch game log for {player_name}: {e}")
        return None

    if df.empty:
        return None

    df_recent = df.head(last_n_games)
    return {
        "Points": df_recent["PTS"].tolist(),
        "Assists": df_recent["AST"].tolist(),
        "Rebounds": df_recent["REB"].tolist(),
        "Blocks": df_recent["BLK"].tolist(),
        "Steals": df_recent["STL"].tolist(),
    }

def build_live_market_test_batch(sample_targets: list):
    """
    Pairs real player baseline metrics with realistic retail prop betting lines.
    """
    sleeper_db = fetch_sleeper_active_players()
    test_batch = []

    for item in sample_targets:
        name = item["player"]
        prop = item["prop"]
        line = item["line"]
        over_odds = item["over_odds"]
        under_odds = item["under_odds"]
        stat_type = "continuous" if prop == "Points" else "discrete"

        if name not in sleeper_db:
            print(f"Skipping {name}: Not found in Sleeper's active directory.")
            continue

        print(f"Pulling real stat history for {name} ({sleeper_db[name]['team']})...")
        history = get_nba_player_recent_stats(name)
        if not history or prop not in history:
            continue

        # Use recent empirical performance to project upcoming expectation
        # Hold out the most recent game as the ground truth "actual" outcome
        games = history[prop]
        if len(games) < 2:
            continue

        actual_outcome = games[0]          # Most recent game
        prior_baseline = games[1:]         # Prior games used as model input
        projected_mean = float(np.mean(prior_baseline))

        test_batch.append({
            "player": name,
            "prop": prop,
            "line": line,
            "proj": round(projected_mean, 2),
            "actual": actual_outcome,
            "over_odds": over_odds,
            "under_odds": under_odds,
            "type": stat_type
        })

    return test_batch