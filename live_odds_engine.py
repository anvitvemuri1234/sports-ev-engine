import os
import requests
from collections import defaultdict

# -------------------------------------------------------------
# SET YOUR API KEY
# Recommendation: set environment variable ODDS_API_KEY, or paste string directly
# -------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "PASTE_YOUR_API_KEY_HERE")

SPORT = "basketball_nba"
REGIONS = "us"
# Multiple markets in one request: h2h (moneyline), spreads, totals
MARKETS = "h2h,spreads,totals"

def american_to_prob(odds: int) -> float:
    """Converts American odds to raw implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)

def american_to_decimal_net(odds: int) -> float:
    """Returns profit per \$1 staked ('b' in Kelly formula)."""
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)

def calculate_kelly(true_prob: float, odds: int, fraction: float = 0.25) -> float:
    """Computes Fractional Kelly Criterion stake percentage."""
    b = american_to_decimal_net(odds)
    q = 1.0 - true_prob
    f_star = (b * true_prob - q) / b
    return max(0.0, f_star * fraction)

def evaluate_market_consensus(market_key: str, offers_by_line: dict, bankroll: float):
    """
    Evaluates consensus across all books for a specific line value.
    Flags retail discrepancies on DraftKings and FanDuel.
    """
    found_count = 0
    
    for line_val, books in offers_by_line.items():
        if len(books) < 3:
            continue  # Need at least 3 books offering the identical line for consensus

        side_a_probs, side_b_probs = [], []
        side_a_name, side_b_name = None, None

        # 1. Devig each bookmaker's two-way offer
        for b_name, pair in books.items():
            names = list(pair.keys())
            if len(names) != 2:
                continue
            
            side_a_name, side_b_name = names[0], names[1]
            p_a = american_to_prob(pair[side_a_name])
            p_b = american_to_prob(pair[side_b_name])

            # Multiplicative fair probability
            fair_a = p_a / (p_a + p_b)
            fair_b = p_b / (p_a + p_b)

            side_a_probs.append(fair_a)
            side_b_probs.append(fair_b)

        if not side_a_probs:
            continue

        true_prob_a = sum(side_a_probs) / len(side_a_probs)
        true_prob_b = sum(side_b_probs) / len(side_b_probs)

        # 2. Check DraftKings & FanDuel against the true consensus
        for target_book in ["draftkings", "fanduel"]:
            if target_book not in books:
                continue

            target_odds = books[target_book]
            for side_name, true_prob in [(side_a_name, true_prob_a), (side_b_name, true_prob_b)]:
                if side_name in target_odds:
                    odds = target_odds[side_name]
                    b = american_to_decimal_net(odds)
                    ev = (true_prob * b) - (1.0 - true_prob)

                    # Flag bets with edge > 1.5%
                    if ev > 0.015:
                        found_count += 1
                        kelly_stake = calculate_kelly(true_prob, odds, fraction=0.25)
                        stake_pct = min(kelly_stake, 0.05)
                        cash_stake = round(bankroll * stake_pct, 2)

                        line_str = f" ({line_val})" if line_val != "ML" else ""
                        print(f"🔥 [+EV ALERT] Market: {market_key.upper()}")
                        print(f"   Sportsbook:      {target_book.upper()}")
                        print(f"   Pick:            {side_name}{line_str} @ {odds:+d}")
                        print(f"   Consensus Prob:  {true_prob * 100:.2f}%")
                        print(f"   Expected Value:  +{ev * 10