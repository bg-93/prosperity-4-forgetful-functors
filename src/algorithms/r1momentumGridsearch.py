import pandas as pd
import numpy as np
from collections import deque
from itertools import product

# ---------- LOAD DATA ----------
df = pd.read_csv("../../data/ROUND_1/prices_round_1_day_0.csv", sep=";")  # change if needed
df = df[df["product"] == "INTARIAN_PEPPER_ROOT"].copy()

# drop bad rows
df = df[df["mid_price"] > 0]

# ---------- PARAMETERS ----------
LIMIT = 80
WINDOW = 10

# grid to search
momentum_weights = [0.2, 0.4, 0.6]
inventory_weights = [0.8, 1.2, 1.6]
take_edges = [1, 2, 3]
make_edges = [0, 1]

# ---------- CORE BACKTEST ----------
def run_backtest(momentum_w, inventory_w, take_edge, make_edge):
    position = 0
    cash = 0

    history = deque(maxlen=WINDOW)

    for _, row in df.iterrows():
        best_bid = row["bid_price_1"]
        best_ask = row["ask_price_1"]

        if best_bid == 0 or best_ask == 0:
            continue

        mid = (best_bid + best_ask) / 2

        history.append(mid)

        if len(history) < 5:
            continue

        # momentum
        momentum = history[-1] - history[0]

        # fair value
        fair = (
            mid
            + momentum_w * momentum
            - inventory_w * (position / LIMIT)
        )

        # ---------- TAKE LOGIC ----------
        # buy from ask
        if best_ask <= fair - take_edge:
            qty = min(10, LIMIT - position)
            if qty > 0:
                position += qty
                cash -= best_ask * qty

        # sell into bid
        if best_bid >= fair + take_edge:
            qty = min(10, LIMIT + position)
            if qty > 0:
                position -= qty
                cash += best_bid * qty

        # ---------- PASSIVE (VERY SIMPLIFIED) ----------
        # small drift capture
        if position < LIMIT:
            if mid < fair:
                qty = 2
                position += qty
                cash -= (best_bid + make_edge) * qty

        if position > -LIMIT:
            if mid > fair:
                qty = 2
                position -= qty
                cash += (best_ask - make_edge) * qty

    # mark to market
    final_mid = (df.iloc[-1]["bid_price_1"] + df.iloc[-1]["ask_price_1"]) / 2
    pnl = cash + position * final_mid

    return pnl


# ---------- GRID SEARCH ----------
results = []

for mw, iw, te, me in product(momentum_weights, inventory_weights, take_edges, make_edges):
    pnl = run_backtest(mw, iw, te, me)
    results.append({
        "momentum": mw,
        "inventory": iw,
        "take_edge": te,
        "make_edge": me,
        "pnl": pnl
    })

results_df = pd.DataFrame(results)
results_df = results_df.sort_values("pnl", ascending=False)

print(results_df.head(10))
