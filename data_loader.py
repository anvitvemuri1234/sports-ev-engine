import time
import unicodedata
import requests
import numpy as np
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, leaguedashteamstats

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nba"

def clean_name(name: str) -> str:
    """Strips accents and diacritics (e.g. 'Jokić' -> 'Jokic') for clean matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", name) 
        if unicodedata.category(c) != "Mn"
    ).lower().replace(".", "").strip()

def fetch_sleeper_active_players():
    """Pulls active players from Sleeper and indexes them with normalized names."""
    print("Fetching active NBA player directory from Sleeper...")
    resp = requests.get(SLEEPER_PLAYERS_URL)
    if resp.status_code != 200:
        raise Exception("Failed to contact Sleeper API")
    
    active_players = {}
    for pid, info in resp.json().items():
        if info.get("active") and info.get("first_name") and info.get("last_name"):
            full = f"{info['first_name']} {info['last_name']}"
            active_players[clean_name(full)] = {
                "display_name": full,
                "team": info.get("team"),
                "position": info.get("position")
            }
    return active_players

def get_opponent_defensive_factor(opponent_abbr: str, stat_col: str = "PTS") -> float:
    """
    Compares how many stats the opponent concedes relative to league average.
    Returns a multiplier (e.g., 1.05 = allows 5% more than average).
    """
    time.sleep(0.5)
    try:
        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense="Opponent",
            per_mode_detailed="PerGame",
            season="2025-26"
        )
        df = team_stats.get_data_frames()[0]
        
        target_col = f"OPP_{stat_col}"
        if target_col not in df.columns:
            target_col = stat_col
            
        league_avg = df[target_col].mean()
        opp_row = df[df["TEAM_ABBREVIATION"] == opponent_abbr]
        
        if opp_row.empty or league_avg == 0:
            return 1.0
            
        opp_allowed = opp_row[target_col].values[0]
        factor = float(opp_allowed / league_avg)
        return round(factor, 3)
    except Exception as e:
        print(f"Could not load team stats: {e}")
        return 1.0

def get_nba_player_recent_stats(player_name: str, last_n_games: int = 10):
    """Pulls trailing game logs from official NBA stats."""
    nba_player = players.find_players_by_full_name(player_name)
    if not nba_player:
        return None
    
    player_id = nba_player[0]["id"]
    time.sleep(0.5)

    try:
        gamelog = playergamelog.PlayerGameLog(player_id=player_id, season="2025-26")
        df = gamelog.get_data_frames()[0]
    except Exception:
        return None

    if df.empty:
        return None

    df_recent = df.head(last_n_games)
    return {
        "Points": df_recent["PTS"].tolist(),
        "Assists": df_recent["AST"].tolist(),
        "Rebounds": df_recent["REB"].tolist(),
        "Blocks": df_recent["BLK"].tolist(),
    }

def build_live_market_test_batch(sample_targets: list):
    sleeper_db = fetch_sleeper_active_players()
    test_batch = []

    stat_col_map = {
        "Points": "PTS",
        "Assists": "AST",
        "Rebounds": "REB",
        "Blocks": "BLK"
    }

    for item in sample_targets:
        name = item["player"]
        opp = item["opponent"]
        prop = item["prop"]
        line = item["line"]
        over_odds = item["over_odds"]
        under_odds = item["under_odds"]
        stat_type = "continuous" if prop == "Points" else "discrete"

        norm_name = clean_name(name)
        if norm_name not in sleeper_db:
            print(f"Skipping {name}: Not found in Sleeper.")
            continue

        player_info = sleeper_db[norm_name]
        print(f"Evaluating {player_info['display_name']} ({player_info['team']}) vs {opp}...")

        history = get_nba_player_recent_stats(name)
        if not history or prop not in history:
            continue

        games = history[prop]
        if len(games) < 2:
            continue

        actual_outcome = games[0]
        raw_baseline = float(np.mean(games[1:]))

        # Adjust baseline using opponent defense factor
        col = stat_col_map.get(prop, "PTS")
        matchup_multiplier = get_opponent_defensive_factor(opp, col)
        adjusted_projection = round(raw_baseline * matchup_multiplier, 2)

        print(f"   -> Raw: {raw_baseline:.1f} | Opp Multiplier ({opp}): {matchup_multiplier:.2f} | Adj Proj: {adjusted_projection:.1f}")

        test_batch.append({
            "player": player_info["display_name"],
            "prop": prop,
            "line": line,
            "proj": adjusted_projection,
            "actual": actual_outcome,
            "over_odds": over_odds,
            "under_odds": under_odds,
            "type": stat_type
        })

    return test_batch