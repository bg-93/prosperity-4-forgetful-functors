from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_PATH = REPO_ROOT / "logs" / "round1" / "269717.log"
MARKOUT_HORIZON_MS = 1_000
POSITION_LIMIT = 80
PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
}


st.set_page_config(
    page_title="Round 1 Log Viewer",
    layout="wide",
)


def wrap_label(label: str, width: int = 14) -> str:
    return "<br>".join(textwrap.wrap(label, width=width)) or label


def load_log_payload_from_text(raw_text: str) -> dict[str, Any]:
    payload = json.loads(raw_text)
    required_keys = {"activitiesLog", "tradeHistory", "logs"}
    missing = required_keys - payload.keys()
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Missing required keys in log file: {missing_text}")
    return payload


@st.cache_data(show_spinner=False)
def load_round_log_from_text(raw_text: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = load_log_payload_from_text(raw_text)

    activity = pd.read_csv(StringIO(raw["activitiesLog"]), sep=";")
    activity.columns = [column.strip() for column in activity.columns]
    for column in activity.columns:
        if column != "product":
            activity[column] = pd.to_numeric(activity[column], errors="coerce")
    activity = activity.sort_values(["product", "timestamp"]).reset_index(drop=True)
    activity["spread"] = activity["ask_price_1"] - activity["bid_price_1"]
    bid_vol = activity["bid_volume_1"].fillna(0)
    ask_vol = activity["ask_volume_1"].fillna(0)
    total_top_level = (bid_vol + ask_vol).replace(0, np.nan)
    activity["book_imbalance"] = (bid_vol - ask_vol) / total_top_level
    activity["time_s"] = activity["timestamp"] / 1000

    trades = pd.DataFrame(raw["tradeHistory"])
    for column in ["timestamp", "price", "quantity", "buyer", "seller", "symbol", "currency"]:
        if column not in trades.columns:
            dtype = "float64" if column in {"timestamp", "price", "quantity"} else "object"
            trades[column] = pd.Series(dtype=dtype)
    trades = trades.sort_values("timestamp").reset_index(drop=True)
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce")
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce")
    trades["is_submission"] = (trades["buyer"] == "SUBMISSION") | (trades["seller"] == "SUBMISSION")
    trades["side"] = np.select(
        [trades["buyer"] == "SUBMISSION", trades["seller"] == "SUBMISSION"],
        [1, -1],
        default=0,
    )
    trades["side_label"] = trades["side"].map({1: "BUY", -1: "SELL", 0: "OTHER"})
    trades["signed_qty"] = trades["side"] * trades["quantity"]
    trades["notional"] = trades["price"] * trades["quantity"]
    trades["cash_flow"] = -trades["side"] * trades["notional"]

    log_entries = pd.DataFrame(raw["logs"])
    for column in ["timestamp", "lambdaLog", "sandboxLog"]:
        if column not in log_entries.columns:
            log_entries[column] = pd.Series(dtype="object")

    return raw, activity, trades, log_entries


def build_views(
    activity: pd.DataFrame,
    trades: pd.DataFrame,
    markout_horizon_ms: int = MARKOUT_HORIZON_MS,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    submission_trades = trades[trades["is_submission"]].copy()
    submission_trades = submission_trades.sort_values(["symbol", "timestamp", "price"]).reset_index(drop=True)
    submission_trades["buy_qty"] = np.where(submission_trades["side"] == 1, submission_trades["quantity"], 0)
    submission_trades["sell_qty"] = np.where(submission_trades["side"] == -1, submission_trades["quantity"], 0)

    product_views: dict[str, pd.DataFrame] = {}
    trade_views: dict[str, pd.DataFrame] = {}

    for product, market in activity.groupby("product", sort=True):
        market = market.sort_values("timestamp").copy()
        product_trades = submission_trades[submission_trades["symbol"] == product].copy()

        market_lookup = market[["timestamp", "mid_price", "spread"]].rename(columns={"mid_price": "mid_at_trade"})
        future_lookup = market[["timestamp", "mid_price"]].rename(columns={"mid_price": "future_mid"})
        future_lookup["timestamp"] = future_lookup["timestamp"] - markout_horizon_ms

        if not product_trades.empty:
            product_trades = product_trades.merge(market_lookup, on="timestamp", how="left")
            product_trades = product_trades.merge(future_lookup, on="timestamp", how="left")
            product_trades["fill_edge"] = np.where(
                product_trades["side"] == 1,
                product_trades["mid_at_trade"] - product_trades["price"],
                product_trades["price"] - product_trades["mid_at_trade"],
            )
            product_trades["markout"] = np.where(
                product_trades["side"] == 1,
                product_trades["future_mid"] - product_trades["price"],
                product_trades["price"] - product_trades["future_mid"],
            )

            trade_by_time = product_trades.groupby("timestamp", as_index=False).agg(
                signed_qty=("signed_qty", "sum"),
                traded_qty=("quantity", "sum"),
                turnover=("notional", "sum"),
                buy_qty=("buy_qty", "sum"),
                sell_qty=("sell_qty", "sum"),
            )
            market = market.merge(trade_by_time, on="timestamp", how="left")

        for column in ["signed_qty", "traded_qty", "turnover", "buy_qty", "sell_qty"]:
            if column not in market.columns:
                market[column] = 0.0
            market[column] = market[column].fillna(0.0)

        market["position"] = market["signed_qty"].cumsum()
        market["running_peak_pnl"] = market["profit_and_loss"].cummax()
        market["drawdown"] = market["running_peak_pnl"] - market["profit_and_loss"]

        product_views[product] = market
        trade_views[product] = product_trades

    pnl_by_product = activity.pivot(index="timestamp", columns="product", values="profit_and_loss").sort_index()
    pnl_by_product["TOTAL"] = pnl_by_product.sum(axis=1)
    return submission_trades, product_views, trade_views, pnl_by_product


def build_summary(
    product_views: dict[str, pd.DataFrame],
    trade_views: dict[str, pd.DataFrame],
    pnl_by_product: pd.DataFrame,
) -> tuple[pd.DataFrame, float, float]:
    summary_rows: list[dict[str, float | int | str]] = []
    total_final_pnl = float(pnl_by_product["TOTAL"].iloc[-1])
    total_drawdown = float((pnl_by_product["TOTAL"].cummax() - pnl_by_product["TOTAL"]).max())

    for product, market in product_views.items():
        product_trades = trade_views[product]
        final_pnl = float(market["profit_and_loss"].iloc[-1])
        final_position = float(market["position"].iloc[-1])
        final_mid = float(market["mid_price"].iloc[-1])

        inventory_pnl_proxy = np.nan
        if not product_trades.empty:
            inventory_pnl_proxy = float(product_trades["cash_flow"].sum() + final_position * final_mid)

        summary_rows.append(
            {
                "product": product,
                "final_pnl": final_pnl,
                "pnl_share_pct": 100 * final_pnl / total_final_pnl if total_final_pnl else np.nan,
                "max_drawdown": float(market["drawdown"].max()),
                "mid_move": float(market["mid_price"].iloc[-1] - market["mid_price"].iloc[0]),
                "avg_spread": float(market["spread"].mean()),
                "trade_count": int(len(product_trades)),
                "turnover": float(product_trades["notional"].sum()),
                "buy_qty": float(product_trades.loc[product_trades["side"] == 1, "quantity"].sum()),
                "sell_qty": float(product_trades.loc[product_trades["side"] == -1, "quantity"].sum()),
                "final_position": final_position,
                "min_position": float(market["position"].min()),
                "max_position": float(market["position"].max()),
                "avg_fill_edge": float(product_trades["fill_edge"].mean()) if not product_trades.empty else np.nan,
                "avg_markout": float(product_trades["markout"].mean()) if not product_trades.empty else np.nan,
                "inventory_pnl_proxy": inventory_pnl_proxy,
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values("final_pnl", ascending=False).reset_index(drop=True)
    return summary, total_final_pnl, total_drawdown


def generate_insights(
    summary: pd.DataFrame,
    trade_views: dict[str, pd.DataFrame],
    markout_horizon_ms: int,
) -> list[str]:
    if summary.empty:
        return ["No products were found in the uploaded log."]

    insights: list[str] = []
    winner = summary.iloc[0]
    runner = summary.iloc[1] if len(summary) > 1 else None

    insights.append(
        f"Total PnL finished at {summary['final_pnl'].sum():,.2f}. "
        f"{winner['product']} contributed {winner['pnl_share_pct']:.1f}% of that result."
    )

    if runner is not None:
        insights.append(
            f"{winner['product']} outperformed {runner['product']} by "
            f"{winner['final_pnl'] - runner['final_pnl']:,.2f}."
        )

    for _, row in summary.iterrows():
        product = str(row["product"])
        product_trades = trade_views[product]

        if row["trade_count"] == 0:
            insights.append(f"{product} had no submission fills in this run.")
            continue

        edge_text = "positive" if pd.notna(row["avg_fill_edge"]) and row["avg_fill_edge"] > 0 else "negative"
        markout_text = "positive" if pd.notna(row["avg_markout"]) and row["avg_markout"] > 0 else "negative"
        limit_touched = abs(row["max_position"]) >= POSITION_LIMIT or abs(row["min_position"]) >= POSITION_LIMIT

        insights.append(
            f"{product}: {int(row['trade_count'])} submission fills, avg fill edge {row['avg_fill_edge']:.2f}, "
            f"and avg {markout_horizon_ms}ms markout {row['avg_markout']:.2f} "
            f"({edge_text} execution / {markout_text} short-term follow-through)."
        )

        if limit_touched:
            insights.append(
                f"{product} touched the {POSITION_LIMIT}-lot position limit and finished at {int(row['final_position'])}, "
                "so inventory carried a meaningful share of the result."
            )

        if abs(row["mid_move"]) > row["avg_spread"] * 10:
            direction = "uptrend" if row["mid_move"] > 0 else "downtrend"
            insights.append(
                f"{product} spent the session in a strong {direction}: mid-price moved {row['mid_move']:.1f} "
                f"against an average spread of {row['avg_spread']:.2f}."
            )

        if product_trades["side"].eq(1).all() or product_trades["side"].eq(-1).all():
            one_way = "buying only" if product_trades["side"].eq(1).all() else "selling only"
            insights.append(
                f"{product} was effectively {one_way}, so the run depended heavily on directional follow-through."
            )

    return insights


def base_figure_layout(title: str, height: int) -> dict[str, Any]:
    return {
        "title": {"text": title, "x": 0.01},
        "template": "plotly_white",
        "height": height,
        "margin": {"l": 70, "r": 30, "t": 70, "b": 70},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        "hovermode": "x unified",
    }


def build_pnl_figure(pnl_by_product: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for column in [name for name in pnl_by_product.columns if name != "TOTAL"]:
        fig.add_trace(
            go.Scatter(
                x=pnl_by_product.index / 1000,
                y=pnl_by_product[column],
                mode="lines",
                name=column,
                line={"width": 2},
            )
        )

    fig.add_trace(
        go.Scatter(
            x=pnl_by_product.index / 1000,
            y=pnl_by_product["TOTAL"],
            mode="lines",
            name="TOTAL",
            line={"width": 3, "color": "#111111"},
        )
    )

    fig.update_layout(**base_figure_layout("PnL Over Time", height=500))
    fig.update_xaxes(title_text="Time (s)", rangeslider={"visible": True}, automargin=True)
    fig.update_yaxes(title_text="PnL", automargin=True)
    return fig


def build_price_figure(product_views: dict[str, pd.DataFrame], trade_views: dict[str, pd.DataFrame]) -> go.Figure:
    products = list(product_views)
    fig = make_subplots(
        rows=len(products),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=products,
    )

    for row_index, product in enumerate(products, start=1):
        market = product_views[product]
        product_trades = trade_views[product]
        time_s = market["time_s"]

        fig.add_trace(
            go.Scatter(
                x=time_s,
                y=market["bid_price_1"],
                mode="lines",
                line={"width": 0},
                hoverinfo="skip",
                name="Top-of-book spread",
                legendgroup="spread",
                showlegend=row_index == 1,
            ),
            row=row_index,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=time_s,
                y=market["ask_price_1"],
                mode="lines",
                fill="tonexty",
                fillcolor="rgba(31, 119, 180, 0.12)",
                line={"width": 0},
                hoverinfo="skip",
                name="Top-of-book spread",
                legendgroup="spread",
                showlegend=False,
            ),
            row=row_index,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=time_s,
                y=market["mid_price"],
                mode="lines",
                line={"color": "#1f77b4", "width": 2},
                name="Mid price",
                legendgroup="mid",
                showlegend=row_index == 1,
            ),
            row=row_index,
            col=1,
        )

        buys = product_trades[product_trades["side"] == 1]
        sells = product_trades[product_trades["side"] == -1]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["timestamp"] / 1000,
                    y=buys["price"],
                    mode="markers",
                    name="Submission buys",
                    legendgroup="buys",
                    showlegend=row_index == 1,
                    marker={"color": "#2ca02c", "size": 9, "symbol": "triangle-up"},
                    customdata=np.stack([buys["quantity"], buys["fill_edge"], buys["markout"]], axis=-1),
                    hovertemplate=(
                        "Time: %{x:.1f}s<br>"
                        "Price: %{y:.2f}<br>"
                        "Qty: %{customdata[0]:.0f}<br>"
                        "Fill edge: %{customdata[1]:.2f}<br>"
                        "Markout: %{customdata[2]:.2f}<extra></extra>"
                    ),
                ),
                row=row_index,
                col=1,
            )
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["timestamp"] / 1000,
                    y=sells["price"],
                    mode="markers",
                    name="Submission sells",
                    legendgroup="sells",
                    showlegend=row_index == 1,
                    marker={"color": "#d62728", "size": 9, "symbol": "triangle-down"},
                    customdata=np.stack([sells["quantity"], sells["fill_edge"], sells["markout"]], axis=-1),
                    hovertemplate=(
                        "Time: %{x:.1f}s<br>"
                        "Price: %{y:.2f}<br>"
                        "Qty: %{customdata[0]:.0f}<br>"
                        "Fill edge: %{customdata[1]:.2f}<br>"
                        "Markout: %{customdata[2]:.2f}<extra></extra>"
                    ),
                ),
                row=row_index,
                col=1,
            )

        fig.update_yaxes(title_text="Price", row=row_index, col=1, automargin=True)

    fig.update_layout(**base_figure_layout("Market Context and Submission Fills", height=max(420 * len(products), 520)))
    fig.update_xaxes(title_text="Time (s)", rangeslider={"visible": len(products) == 1}, automargin=True)
    return fig


def build_inventory_quality_figure(
    product_views: dict[str, pd.DataFrame],
    trade_views: dict[str, pd.DataFrame],
    markout_horizon_ms: int,
) -> go.Figure:
    products = list(product_views)
    subplot_titles: list[str] = []
    for product in products:
        subplot_titles.append(f"{product} Inventory Path")
        subplot_titles.append(f"{product} Execution Quality")

    fig = make_subplots(
        rows=len(products),
        cols=2,
        horizontal_spacing=0.12,
        vertical_spacing=0.11,
        subplot_titles=subplot_titles,
        column_widths=[0.62, 0.38],
    )

    metric_labels = [
        "Avg fill edge",
        "Median fill edge",
        f"Avg {markout_horizon_ms}ms markout",
        "Median markout",
    ]

    for row_index, product in enumerate(products, start=1):
        market = product_views[product]
        product_trades = trade_views[product]

        fig.add_trace(
            go.Scatter(
                x=market["time_s"],
                y=market["position"],
                mode="lines",
                line={"color": "#9467bd", "width": 2},
                name="Position",
                showlegend=False,
            ),
            row=row_index,
            col=1,
        )
        for limit_value, color in [(POSITION_LIMIT, "#d62728"), (-POSITION_LIMIT, "#d62728"), (0, "#111111")]:
            fig.add_hline(
                y=limit_value,
                line_width=1,
                line_dash="dash" if limit_value else "solid",
                line_color=color,
                row=row_index,
                col=1,
            )

        metric_values = [
            product_trades["fill_edge"].mean(),
            product_trades["fill_edge"].median(),
            product_trades["markout"].mean(),
            product_trades["markout"].median(),
        ]
        metric_values = [0 if pd.isna(value) else float(value) for value in metric_values]
        metric_colors = ["#2ca02c" if value >= 0 else "#ff7f0e" for value in metric_values]

        fig.add_trace(
            go.Bar(
                x=[wrap_label(label) for label in metric_labels],
                y=metric_values,
                marker_color=metric_colors,
                showlegend=False,
                hovertemplate="%{x}<br>%{y:.2f}<extra></extra>",
            ),
            row=row_index,
            col=2,
        )
        fig.add_hline(y=0, line_width=1, line_color="#111111", row=row_index, col=2)

        fig.update_xaxes(title_text="Time (s)", row=row_index, col=1, automargin=True)
        fig.update_yaxes(title_text="Position", row=row_index, col=1, automargin=True)
        fig.update_xaxes(tickangle=0, row=row_index, col=2, automargin=True)
        fig.update_yaxes(title_text="Ticks vs mid", row=row_index, col=2, automargin=True)

    fig.update_layout(
        **base_figure_layout("Inventory Path and Execution Quality", height=max(380 * len(products), 520))
    )
    fig.update_layout(bargap=0.35)
    return fig


def read_default_log_text() -> str:
    return DEFAULT_LOG_PATH.read_text()


def render_header() -> None:
    st.title("Round 1 Log Viewer")
    st.caption(
        "Upload a Round 1 JSON log to recreate the notebook visuals with Plotly zoom, pan, and hover support."
    )


def render_inputs() -> tuple[str, int]:
    uploaded_file = st.file_uploader(
        "Drag and drop a `.log` or `.json` file",
        type=["log", "json"],
        accept_multiple_files=False,
        help="The app expects the same JSON log structure used by `R1LogViewer.ipynb`.",
    )

    st.sidebar.header("Controls")
    markout_horizon_ms = st.sidebar.number_input(
        "Markout horizon (ms)",
        min_value=100,
        max_value=10_000,
        value=MARKOUT_HORIZON_MS,
        step=100,
    )

    if uploaded_file is not None:
        source_name = uploaded_file.name
        raw_text = uploaded_file.getvalue().decode("utf-8")
    else:
        source_name = str(DEFAULT_LOG_PATH.relative_to(REPO_ROOT))
        raw_text = read_default_log_text()

    st.sidebar.info(f"Loaded source: `{source_name}`")
    return raw_text, int(markout_horizon_ms)


def render_run_metrics(
    raw_log: dict[str, Any],
    activity: pd.DataFrame,
    trades: pd.DataFrame,
    submission_trades: pd.DataFrame,
    log_entries: pd.DataFrame,
    total_final_pnl: float,
    total_max_drawdown: float,
) -> None:
    non_empty_debug = int(
        log_entries["lambdaLog"].fillna("").astype(bool).sum()
        + log_entries["sandboxLog"].fillna("").astype(bool).sum()
    )
    columns = st.columns(4)
    columns[0].metric("Submission ID", str(raw_log.get("submissionId", "N/A"))[:12])
    columns[1].metric("Activity rows", f"{len(activity):,}")
    columns[2].metric("Submission trades", f"{len(submission_trades):,}")
    columns[3].metric("Log entries", f"{len(log_entries):,}")

    columns = st.columns(4)
    columns[0].metric("Total final PnL", f"{total_final_pnl:,.2f}")
    columns[1].metric("Total max drawdown", f"{total_max_drawdown:,.2f}")
    columns[2].metric("Market trades", f"{len(trades):,}")
    columns[3].metric("Non-empty debug logs", f"{non_empty_debug:,}")


def main() -> None:
    render_header()
    raw_text, markout_horizon_ms = render_inputs()

    st.markdown(
        """
        <style>
        div[data-testid="stFileUploaderDropzone"] {
            padding: 1rem;
            border-radius: 16px;
        }
        div[data-testid="stMetric"] {
            background: #fafafa;
            border: 1px solid #ececec;
            border-radius: 14px;
            padding: 0.75rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    try:
        raw_log, activity, trades, log_entries = load_round_log_from_text(raw_text)
    except Exception as exc:
        st.error(
            "The uploaded file could not be parsed as a Round 1 notebook log. "
            f"Details: {exc}"
        )
        st.stop()

    submission_trades, product_views, trade_views, pnl_by_product = build_views(
        activity,
        trades,
        markout_horizon_ms=markout_horizon_ms,
    )
    summary, total_final_pnl, total_max_drawdown = build_summary(product_views, trade_views, pnl_by_product)
    annotated_submission_trades = (
        pd.concat(trade_views.values(), ignore_index=True) if trade_views else submission_trades.copy()
    )
    if not annotated_submission_trades.empty:
        annotated_submission_trades = annotated_submission_trades.sort_values(
            ["symbol", "timestamp", "price"]
        ).reset_index(drop=True)

    render_run_metrics(
        raw_log,
        activity,
        trades,
        submission_trades,
        log_entries,
        total_final_pnl,
        total_max_drawdown,
    )

    st.subheader("Auto Insights")
    for insight in generate_insights(summary, trade_views, markout_horizon_ms):
        st.markdown(f"- {insight}")

    st.subheader("Summary")
    st.dataframe(summary.round(2), use_container_width=True, hide_index=True)

    st.subheader("PnL Over Time")
    st.plotly_chart(build_pnl_figure(pnl_by_product), use_container_width=True, config=PLOTLY_CONFIG)

    st.subheader("Market Context and Submission Fills")
    st.plotly_chart(build_price_figure(product_views, trade_views), use_container_width=True, config=PLOTLY_CONFIG)

    st.subheader("Inventory Path and Execution Quality")
    st.plotly_chart(
        build_inventory_quality_figure(product_views, trade_views, markout_horizon_ms),
        use_container_width=True,
        config=PLOTLY_CONFIG,
    )

    st.subheader("Submission Trade Preview")
    preview_columns = ["timestamp", "symbol", "side_label", "price", "quantity", "mid_at_trade", "fill_edge", "markout"]
    st.dataframe(
        annotated_submission_trades.reindex(columns=preview_columns).head(20).round(2),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
