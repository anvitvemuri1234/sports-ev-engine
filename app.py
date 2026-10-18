import os
import requests
import pandas as pd
import streamlit as st
from collections import defaultdict

# Page configuration
st.set_page_config(
    page_title="Quantitative +EV Sports Engine",
    page_icon="⚡",
    layout="wide"
)

# ---------------------------------------------------------
# HELPER MATH FUNCTIONS
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# SIDEBAR CONTROLS
# ---------------------------------------------------------
st.sidebar.header("⚙️ Scanner Settings")

# Check if an admin key exists in secrets/env as an optional fallback
default_key = ""
try:
    if "ODDS_API_KEY" in st.secrets:
        default_key = st.secrets["ODDS_API_KEY"]
except Exception:
    default_key = os.getenv("ODDS_API_KEY", "")

# Allow the user to input their own key (masks input like a password)
api_key = st.sidebar.text_input(
    "Enter Your The Odds API Key",
    value=default_key,
    type="password",
    help="Paste your free API key from https://the-odds-api.com"
)

st.sidebar.caption("👉 Need a key? Get 500 free requests/month at [the-odds-api.com](https://the-odds-api.com).")

selected_sports = st.sidebar.multiselect(
    "Select Leagues",
    options=["basketball_nba", "americanfootball_nfl", "americanfootball_ncaaf"],
    default=["basketball_nba", "americanfootball_nfl"],
    format_func=lambda s: {"basketball_nba": "NBA", "americanfootball_nfl": "NFL", "americanfootball_ncaaf": "College Football"}.get(s, s)
)

bankroll = st.sidebar.number_input("Total Bankroll ($)", min_value=100.0, value=1000.0, step=50.0)
min_edge_pct = st.sidebar.slider("Minimum +EV Edge (%)", min_value=0.5, max_value=8.0, value=1.5, step=0.1)
kelly_mult = st.sidebar.selectbox("Kelly Fraction", options=[0.125, 0.25, 0.5], index=1, format_func=lambda x: f"{x}x (Fractional Kelly)")

# ---------------------------------------------------------
# MAIN DASHBOARD INTERFACE
# ---------------------------------------------------------
st.title("⚡ Quantitative +EV & Kelly Betting Scanner")
st.markdown("""
Identifies positive expected value ($+EV$) pricing discrepancies on **DraftKings, FanDuel, BetMGM, Caesars, and BetRivers** 
relative to market consensus, and computes optimal position sizes using **Fractional Kelly**.
""")

if not api_key.strip():
    st.info("👋 **Welcome!** To scan live market odds, please paste your **The Odds API Key** in the sidebar on the left.")
    st.markdown("""
    1. Grab a free API key at **[the-odds-api.com](https://the-odds-api.com)** (no credit card required, 500 free requests/month).
    2. Paste it into the sidebar input field.
    3. Choose your leagues and hit **Scan Live Sportsbooks Now**!
    """)
    st.stop()

scan_button = st.button("🚀 Scan Live Sportsbooks Now", type="primary")

if scan_button:
    results = []
    total_games_scanned = 0
    quota_remaining = "N/A"

    with st.spinner("Fetching live boards & devigging market consensus..."):
        for sport in selected_sports:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
            params = {
                "apiKey": api_key,
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american"
            }
            try:
                res = requests.get(url, params=params, timeout=10)
                if res.status_code != 200:
                    st.error(f"Error scanning {sport}: {res.status_code} - {res.text}")
                    continue

                games = res.json()
                total_games_scanned += len(games)
                quota_remaining = res.headers.get("x-requests-remaining", quota_remaining)

                for game in games:
                    matchup = f"{game['away_team']} @ {game['home_team']}"
                    sport_label = "NBA" if "nba" in sport else ("NCAAF" if "ncaaf" in sport else "NFL")

                    parsed_markets = {
                        "SPREAD": defaultdict(dict),
                        "TOTAL": defaultdict(dict),
                        "MONEYLINE": defaultdict(dict)
                    }

                    for book in game.get("bookmakers", []):
                        b_key = book["key"]
                        for m in book.get("markets", []):
                            m_key = m["key"]
                            label_key = "MONEYLINE" if m_key == "h2h" else ("SPREAD" if m_key == "spreads" else "TOTAL")
                            
                            for out in m.get("outcomes", []):
                                line_val = out.get("point", "ML")
                                if b_key not in parsed_markets[label_key][line_val]:
                                    parsed_markets[label_key][line_val][b_key] = {}
                                parsed_markets[label_key][line_val][b_key][out["name"]] = out["price"]

                    # Devig consensus and spot discrepancies
                    for m_label, lines_dict in parsed_markets.items():
                        for line_val, books in lines_dict.items():
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
                                side_a_probs.append(p_a / (p_a + p_b))
                                side_b_probs.append(p_b / (p_a + p_b))

                            if not side_a_probs:
                                continue

                            true_p_a = sum(side_a_probs) / len(side_a_probs)
                            true_p_b = sum(side_b_probs) / len(side_b_probs)

                            for target_key, target_disp in TARGET_BOOKS.items():
                                if target_key not in books:
                                    continue
                                target_odds = books[target_key]
                                for pick_name, true_prob in [(side_a_name, true_p_a), (side_b_name, true_p_b)]:
                                    if pick_name in target_odds:
                                        odds = target_odds[pick_name]
                                        b = american_to_decimal_net(odds)
                                        ev = (true_prob * b) - (1.0 - true_prob)

                                        if (ev * 100) >= min_edge_pct:
                                            kelly = calculate_kelly(true_prob, odds, fraction=kelly_mult)
                                            stake_pct = min(kelly, 0.05)
                                            stake_cash = round(bankroll * stake_pct, 2)
                                            line_str = f" {line_val:+g}" if isinstance(line_val, (int, float)) and line_val != 0 else (f" {line_val}" if line_val != "ML" else "")

                                            results.append({
                                                "League": sport_label,
                                                "Matchup": matchup,
                                                "Market": m_label,
                                                "Sportsbook": target_disp,
                                                "Recommended Pick": f"{pick_name}{line_str}",
                                                "Odds": f"{odds:+d}",
                                                "Consensus Fair Prob": f"{true_prob * 100:.1f}%",
                                                "+EV Edge": round(ev * 100, 2),
                                                "Kelly Wager ($)": stake_cash,
                                                "Stake (%)": f"{stake_pct * 100:.1f}%"
                                            })
            except Exception as e:
                st.error(f"Error: {e}")

    # Metrics row
    col1, col2, col3 = st.columns(3)
    col1.metric("Upcoming Games Evaluated", total_games_scanned)
    col2.metric("+EV Bets Identified", len(results))
    col3.metric("API Requests Left", quota_remaining)

    st.divider()

    if results:
        df = pd.DataFrame(results)
        df = df.sort_values(by="+EV Edge", ascending=False).reset_index(drop=True)

        st.subheader("🎯 Actionable Value Bets")
        
        # Color coding for high EV
        st.dataframe(
            df.style.format({"+EV Edge": "+{:.2f}%", "Kelly Wager ($)": "${:.2f}"}),
            use_container_width=True
        )
    else:
        st.info("No actionable opportunities met your edge criteria across the scanned markets at this moment.")