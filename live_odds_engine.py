import os
import requests
from collections import defaultdict

# -------------------------------------------------------------
# API CONFIGURATION
# -------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "89c1a3d5b262f10b1df6230a275f75eb")

# Scanning Pro and College boards dramatically increases opportunities
SPORTS = [
    "americanfootball_nfl",
    "americanfootball_ncaaf",  # College Football (huge Saturday volume)
    "basketball_nba",
]

REGIONS = "us"
# Main markets
MAIN_MARKETS = "h2h,spreads,totals"

TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "betrivers": "BetRivers"
}

def american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)

def american_to_decimal_net(odds: int) -> float:
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)

def calculate_kelly(true_prob: float, odds: int, fraction: float = 0.25) -> float:
    b = american_to_decimal_net(odds)
    q = 1.0 - true_prob
    f_star = (b * true_prob - q) / b
    return max(0.0, f_star * fraction)

# ==========================================================
# 1. CONSENSUS DEVIGGING & EV CHECKER
# ==========================================================

def evaluate_line_offers(matchup: str, market_label: str, offers: dict, bankroll: float):
    found = 0
    for line_val, books in offers.items():
        if len(books) < 3:
            continue

        side_a_probs, side_b_probs = [], []
        side_a_name, side_b_name = None, None

        for b_name, pair in books.items():
            names = list(pair.keys())
            if len(names) != 2:
                continue
            side_a_name, side_b_name = names[0], names[1]
            p_a = american_to_prob(pair[side_a_name])
            p_b = american_to_prob(pair[side_b_name])

            side_a_probs.append(p_a / (p_a + p_b))
            side_b_probs.append(p_b / (p_a + p_b))

        if not side_a_probs:
            continue

        fair_p_a = sum(side_a_probs) / len(side_a_probs)
        fair_p_b = sum(side_b_probs) / len(side_b_probs)

        for target_key, target_display in TARGET_BOOKS.items():
            if target_key not in books:
                continue
            target_odds = books[target_key]
            for side_name, true_prob in [(side_a_name, fair_p_a), (side_b_name, fair_p_b)]:
                if side_name in target_odds:
                    odds = target_odds[side_name]
                    b = american_to_decimal_net(odds)
                    ev = (true_prob * b) - (1.0 - true_prob)

                    if ev > 0.015:  # +1.5% edge threshold
                        found += 1
                        kelly = calculate_kelly(true_prob, odds, fraction=0.25)
                        stake_pct = min(kelly, 0.05)
                        cash_stake = round(bankroll * stake_pct, 2)

                        line_str = f" ({line_val})" if line_val != "ML" else ""
                        print(f"🔥 [+EV ALERT] {matchup}")
                        print(f"   Market:          {market_label.upper()}")
                        print(f"   Sportsbook:      {target_display}")
                        print(f"   Recommendation:  {side_name}{line_str} @ {odds:+d}")
                        print(f"   Consensus Prob:  {true_prob * 100:.2f}%")
                        print(f"   Expected Value:  +{ev * 100:.2f}%")
                        print(f"   Kelly Stake:     ${cash_stake:.2f} ({stake_pct * 100:.1f}%)\n")
    return found

# ==========================================================
# 2. SCAN BROAD GAME MAINLINES (NFL, NCAAF, NBA)
# ==========================================================

def scan_broad_boards(bankroll: float = 1000.0):
    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {"apiKey": API_KEY, "regions": REGIONS, "markets": MAIN_MARKETS, "oddsFormat": "american"}
        res = requests.get(url, params=params)
        if res.status_code != 200:
            continue

        games = res.json()
        print(f"\nScanning {sport.upper()} ({len(games)} games)...")
        alerts = 0

        for game in games:
            matchup = f"{game['away_team']} @ {game['home_team']}"
            market_data = {"h2h": defaultdict(dict), "spreads": defaultdict(dict), "totals": defaultdict(dict)}

            for book in game.get("bookmakers", []):
                b_name = book["key"]
                for m in book.get("markets", []):
                    m_key = m["key"]
                    if m_key not in market_data:
                        continue
                    for out in m.get("outcomes", []):
                        name = out["name"]
                        price = out["price"]
                        line_val = out.get("point", "ML")
                        if b_name not in market_data[m_key][line_val]:
                            market_data[m_key][line_val][b_name] = {}
                        market_data[m_key][line_val][b_name][name] = price

            for m_key in ["h2h", "spreads", "totals"]:
                alerts += evaluate_line_offers(matchup, m_key, market_data[m_key], bankroll)

# ==========================================================
# 3. SCAN TARGETED PLAYER PROPS (CONSERVES QUOTA)
# ==========================================================

def scan_game_player_props(sport: str, event_id: str, matchup_label: str, prop_markets: list, bankroll: float = 1000.0):
    """
    Pulls player prop lines for a single high-profile game.
    Example prop_markets: ['player_pass_yds', 'player_points', 'player_assists']
    """
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": ",".join(prop_markets),
        "oddsFormat": "american"
    }
    res = requests.get(url, params=params)
    if res.status_code != 200:
        return

    data = res.json()
    prop_data = defaultdict(lambda: defaultdict(dict))

    for book in data.get("bookmakers", []):
        b_name = book["key"]
        for m in book.get("markets", []):
            m_key = m["key"]
            for out in m.get("outcomes", []):
                # Outcomes for props have 'description' (Player Name) and 'name' (Over/Under)
                player_name = out.get("description", "Player")
                over_under = out.get("name")
                price = out.get("price")
                point = out.get("point")

                identifier = f"{player_name} - {m_key} ({point})"
                if b_name not in prop_data[identifier][point]:
                    prop_data[identifier][point][b_name] = {}
                prop_data[identifier][point][b_name][over_under] = price

    for identifier, lines in prop_data.items():
        evaluate_line_offers(f"{matchup_label} [{identifier}]", "PLAYER PROP", lines, bankroll)

if __name__ == "__main__":
    scan_broad_boards(bankroll=1000.0)