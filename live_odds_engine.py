import os
import requests
from collections import defaultdict

# -------------------------------------------------------------
# API CONFIGURATION
# -------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "PASTE_YOUR_API_KEY_HERE")

SPORTS = ["americanfootball_nfl", "basketball_nba"]
REGIONS = "us"
# Explicitly pulling all 3 primary markets
MARKETS = "h2h,spreads,totals"

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

def evaluate_market_group(sport_label: str, matchup: str, market_name: str, lines_dict: dict, bankroll: float):
    alerts = 0

    for line_val, books in lines_dict.items():
        # Require at least 2 books on this line to establish a baseline
        if len(books) < 2:
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

            # Devigging formula: remove overround
            fair_a = p_a / (p_a + p_b)
            fair_b = p_b / (p_a + p_b)

            side_a_probs.append(fair_a)
            side_b_probs.append(fair_b)

        if not side_a_probs:
            continue

        true_prob_a = sum(side_a_probs) / len(side_a_probs)
        true_prob_b = sum(side_b_probs) / len(side_b_probs)

        # Check for edges across your target books
        for target_key, target_display in TARGET_BOOKS.items():
            if target_key not in books:
                continue

            target_odds = books[target_key]
            for side_name, true_prob in [(side_a_name, true_prob_a), (side_b_name, true_prob_b)]:
                if side_name in target_odds:
                    odds = target_odds[side_name]
                    b = american_to_decimal_net(odds)
                    ev = (true_prob * b) - (1.0 - true_prob)

                    # Strict +1.5% edge filter
                    if ev > 0.015:
                        alerts += 1
                        kelly = calculate_kelly(true_prob, odds, fraction=0.25)
                        stake_pct = min(kelly, 0.05)
                        cash_stake = round(bankroll * stake_pct, 2)

                        # Format line display for spreads and totals
                        line_str = f" {line_val:+g}" if isinstance(line_val, (int, float)) and line_val != 0 else (f" {line_val}" if line_val != "ML" else "")
                        
                        print(f"🔥 [+EV ALERT] [{sport_label}] {matchup}")
                        print(f"   Market:          {market_name.upper()}")
                        print(f"   Sportsbook:      {target_display}")
                        print(f"   Pick:            {side_name}{line_str} @ {odds:+d}")
                        print(f"   Consensus Prob:  {true_prob * 100:.2f}%")
                        print(f"   Expected Value:  +{ev * 100:.2f}%")
                        print(f"   Kelly Stake:     ${cash_stake:.2f} ({stake_pct * 100:.1f}%)\n")
    return alerts

def scan_all_markets(bankroll: float = 1000.0):
    for sport in SPORTS:
        label = "NFL" if "nfl" in sport else "NBA"
        print(f"\n==========================================")
        print(f"  SCANNING {label} (SPREADS, TOTALS, ML)")
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
            print(f"API Error ({res.status_code}): {res.text}")
            continue

        games = res.json()
        remaining = res.headers.get("x-requests-remaining", "N/A")
        print(f"Loaded {len(games)} games. (Requests left this month: {remaining})")

        found = 0
        for game in games:
            matchup = f"{game['away_team']} @ {game['home_team']}"

            # Groupings: market_type -> line_value -> bookmaker -> {outcome: price}
            parsed_markets = {
                "h2h": defaultdict(dict),
                "spreads": defaultdict(dict),
                "totals": defaultdict(dict)
            }

            for book in game.get("bookmakers", []):
                b_name = book["key"]
                for m in book.get("markets", []):
                    m_key = m["key"]
                    if m_key not in parsed_markets:
                        continue

                    for out in m.get("outcomes", []):
                        name = out["name"]
                        price = out["price"]
                        # Grabs handicap point for spreads (e.g. -3.5) or over/under total (e.g. 45.5)
                        line_val = out.get("point", "ML")

                        if b_name not in parsed_markets[m_key][line_val]:
                            parsed_markets[m_key][line_val][b_name] = {}
                        parsed_markets[m_key][line_val][b_name][name] = price

            # Scan Spreads, Game Totals, and Moneyline
            found += evaluate_market_group(label, matchup, "SPREAD", parsed_markets["spreads"], bankroll)
            found += evaluate_market_group(label, matchup, "TOTAL (OVER/UNDER)", parsed_markets["totals"], bankroll)
            found += evaluate_market_group(label, matchup, "MONEYLINE", parsed_markets["h2h"], bankroll)

        if found == 0:
            print(f"No +EV spread, total, or moneyline edges found across {label} right now.")

if __name__ == "__main__":
    scan_all_markets(bankroll=1000.0)