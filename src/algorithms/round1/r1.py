import json
from abc import abstractmethod
from collections import deque
from typing import Any, TypeAlias

from algorithms.round1.datamodel import Order, OrderDepth, Symbol, TradingState

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None

class Strategy:
    def __init__(self, symbol: str, limit: int) -> None:
        self.symbol = symbol
        self.limit = limit

    @abstractmethod
    def act(self, state: TradingState) -> None:
        raise NotImplementedError()

    def run(self, state: TradingState) -> tuple[list[Order], int]:
        self.orders: list[Order] = []
        self.conversions = 0

        self.act(state)

        return self.orders, self.conversions

    def buy(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, quantity))

    def sell(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, -quantity))

    def convert(self, amount: int) -> None:
        self.conversions += amount

    def save(self) -> JSON:
        return None

    def load(self, data: JSON) -> None:
        pass

class MarketMakingStrategy(Strategy):
    def __init__(self, symbol: Symbol, limit: int) -> None:
        super().__init__(symbol, limit)

        self.window: deque[Any] = deque()
        self.window_size = 10

    @abstractmethod
    def get_true_value(self, state: TradingState) -> int:
        raise NotImplementedError()

    def act(self, state: TradingState) -> None:
        true_value = self.get_true_value(state)

        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)   # [(price, volume), ...]
        sell_orders = sorted(order_depth.sell_orders.items())               # [(price, volume), ...], sell volumes negative

        position = state.position.get(self.symbol, 0)

        # Remaining capacity before hitting limits
        to_buy = self.limit - position
        to_sell = self.limit + position

        # Small clip size for both taking and making
        max_clip = 10

        # Continuous inventory skew:
        # long inventory => lower fair value
        # short inventory => higher fair value
        skew_strength = 2.0
        skew = skew_strength * position / self.limit

        bid_fair = true_value - skew
        ask_fair = true_value - skew

        # ---------- Aggressive taking ----------
        # Only take when price is clearly better than our skewed fair value.
        # Use strict inequality to avoid overtrading at exactly fair.
        for price, volume in sell_orders:
            if to_buy <= 0:
                break

            ask_volume = -volume
            if price < bid_fair:
                quantity = min(max_clip, to_buy, ask_volume)
                if quantity > 0:
                    self.buy(price, quantity)
                    to_buy -= quantity

        for price, volume in buy_orders:
            if to_sell <= 0:
                break

            bid_volume = volume
            if price > ask_fair:
                quantity = min(max_clip, to_sell, bid_volume)
                if quantity > 0:
                    self.sell(price, quantity)
                    to_sell -= quantity

        # ---------- Passive market making ----------
        # After aggressive fills, quote small remaining size only.
        if buy_orders and to_buy > 0:
            best_bid = buy_orders[0][0]

            # Quote near fair, but not too far through the current best bid
            bid_price = min(int(round(bid_fair)), best_bid + 1)
            bid_size = min(max_clip, to_buy)

            if bid_size > 0:
                self.buy(bid_price, bid_size)

        if sell_orders and to_sell > 0:
            best_ask = sell_orders[0][0]

            # Quote near fair, but not too far through the current best ask
            ask_price = max(int(round(ask_fair)), best_ask - 1)
            ask_size = min(max_clip, to_sell)

            if ask_size > 0:
                self.sell(ask_price, ask_size)
    def save(self) -> JSON:
        return list(self.window)

    def load(self, data: JSON) -> None:
        if isinstance(data, list):
            self.window = deque(data, maxlen=self.window_size)
        else:
            # Fallback for unexpected data types
            self.window = deque([], maxlen=self.window_size)

class AshCoatedOsmiumStrategy(MarketMakingStrategy):
    def get_true_value(self, state: TradingState) -> int:
        return 10_000

class IntarianPepperRootStrategy(MarketMakingStrategy):

    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]

        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return 10_000

        best_bid, bid_vol = buy_orders[0]
        best_ask, ask_vol = sell_orders[0]
        ask_vol = -ask_vol

        if bid_vol + ask_vol == 0:
            fair = (best_bid + best_ask) / 2
        else:
            fair = (best_ask * bid_vol + best_bid * ask_vol) / (bid_vol + ask_vol)

        return round(fair)

    def act(self, state: TradingState) -> None:
        true_value = self.get_true_value(state)

        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return

        position = state.position.get(self.symbol, 0)
        limit = self.limit

        to_buy = limit - position
        to_sell = limit + position

        max_clip = 80
        take_edge = 1000
        make_edge = 1000

        # ---------- TREND ----------
        if not hasattr(self, "history"):
            self.history:Any = deque(maxlen=10)

        self.history.append(true_value)

        trend = 0
        if len(self.history) >= 5:
            trend = self.history[-1] - self.history[0]

        uptrend = trend > 0
        downtrend = trend < 0

        # ---------- FAIR ----------
        skew_strength = 1.5

        # bias inventory WITH trend
        directional_bias = 0.3 if uptrend else (-0.3 if downtrend else 0)

        fair = true_value - skew_strength * (position / limit) + directional_bias

        # ---------- TAKE ----------
        for price, volume in sell_orders:
            if to_buy <= 0:
                break

            ask_size = -volume

            if price <= fair - take_edge:
                qty = min(max_clip, to_buy, ask_size)
                self.buy(price, qty)
                to_buy -= qty
                position += qty

        for price, volume in buy_orders:
            if to_sell <= 0:
                break

            bid_size = volume

            # 🔥 CRITICAL: DO NOT SELL IN UPTREND UNLESS VERY GOOD
            threshold = fair + take_edge
            if uptrend:
                threshold = fair + 2 * take_edge

            if price >= threshold:
                qty = min(max_clip, to_sell, bid_size)
                self.sell(price, qty)
                to_sell -= qty
                position -= qty

        # ---------- PASSIVE ----------
        best_bid = buy_orders[0][0]
        best_ask = sell_orders[0][0]

        # BUY SIDE (more aggressive in uptrend)
        if to_buy > 0:
            if uptrend:
                bid_price = min(int(fair), best_bid + 1)
            else:
                bid_price = int(fair - make_edge)

            qty = min(max_clip, to_buy)
            self.buy(bid_price, qty)

        # SELL SIDE (much more conservative in uptrend)
        if to_sell > 0:
            if uptrend:
                ask_price = int(fair + 2 * make_edge)  # push higher
            else:
                ask_price = max(int(fair + make_edge), best_ask - 1)

            qty = min(max_clip, to_sell)
            self.sell(ask_price, qty)


class Trader:
    def bid(self):
        return 15

    def __init__(self) -> None:
        limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }

        self.strategies: dict[Symbol, Strategy] = {symbol: clazz(symbol, limits[symbol]) for symbol, clazz in {
            "ASH_COATED_OSMIUM": AshCoatedOsmiumStrategy,
            "INTARIAN_PEPPER_ROOT": IntarianPepperRootStrategy,
        }.items()}

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        orders = {}
        conversions = 0

        old_trader_data = json.loads(state.traderData) if state.traderData != "" else {}
        new_trader_data = {}

        for symbol, strategy in self.strategies.items():
            if symbol in old_trader_data:
                strategy.load(old_trader_data[symbol])

            if symbol in state.order_depths:
                strategy_orders, strategy_conversions = strategy.run(state)
                orders[symbol] = strategy_orders
                conversions += strategy_conversions

            new_trader_data[symbol] = strategy.save()

        trader_data = json.dumps(new_trader_data, separators=(",", ":"))


        return orders, conversions, trader_data
