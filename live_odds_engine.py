import requests

# -------------------------------------------------------------
# PASTE YOUR FREE KEY FROM THE-ODDS-API.COM HERE
# -------------------------------------------------------------
API_KEY = "89c1a3d5b262f10b1df6230a275f75eb"

SPORT = "basketball_nba"
REGIONS = "us"
MARKETS = "h2h"  # 'h2h' (Moneyline), 'totals' (Over/Under), or 'spreads'

def american_to_prob(odds: int) -> float:
    """Converts American odds to raw implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)

def american_to_decimal_net(odds: int) -> float:
    """Converts American odds to net profit per dollar staked."""
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)

def calculate_kelly(true_prob: float, odds: int, fraction: float = 0.25) -> float:
    b = american_to_decimal_net(odds)
    q = 1.0 - true_prob
    f_star = (b * true_prob - q) / b
    return max(0.0, f_star * fraction)

def scan_live_markets(bankroll: float = 1000.0):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "american"
    }

    print("[1/2] Connecting to live sportsbook feeds (DraftKings, FanDuel, BetMGM)...")
    res = requests.get(url, params=params)

    if res.status_code != 200:
        print(f"Error fetching odds: {res.status_code} - {res.text}")
        return

    games = res.json()
    remaining = res.headers.get("x-requests-remaining", "N/A")
    print(f"[2/2] Ingested {len(games)} live upcoming games. (Monthly API credits left: {remaining})\n")

    found_bets = 0

    for game in games:
        home = game["home_team"]
        away = game["away_team"]
        start_time = game["commence_time"]

        # Track consensus across all sharp & retail books
        fair_probs_home = []
        fair_probs_away = []
        books_data = {}

        for book in game.get("bookmakers", []):
            book_name = book["key"]
            market = next((m for m in book["markets"] if m["key"] == MARKETS), None)
            if not market:
                continue

            outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
            if home in outcomes and away in outcomes:
                p_h = american_to_prob(outcomes[home])
                p_a = american_to_prob(outcomes[away])

                # Devig the pair (multiplicative devigging)
                fair_h = p_h / (p_h + p_a)
                fair_a = p_a / (p_h + p_a)

                fair_probs_home.append(fair_h)
                fair_probs_away.append(fair_a)
                books_data[book_name] = outcomes

        if not fair_probs_home:
            continue

        # True consensus probability = consensus across all participating books
        consensus_p_home = sum(fair_probs_home) / len(fair_probs_home)
        consensus_p_away = sum(fair_probs_away) / len(fair_probs_away)

        # Inspect specific retail books (DraftKings / FanDuel) for +EV pricing discrepancies
        for target_book in ["draftkings", "fanduel"]:
            if target_book not in books_data:
                continue

            book_odds = books_data[target_book]
            for team, true_prob in [(home, consensus_p_home), (away, consensus_p_away)]:
                if team in book_odds:
                    odds = book_odds[team]
                    b = american_to_decimal_net(odds)
                    ev = (true_prob * b) - (1.0 - true_prob)

                    # Flag if expected value > 1.5% edge
                    if ev > 0.015:
                        found_bets += 1
                        kelly_stake = calculate_kelly(true_prob, odds, fraction=0.25)
                        stake_pct = min(kelly_stake, 0.05)
                        stake_cash = bankroll * stake_pct

                        print(f"🔥 [+EV ALERT] {away} @ {home} ({start_time})")
                        print(f"   Sportsbook:      {target_book.upper()}")
                        print(f"   Recommended Bet: {team} ({odds:+d})")
                        print(f"   Consensus Prob:  {true_prob * 100:.2f}%")
                        print(f"   Expected Value:  +{ev * 100:.2f}%")
                        print(f"   Kelly Wager:     ${stake_cash:.2f} ({stake_pct * 100:.1f}% of ${bankroll:.2f})\n")

    if found_bets == 0:
        print("Scanned all live boards: No +EV pricing inefficiencies found at this moment.")

if __name__ == "__main__":
    scan_live_markets(bankroll=1000.0)