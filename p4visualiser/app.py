
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="CSV Market Dashboard", layout="wide")


# ----------------------------
# 1) Data loading helpers
# ----------------------------
@st.cache_data
def read_csv_flexible(file_obj) -> pd.DataFrame:
    """
    Read a CSV that uses semicolons.
    Works with either an uploaded file object or a local file path.
    """
    return pd.read_csv(file_obj, sep=";")


def classify_dataframe(df: pd.DataFrame) -> str:
    """
    Identify whether a dataframe is a prices table or a trades table.
    """
    price_cols = {"product", "mid_price", "bid_price_1", "ask_price_1"}
    trade_cols = {"symbol", "price", "quantity"}

    if price_cols.issubset(df.columns):
        return "prices"
    if trade_cols.issubset(df.columns):
        return "trades"
    return "unknown"


def resolve_example_file_path(filename: str) -> Path:
    """Find an example CSV in likely data locations."""
    candidate_dirs = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent.parent / "data" / "TUTORIAL_ROUND_1",
        Path(__file__).resolve().parent.parent / "data",
    ]

    for base in candidate_dirs:
        candidate = base / filename
        if candidate.exists():
            return candidate

    return Path(filename)


def add_source_name(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    df = df.copy()
    df["source_file"] = source_name
    return df


@st.cache_data
def load_local_example_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load the example files if they exist beside this app.
    """
    candidate_files = [
        "prices_round_0_day_-1.csv",
        "prices_round_0_day_-2.csv",
        "trades_round_0_day_-1.csv",
        "trades_round_0_day_-2.csv",
    ]

    prices_dfs = []
    trades_dfs = []

    for filename in candidate_files:
        local_path = resolve_example_file_path(filename)
        if not local_path.exists():
            continue

        df = read_csv_flexible(local_path)
        df = add_source_name(df, str(local_path.name))

        kind = classify_dataframe(df)
        if kind == "prices":
            prices_dfs.append(df)
        elif kind == "trades":
            trades_dfs.append(df)

    prices = pd.concat(prices_dfs, ignore_index=True) if prices_dfs else pd.DataFrame()
    trades = pd.concat(trades_dfs, ignore_index=True) if trades_dfs else pd.DataFrame()
    return prices, trades


def load_uploaded_files(uploaded_files) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices_dfs = []
    trades_dfs = []

    for uploaded in uploaded_files:
        df = read_csv_flexible(uploaded)
        df = add_source_name(df, uploaded.name)

        kind = classify_dataframe(df)
        if kind == "prices":
            prices_dfs.append(df)
        elif kind == "trades":
            trades_dfs.append(df)

    prices = pd.concat(prices_dfs, ignore_index=True) if prices_dfs else pd.DataFrame()
    trades = pd.concat(trades_dfs, ignore_index=True) if trades_dfs else pd.DataFrame()
    return prices, trades


def add_time_key(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a continuous x-axis across days.
    Example:
      day = -2, timestamp = 100
      day = -1, timestamp = 100
    become two different points on a single timeline.
    """
    df = df.copy()
    if "day" in df.columns and "timestamp" in df.columns:
        df["time_key"] = df["day"] * 1_000_000 + df["timestamp"]
    else:
        df["time_key"] = df["timestamp"]
    return df


# ----------------------------
# 2) Sidebar inputs
# ----------------------------
st.title("Market Data Dashboard")
st.caption("Built with pandas, Plotly, and Streamlit")

with st.sidebar:
    st.header("Data")
    uploaded_files = st.file_uploader(
        "Upload one or more CSV files",
        type="csv",
        accept_multiple_files=True,
        help="This dashboard expects semicolon-separated CSV files.",
    )

    st.markdown(
        """
        **Tip:** your files use `;` as the separator, so remember:
        ```python
        pd.read_csv("your_file.csv", sep=";")
        ```
        """
    )

# Use uploaded files if provided, otherwise try local example files
if uploaded_files:
    prices, trades = load_uploaded_files(uploaded_files)
else:
    prices, trades = load_local_example_data()

if prices.empty and trades.empty:
    st.warning("No usable CSV files found yet. Upload your price/trade CSVs in the sidebar.")
    st.stop()

if not prices.empty:
    prices = add_time_key(prices)

# ----------------------------
# 3) Shared filters
# ----------------------------
available_products = []
if not prices.empty:
    available_products.extend(prices["product"].dropna().unique().tolist())
if not trades.empty:
    available_products.extend(trades["symbol"].dropna().unique().tolist())

available_products = sorted(set(available_products))

with st.sidebar:
    st.header("Filters")
    selected_products = st.multiselect(
        "Products",
        options=available_products,
        default=available_products,
    )

    selected_days = None
    if not prices.empty and "day" in prices.columns:
        day_options = sorted(prices["day"].dropna().unique().tolist())
        selected_days = st.multiselect("Days", options=day_options, default=day_options)

# Apply filters
filtered_prices = prices.copy()
if not filtered_prices.empty:
    if selected_products:
        filtered_prices = filtered_prices[filtered_prices["product"].isin(selected_products)]
    if selected_days is not None:
        filtered_prices = filtered_prices[filtered_prices["day"].isin(selected_days)]

filtered_trades = trades.copy()
if not filtered_trades.empty:
    if selected_products:
        filtered_trades = filtered_trades[filtered_trades["symbol"].isin(selected_products)]

# ----------------------------
# 4) Overview metrics
# ----------------------------
st.subheader("Overview")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("Price rows", f"{len(filtered_prices):,}")

with c2:
    st.metric("Trade rows", f"{len(filtered_trades):,}")

with c3:
    if not filtered_prices.empty:
        st.metric("Average mid price", f"{filtered_prices['mid_price'].mean():,.2f}")
    else:
        st.metric("Average mid price", "N/A")

with c4:
    if not filtered_trades.empty:
        st.metric("Total traded quantity", f"{filtered_trades['quantity'].sum():,}")
    else:
        st.metric("Total traded quantity", "N/A")

# ----------------------------
# 5) Price visualisations
# ----------------------------
if not filtered_prices.empty:
    st.subheader("Prices")

    price_tab1, price_tab2, price_tab3 = st.tabs(
        ["Mid / Best Bid / Best Ask", "Bid-Ask Spread", "Raw price table"]
    )

    with price_tab1:
        fig = go.Figure()

        for product in sorted(filtered_prices["product"].unique()):
            dfp = filtered_prices[filtered_prices["product"] == product].sort_values("time_key")

            fig.add_trace(
                go.Scatter(
                    x=dfp["time_key"],
                    y=dfp["mid_price"],
                    mode="lines",
                    name=f"{product} mid",
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=dfp["time_key"],
                    y=dfp["bid_price_1"],
                    mode="lines",
                    name=f"{product} best bid",
                    opacity=0.6,
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=dfp["time_key"],
                    y=dfp["ask_price_1"],
                    mode="lines",
                    name=f"{product} best ask",
                    opacity=0.6,
                )
            )

        fig.update_layout(
            height=500,
            xaxis_title="time_key (day * 1,000,000 + timestamp)",
            yaxis_title="price",
            legend_title="Series",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.info(
            "Mid price is usually the easiest summary to start with. "
            "Best bid and best ask show the top of the order book around it."
        )

    with price_tab2:
        spread_df = filtered_prices.copy()
        spread_df["spread"] = spread_df["ask_price_1"] - spread_df["bid_price_1"]

        fig = px.line(
            spread_df.sort_values("time_key"),
            x="time_key",
            y="spread",
            color="product",
            title="Bid-Ask Spread Over Time",
        )
        fig.update_layout(height=450)
        st.plotly_chart(fig, use_container_width=True)

    with price_tab3:
        table_cols = [
            "day",
            "timestamp",
            "product",
            "bid_price_1",
            "ask_price_1",
            "mid_price",
            "profit_and_loss",
            "source_file",
        ]
        table_cols = [c for c in table_cols if c in filtered_prices.columns]

        if not table_cols:
            st.warning("No supported price columns to display in raw table.")
        else:
            st.dataframe(
                filtered_prices[table_cols].sort_values([c for c in ["day", "timestamp", "product"] if c in filtered_prices.columns]),
                use_container_width=True,
                height=350,
            )

# ----------------------------
# 6) Trade visualisations
# ----------------------------
if not filtered_trades.empty:
    st.subheader("Trades")

    trade_tab1, trade_tab2, trade_tab3 = st.tabs(
        ["Trade price scatter", "Trade volume by product", "Raw trade table"]
    )

    with trade_tab1:
        fig = px.scatter(
            filtered_trades.sort_values("timestamp"),
            x="timestamp",
            y="price",
            color="symbol",
            size="quantity",
            hover_data=["quantity", "currency", "source_file"],
            title="Trades by Time",
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

    with trade_tab2:
        volume_df = (
            filtered_trades.groupby("symbol", as_index=False)["quantity"]
            .sum()
            .sort_values("quantity", ascending=False)
        )
        fig = px.bar(
            volume_df,
            x="symbol",
            y="quantity",
            title="Total Traded Quantity by Product",
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    with trade_tab3:
        st.dataframe(
            filtered_trades.sort_values(["symbol", "timestamp"]),
            use_container_width=True,
            height=350,
        )

# ----------------------------
# 7) Join price + trade views
# ----------------------------
if not filtered_prices.empty and not filtered_trades.empty:
    st.subheader("Compare trades against mid price")

    compare_products = sorted(set(filtered_prices["product"]).intersection(set(filtered_trades["symbol"])) )
    if not compare_products:
        st.info("No overlapping products in filtered prices and trades to compare.")
    else:
        chosen_product = st.selectbox(
            "Choose one product to compare",
            options=compare_products,
        )

        p = (
        filtered_prices[filtered_prices["product"] == chosen_product]
        .sort_values("time_key")
        .copy()
    )
    t = (
        filtered_trades[filtered_trades["symbol"] == chosen_product]
        .sort_values("timestamp")
        .copy()
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=p["time_key"],
            y=p["mid_price"],
            mode="lines",
            name="mid price",
        )
    )

    # Trade files do not contain a day column, so we plot them on plain timestamp.
    # This is still useful when exploring one day at a time, or when files represent similar ranges.
    fig.add_trace(
        go.Scatter(
            x=t["timestamp"],
            y=t["price"],
            mode="markers",
            marker=dict(size=8),
            name="trade price",
            text=t["quantity"],
            hovertemplate="timestamp=%{x}<br>price=%{y}<br>qty=%{text}<extra></extra>",
        )
    )

    fig.update_layout(
        height=500,
        xaxis_title="time",
        yaxis_title="price",
        title=f"{chosen_product}: trades vs mid price",
    )
    st.plotly_chart(fig, use_container_width=True)

# ----------------------------
# 8) Learning notes
# ----------------------------
with st.expander("How this app is structured"):
    st.markdown(
        """
        ### What to learn from this dashboard

        1. **Load data with pandas**
           - `pd.read_csv(..., sep=";")`
           - `pd.concat([...])` to combine multiple files

        2. **Filter data in Streamlit**
           - sidebar widgets like `st.multiselect`
           - slice the dataframe using `.isin(...)`

        3. **Plot with Plotly**
           - `plotly.express` is great for quick charts
           - `graph_objects` gives you more control

        4. **Keep the app fast**
           - `@st.cache_data` avoids re-reading files every rerun

        5. **Build iteratively**
           - start with one chart
           - add filters
           - add KPIs
           - then add comparison views
        """
    )
