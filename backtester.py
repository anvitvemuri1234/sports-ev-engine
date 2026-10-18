import math
import numpy as np
import scipy.stats as stats

# ==========================================================
# 1. CORE ODDS CONVERSION & KELLY CRITERION FORMULA
# ==========================================================

def american_to_net_odds(odds: int) -> float:
    """
    Returns net profit per $1 staked ('b' in Kelly formula).
    Example: +150 -> 1.50, -110 -> 0.909
    """
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)

def calculate_kelly(true_prob: float, american_odds: int, kelly_fraction: float = 0.25) -> float:
    """
    Calculates fractional Kelly stake percentage.
    Formula: f* = (b*p - q) / b
    """
    b = american_to_net_odds(american_odds)
    q = 1.0 - true_prob
    
    f_star = (b * true_prob - q) / b
    
    # If expected value is negative or zero, do not bet
    if f_star <= 0:
        return 0.0
    
    return f_star * kelly_fraction

# ==========================================================
# 2. STATISTICAL PROBABILITY ENGINE
# ==========================================================

def get_prop_probability(projected_mean: float, line: float, stat_type: str = "discrete") -> dict:
    """
    Calculates P(X > line) and P(X < line).
    - discrete: Poisson distribution (Rebounds, Assists, Steals, Blocks)
    - continuous: Normal distribution (Points, Passing Yards)
    """
    if stat_type == "discrete":
        # Poisson CDF gives P(X <= k)
        k = math.floor(line)
        p_under = stats.poisson.cdf(k, mu=projected_mean)
        p_over = 1.0 - p_under
    else:
        # Standard assumption: variance scale ~ 25% of the projected stat
        sigma = max(3.0, projected_mean * 0.25)
        p_under = stats.norm.cdf(line, loc=projected_mean, scale=sigma)
        p_over = 1.0 - p_under
        
    return {"over_prob": p_over, "under_prob": p_under}

# ==========================================================
# 3. BACKTESTING ENGINE
# ==========================================================

class PropBacktester:
    def __init__(self, initial_bankroll: float = 1000.0, kelly_fraction: float = 0.25):
        self.bankroll = initial_bankroll
        self.initial_bankroll = initial_bankroll
        self.history = [initial_bankroll]
        self.kelly_fraction = kelly_fraction
        self.bets_placed = 0
        self.wins = 0

    def evaluate_game(self, record: dict):
        player = record["player"]
        prop = record["prop"]
        line = record["line"]
        proj = record["proj"]
        actual = record["actual"]
        over_odds = record["over_odds"]
        under_odds = record["under_odds"]
        stat_type = record.get("type", "discrete")

        probs = get_prop_probability(proj, line, stat_type)

        # Calculate Kelly for both sides
        kelly_over = calculate_kelly(probs["over_prob"], over_odds, self.kelly_fraction)
        kelly_under = calculate_kelly(probs["under_prob"], under_odds, self.kelly_fraction)

        side, chosen_odds, stake_pct = None, 0, 0.0
        win = False

        if kelly_over > 0.01:
            side = "OVER"
            chosen_odds = over_odds
            stake_pct = min(kelly_over, 0.05)  # Cap maximum wager at 5% of bankroll
            win = (actual > line)
        elif kelly_under > 0.01:
            side = "UNDER"
            chosen_odds = under_odds
            stake_pct = min(kelly_under, 0.05)
            win = (actual < line)

        if not side:
            print(f"Skipping {player} {prop} (No +EV edge found)")
            return

        stake = round(self.bankroll * stake_pct, 2)
        b = american_to_net_odds(chosen_odds)
        self.bets_placed += 1

        if win:
            pnl = round(stake * b, 2)
            self.bankroll += pnl
            self.wins += 1
            outcome = f"WIN (+${pnl:.2f})"
        else:
            self.bankroll -= stake
            outcome = f"LOSS (-${stake:.2f})"

        self.history.append(self.bankroll)
        print(f"[{player} {prop} {line}] Pick: {side} ({chosen_odds:+d}) | Stake: ${stake:.2f} ({stake_pct*100:.1f}%) | Actual: {actual} -> {outcome}")

    def summary(self):
        print("\n" + "=" * 45)
        print("          BACKTEST PERFORMANCE SUMMARY        ")
        print("=" * 45)
        print(f"Initial Bankroll: ${self.initial_bankroll:.2f}")
        print(f"Final Bankroll:   ${self.bankroll:.2f}")
        total_roi = ((self.bankroll - self.initial_bankroll) / self.initial_bankroll) * 100
        print(f"Total Return:     {total_roi:+.2f}%")
        win_rate = (self.wins / self.bets_placed * 100) if self.bets_placed else 0
        print(f"Bets Placed:      {self.bets_placed}")
        print(f"Win Rate:         {win_rate:.1f}%")
        print("=" * 45)

# ==========================================================
# 4. RUN TEST
# ==========================================================

from data_loader import build_live_market_test_batch

if __name__ == "__main__":
    backtester = PropBacktester(initial_bankroll=1000.0, kelly_fraction=0.25)

    # Real active stars to test against live market lines
    sample_targets = [
        {"player": "Tyrese Haliburton", "opponent": "DET", "prop": "Assists", "line": 9.5, "over_odds": -115, "under_odds": -115},
        {"player": "Jayson Tatum", "opponent": "MIA", "prop": "Points", "line": 26.5, "over_odds": -110, "under_odds": -110},
        {"player": "Nikola Jokić", "opponent": "LAL", "prop": "Rebounds", "line": 12.5, "over_odds": -115, "under_odds": -115},
        {"player": "Victor Wembanyama", "opponent": "UTA", "prop": "Blocks", "line": 3.5, "over_odds": +115, "under_odds": -145},
        {"player": "Anthony Edwards", "opponent": "ORL", "prop": "Assists", "line": 5.5, "over_odds": -110, "under_odds": -110},
    ]

    print("\n[1/2] Connecting to Sleeper & NBA Stats to pull live player distributions...")
    live_test_data = build_live_market_test_batch(sample_targets)

    print(f"\n[2/2] Running Backtest on {len(live_test_data)} Live Market Scenarios...\n")
    for game in live_test_data:
        backtester.evaluate_game(game)

    backtester.summary()