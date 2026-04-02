import io
from typing import List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Prosperity Order Book Explorer", layout="wide")

REQUIRED_COLUMNS = {
    "day", "timestamp", "product",
    "bid_price_1", "bid_volume_1",
    "bid_price_2", "bid_volume_2",
    "bid_price_3", "bid_volume_3",
    "ask_price_1", "ask_volume_1",
    "ask_price_2", "ask_volume_2",
    "ask_price_3", "ask_volume_3",
    "mid_price", "profit_and_loss",
}

PRICE_COLS = [f"bid_price_{i}" for i in range(1, 4)] + [f"ask_price_{i}" for i in range(1, 4)]
VOLUME_COLS = [f"bid_volume_{i}" for i in range(1, 4)] + [f"ask_volume_{i}" for i in range(1, 4)]


def load_csv(file) -> pd.DataFrame:
    df = pd.read_csv(file, sep=";")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    for col in ["day", "timestamp", "mid_price", "profit_and_loss", *PRICE_COLS, *VOLUME_COLS]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values(["product", "day", "timestamp"]).reset_index(drop=True)
    df["time_index"] = df["day"].astype(str) + " | " + df["timestamp"].astype(int).astype(str)
    return engineer_features(df)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["best_bid"] = out["bid_price_1"]
    out["best_ask"] = out["ask_price_1"]
    out["spread"] = out["best_ask"] - out["best_bid"]
    out["microprice"] = (
        out["best_ask"] * out["bid_volume_1"].fillna(0)
        + out["best_bid"] * out["ask_volume_1"].fillna(0)
    ) / (out["bid_volume_1"].fillna(0) + out["ask_volume_1"].fillna(0)).replace(0, np.nan)
    out["total_bid_volume"] = out[[f"bid_volume_{i}" for i in range(1, 4)]].fillna(0).sum(axis=1)
    out["total_ask_volume"] = out[[f"ask_volume_{i}" for i in range(1, 4)]].fillna(0).sum(axis=1)
    denom = (out["total_bid_volume"] + out["total_ask_volume"]).replace(0, np.nan)
    out["imbalance"] = (out["total_bid_volume"] - out["total_ask_volume"]) / denom
    out["mid_return"] = out.groupby("product")["mid_price"].pct_change()
    out["mid_change"] = out.groupby("product")["mid_price"].diff()
    return out


def line_chart(df: pd.DataFrame, y_cols: List[str], title: str) -> go.Figure:
    fig = go.Figure()
    for col in y_cols:
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df[col], mode="lines", name=col.replace("_", " ").title()
        ))
    fig.update_layout(title=title, xaxis_title="Timestamp", yaxis_title="Value", height=420)
    return fig


def level_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for i in range(1, 4):
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df[f"bid_price_{i}"], mode="markers",
            marker={"size": np.clip(df[f"bid_volume_{i}"].fillna(0) * 2 + 4, 4, 26)},
            name=f"Bid L{i}",
            customdata=np.stack([df[f"bid_volume_{i}"].fillna(0)], axis=-1),
            hovertemplate="Timestamp=%{x}<br>Price=%{y}<br>Volume=%{customdata[0]}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df[f"ask_price_{i}"], mode="markers",
            marker={"size": np.clip(df[f"ask_volume_{i}"].fillna(0) * 2 + 4, 4, 26)},
            name=f"Ask L{i}",
            customdata=np.stack([df[f"ask_volume_{i}"].fillna(0)], axis=-1),
            hovertemplate="Timestamp=%{x}<br>Price=%{y}<br>Volume=%{customdata[0]}<extra></extra>",
        ))
    fig.update_layout(
        title="Order Book Levels Over Time",
        xaxis_title="Timestamp",
        yaxis_title="Price",
        height=520,
    )
    return fig


def depth_chart(row: pd.Series) -> go.Figure:
    bid_prices, bid_sizes, ask_prices, ask_sizes = [], [], [], []
    for i in range(3, 0, -1):
        p, v = row.get(f"bid_price_{i}"), row.get(f"bid_volume_{i}")
        if pd.notna(p) and pd.notna(v):
            bid_prices.append(p)
            bid_sizes.append(v)
    for i in range(1, 4):
        p, v = row.get(f"ask_price_{i}"), row.get(f"ask_volume_{i}")
        if pd.notna(p) and pd.notna(v):
            ask_prices.append(p)
            ask_sizes.append(v)

    bid_cum = np.cumsum(bid_sizes)
    ask_cum = np.cumsum(ask_sizes)

    fig = go.Figure()
    if len(bid_prices):
        fig.add_trace(go.Scatter(x=bid_prices, y=bid_cum, mode="lines+markers", name="Bid Depth", line_shape="hv"))
    if len(ask_prices):
        fig.add_trace(go.Scatter(x=ask_prices, y=ask_cum, mode="lines+markers", name="Ask Depth", line_shape="hv"))

    fig.update_layout(
        title=f"Depth Snapshot | day={int(row['day'])}, timestamp={int(row['timestamp'])}",
        xaxis_title="Price",
        yaxis_title="Cumulative Volume",
        height=420,
    )
    return fig


def order_table(row: pd.Series) -> pd.DataFrame:
    records = []
    for i in range(3, 0, -1):
        records.append({
            "side": "bid",
            "level": i,
            "price": row.get(f"bid_price_{i}"),
            "volume": row.get(f"bid_volume_{i}"),
        })
    for i in range(1, 4):
        records.append({
            "side": "ask",
            "level": i,
            "price": row.get(f"ask_price_{i}"),
            "volume": row.get(f"ask_volume_{i}"),
        })
    return pd.DataFrame(records)


st.title("Prosperity Order Book Explorer")
st.write(
    "Upload a Prosperity-style price history CSV to inspect order book levels, spread, imbalance, and depth snapshots."
)

uploaded = st.file_uploader("Drop a CSV file here", type=["csv"])

sample_path = "prices_round_0_day_-1.csv"
if uploaded is None:
    try:
        with open(sample_path, "rb") as f:
            sample_bytes = f.read()
        st.info("No file uploaded yet, so the bundled sample file is loaded.")
        df = load_csv(io.BytesIO(sample_bytes))
    except FileNotFoundError:
        st.warning("Upload a CSV to begin.")
        st.stop()
else:
    df = load_csv(uploaded)

products = sorted(df["product"].dropna().unique().tolist())
selected_product = st.sidebar.selectbox("Product", products)
product_df = df[df["product"] == selected_product].copy()

min_ts, max_ts = int(product_df["timestamp"].min()), int(product_df["timestamp"].max())
ts_range = st.sidebar.slider("Timestamp range", min_ts, max_ts, (min_ts, max_ts))
product_df = product_df[(product_df["timestamp"] >= ts_range[0]) & (product_df["timestamp"] <= ts_range[1])]

st.sidebar.markdown("### View options")
show_raw = st.sidebar.checkbox("Show raw filtered table", value=False)

metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric("Rows", f"{len(product_df):,}")
metric2.metric("Average spread", f"{product_df['spread'].mean():.2f}")
metric3.metric("Average imbalance", f"{product_df['imbalance'].mean():.3f}")
metric4.metric("Latest mid price", f"{product_df['mid_price'].iloc[-1]:.2f}")

left, right = st.columns(2)
with left:
    st.plotly_chart(
        line_chart(product_df, ["mid_price", "microprice"], f"{selected_product}: Mid Price vs Microprice"),
        use_container_width=True,
    )
with right:
    st.plotly_chart(
        line_chart(product_df, ["spread", "imbalance"], f"{selected_product}: Spread and Imbalance"),
        use_container_width=True,
    )

st.plotly_chart(level_scatter(product_df), use_container_width=True)

st.subheader("Order Book Snapshot")
snapshot_index = st.slider(
    "Choose a row from the filtered data",
    min_value=0,
    max_value=max(len(product_df) - 1, 0),
    value=max(len(product_df) - 1, 0),
)
row = product_df.iloc[snapshot_index]

snap_left, snap_right = st.columns([1.2, 1])
with snap_left:
    st.plotly_chart(depth_chart(row), use_container_width=True)
with snap_right:
    st.dataframe(order_table(row), use_container_width=True, hide_index=True)
    st.markdown(
        f"""
        **Snapshot stats**
        - Day: `{int(row['day'])}`
        - Timestamp: `{int(row['timestamp'])}`
        - Best bid: `{row['best_bid']}`
        - Best ask: `{row['best_ask']}`
        - Spread: `{row['spread']}`
        - Mid price: `{row['mid_price']}`
        - Imbalance: `{row['imbalance']:.3f}`
        """
    )

st.subheader("Useful feature ideas")
st.markdown(
    """
    - **Mid price / microprice**: baseline fair value proxies.
    - **Spread**: tells you how expensive it is to cross the market.
    - **Order book imbalance**: measures whether bids or asks dominate.
    - **Depth chart**: shows how much liquidity sits near the touch.
    - **Level scatter**: reveals how the ladder moves through time.
    - **Returns / price changes**: helps spot momentum or mean reversion.
    """
)

if show_raw:
    st.subheader("Filtered raw data")
    st.dataframe(product_df, use_container_width=True)
