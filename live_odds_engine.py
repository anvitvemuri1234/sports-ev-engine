import os
import requests
from collections import defaultdict

# -------------------------------------------------------------
# API CONFIGURATION
# -------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "89c1a3d5b262f10b1df6230a275f75eb")

SPORTS = ["americanfootball_nfl", "basketball_nba"]
REGIONS = "us"
MARKETS = "h2h,spreads,totals"

# Books to evaluate for mispriced lines
TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "betrivers": "BetRivers"
}

def american_to_prob(odds: int) -> float:
    """Converts American odds to raw implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)

def american_to_decimal_net(odds: int) -> float:
    """Returns net profit multiplier per dollar staked."""
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)

def calculate_kelly(true_prob: float, odds: int, fraction: float = 0.25) -> float:
    """Computes Fractional Kelly Criterion stake percentage."""
    b = american_to_decimal_net(odds)
    q = 1.0 - true_prob
    f_star = (b * true_prob - q) / b
    return max(0.0, f_star * fraction)

def evaluate_market_consensus(sport_label: str, matchup_name: str, market_key: str, offers_by_line: dict, bankroll: float):
    found_count = 0
    
    for line_val, books in offers_by_line.items():
        # Require at least 3 books offering the identical line to establish consensus
        if len(books) < 3:
            continue

        side_a_probs, side_b_probs = [], []
        side_a_name, side_b_name = None, None

        # 1. Multiplicative Devig for each book's market pair
        for b_name, pair in books.items():
            names = list(pair.keys())
            if len(names) != 2:
                continue
            
            side_a_name, side_b_name = names[0], names[1]
            p_a = american_to_prob(pair[side_a_name])
            p_b = american_to_prob(pair[side_b_name])

            fair_a = p_a / (p_a + p_b)
            fair_b = p_b / (p_a + p_b)

            side_a_probs.append(fair_a)
            side_b_probs.append(fair_b)

        if not side_a_probs:
            continue

        true_prob_a = sum(side_a_probs) / len(side_a_probs)
        true_prob_b = sum(side_b_probs) / len(side_b_probs)

        # 2. Check each target sportsbook against market consensus
        for target_key, target_display in TARGET_BOOKS.items():
            if target_key not in books:
                continue

            target_odds = books[target_key]
            for side_name, true_prob in [(side_a_name, true_prob_a), (side_b_name, true_prob_b)]:
                if side_name in target_odds:
                    odds = target_odds[side_name]
                    b = american_to_decimal_net(odds)
                    ev = (true_prob * b) - (1.0 - true_prob)

                    # Strict filter: Edge must be greater than +1.5%
                    if ev > 0.015:
                        found_count += 1
                        kelly_stake = calculate_kelly(true_prob, odds, fraction=0.25)
                        stake_pct = min(kelly_stake, 0.05)
                        cash_stake = round(bankroll * stake_pct, 2)

                        line_str = f" ({line_val:+g})" if isinstance(line_val, (int, float)) and line_val != 0 else (f" ({line_val})" if line_val != "ML" else "")
                        print(f"🔥 [+EV ALERT] [{sport_label}] {matchup_name}")
                        print(f"   Market:          {market_key.upper()}")
                        print(f"   Sportsbook:      {target_display}")
                        print(f"   Recommended:     {side_name}{line_str} @ {odds:+d}")
                        print(f"   Consensus Prob:  {true_prob * 100:.2f}%")
                        print(f"   Expected Value:  +{ev * 100:.2f}%")
                        print(f"   Kelly Stake:     ${cash_stake:.2f} ({stake_pct * 100:.1f}%)\n")

    return found_count

def scan_sports_boards(bankroll: float = 1000.0):
    total_alerts = 0

    for sport in SPORTS:
        label = "NFL" if "nfl" in sport else "NBA"
        print(f"\n==========================================")
        print(f"  SCANNING LIVE {label} MARKETS ({MARKETS})")
        print(f"==========================================")
        
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": API_KEY,
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": "american"
        }

        res = requests.get(url, params=params)
        if res.status_code != 200:
            print(f"Error fetching {label}: {res.status_code} - {res.text}")
            continue

        games = res.json()
        remaining = res.headers.get("x-requests-remaining", "N/A")
        print(f"Loaded {len(games)} {label} games. (API requests remaining this month: {remaining})")

        sport_alerts = 0
        for game in games:
            home = game["home_team"]
            away = game["away_team"]
            matchup = f"{away} @ {home}"

            market_data = {
                "h2h": defaultdict(dict),
                "spreads": defaultdict(dict),
                "totals": defaultdict(dict),
            }

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
                sport_alerts += evaluate_market_consensus(label, matchup, m_key, market_data[m_key], bankroll)

        total_alerts += sport_alerts
        if sport_alerts == 0:
            print(f"No +EV edges >= 1.5% found across {label} at this moment.")

    print(f"\n--- SCAN FINISHED: {total_alerts} TOTAL ACTIONABLE EDGES IDENTIFIED ---")

if __name__ == "__main__":
    scan_sports_boards(bankroll=1000.0)

    #hello