import json
from typing import cast
from abc import abstractmethod
from collections import deque
from typing import Any, TypeAlias

from datamodel import Order, OrderDepth, Symbol, TradingState

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


    def save(self) -> JSON:
        pass

    def load(self, data: JSON) -> None:
        pass

class AshCoatedOsmiumStrategy(MarketMakingStrategy):
    def act(self, state: TradingState) -> None:
        # true value of the item
        true_value = self.get_true_value(state)

        #reading all the orders that have occured till this point
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        # defining present inventory
        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        max_clip = 10

        bid_size = max(0, min(max_clip, self.limit - position))
        ask_size = max(0, min(max_clip, self.limit + position))

        #variables indicating how often we are hitting our position limit
        #soft_liquidate = len(self.window) == self.window_size and sum(self.window) >= self.window_size / 2 and self.window[-1]
        #hard_liquidate = len(self.window) == self.window_size and all(self.window)

        #defining our max and min buy and sell prices around true value
        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < self.limit * -0.5 else true_value

        # picking out cheap ask prices
        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        # if we have enough position to buy, and for the past 10 ticks weve hit our
        # limit then we need to buy more( reducing risk from being stuck at short limit)
        '''if to_buy > 0 and hard_liquidate:
            quantity = to_buy // 2
            self.buy(true_value, quantity)
            to_buy -= quantity'''

        # same as above but for less amount of previous ticks we've hit our limit
        # still need to buy more but less aggressively
        '''if to_buy > 0 and soft_liquidate:
            quantity = to_buy // 2
            self.buy(true_value - 2, quantity)
            to_buy -= quantity'''

        # if we have enough position to buy, then place a bid that beats the most popular bid
        # by 1
        if to_buy > 0 and buy_orders:
            popular_buy_price = buy_orders[0][0]
            price = min(max_buy_price, popular_buy_price + 1)
            self.buy(price, min(bid_size,to_buy))

        # the following is symmetric for sell side
        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        '''if to_sell > 0 and hard_liquidate:
            quantity = to_sell // 2
            self.sell(true_value, quantity)
            to_sell -= quantity'''

        '''if to_sell > 0 and soft_liquidate:
            quantity = to_sell // 2
            self.sell(true_value + 2, quantity)
            to_sell -= quantity'''

        if to_sell > 0 and sell_orders:
            popular_sell_price = sell_orders[0][0]
            price = max(min_sell_price, popular_sell_price - 1)
            self.sell(price, min(ask_size,to_sell))

    def get_true_value(self, state: TradingState) -> int:
        return 10_000

from collections import deque
from datamodel import Order
from typing import List, Optional


class IntarianPepperRootStrategy(MarketMakingStrategy):
    def __init__(self, symbol: str, position_limit: int) -> None:
        super().__init__(symbol, position_limit)

        # history
        self.mid_history = deque(maxlen=60)
        self.microprice_history = deque(maxlen=60)
        self.imbalance_history = deque(maxlen=30)
        self.signal_history = deque(maxlen=20)

    def save(self) -> JSON:
        return {
            "mid_history": list(self.mid_history),
            "microprice_history": list(self.microprice_history),
            "imbalance_history": list(self.imbalance_history),
            "signal_history": list(self.signal_history),
        }

    def load(self, data: JSON) -> None:
        if not isinstance(data, dict):
            self.mid_history = deque([], maxlen=60)
            self.microprice_history = deque([], maxlen=60)
            self.imbalance_history = deque([], maxlen=30)
            self.signal_history = deque([], maxlen=20)
            return

        mid_history = data.get("mid_history", [])
        microprice_history = data.get("microprice_history", [])
        imbalance_history = data.get("imbalance_history", [])
        signal_history = data.get("signal_history", [])

        self.mid_history = deque(mid_history if isinstance(mid_history, list) else [], maxlen=60)
        self.microprice_history = deque(microprice_history if isinstance(microprice_history, list) else [], maxlen=60)
        self.imbalance_history = deque(imbalance_history if isinstance(imbalance_history, list) else [], maxlen=30)
        self.signal_history = deque(signal_history if isinstance(signal_history, list) else [], maxlen=20)

    # -----------------------------
    # Basic order book utilities
    # -----------------------------
    def get_sorted_books(self, order_depth: OrderDepth) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())
        return buy_orders, sell_orders

    def get_best_bid_ask(self, order_depth: OrderDepth) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        buy_orders, sell_orders = self.get_sorted_books(order_depth)
        if not buy_orders or not sell_orders:
            return None, None, None, None
        best_bid, best_bid_vol = buy_orders[0]
        best_ask, best_ask_vol = sell_orders[0]
        return best_bid, best_bid_vol, best_ask, best_ask_vol

    def get_mid_price(self, order_depth: OrderDepth) -> Optional[float]:
        best_bid, _, best_ask, _ = self.get_best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2

    def get_microprice(self, order_depth: OrderDepth) -> Optional[float]:
        best_bid, best_bid_vol, best_ask, best_ask_vol = self.get_best_bid_ask(order_depth)
        if best_bid is None or best_ask is None or best_bid_vol is None or best_ask_vol is None:
            return None

        ask_vol = abs(best_ask_vol)
        bid_vol = abs(best_bid_vol)

        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2

        return (best_bid * ask_vol + best_ask * bid_vol) / total

    def get_book_imbalance(self, order_depth: OrderDepth, depth_levels: int = 3) -> float:
        buy_orders, sell_orders = self.get_sorted_books(order_depth)

        total_bid = 0
        total_ask = 0

        for _, vol in buy_orders[:depth_levels]:
            total_bid += abs(vol)

        for _, vol in sell_orders[:depth_levels]:
            total_ask += abs(vol)

        denom = total_bid + total_ask
        if denom == 0:
            return 0.0

        return (total_bid - total_ask) / denom

    def get_spread(self, order_depth: OrderDepth) -> Optional[int]:
        best_bid, _, best_ask, _ = self.get_best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return None
        return best_ask - best_bid

    def get_depth_liquidity(self, order_depth: OrderDepth, depth_levels: int = 3) -> int:
        buy_orders, sell_orders = self.get_sorted_books(order_depth)
        total = 0
        for _, vol in buy_orders[:depth_levels]:
            total += abs(vol)
        for _, vol in sell_orders[:depth_levels]:
            total += abs(vol)
        return total

    # -----------------------------
    # History updates
    # -----------------------------
    def update_history(self, order_depth: OrderDepth) -> None:
        mid = self.get_mid_price(order_depth)
        micro = self.get_microprice(order_depth)
        imb = self.get_book_imbalance(order_depth)

        if mid is not None:
            self.mid_history.append(mid)
        if micro is not None:
            self.microprice_history.append(micro)
        self.imbalance_history.append(imb)

    # -----------------------------
    # Trend / momentum features
    # -----------------------------
    def safe_diff(self, arr: deque[float], lookback: int) -> float:
        if len(arr) <= lookback:
            return 0.0
        return arr[-1] - arr[-1 - lookback]

    def get_short_momentum(self) -> float:
        return self.safe_diff(self.mid_history, 2)

    def get_medium_momentum(self) -> float:
        return self.safe_diff(self.mid_history, 5)

    def get_long_momentum(self) -> float:
        return self.safe_diff(self.mid_history, 12)

    def get_momentum_signal(self) -> float:
        short_mom = self.get_short_momentum()
        med_mom = self.get_medium_momentum()
        long_mom = self.get_long_momentum()

        return 0.60 * short_mom + 0.25 * med_mom + 0.15 * long_mom

    def get_acceleration(self) -> float:
        if len(self.mid_history) < 6:
            return 0.0

        recent_mom = self.mid_history[-1] - self.mid_history[-3]
        prev_mom = self.mid_history[-3] - self.mid_history[-5]
        return recent_mom - prev_mom

    def get_microprice_pressure(self) -> float:
        if len(self.mid_history) == 0 or len(self.microprice_history) == 0:
            return 0.0
        return self.microprice_history[-1] - self.mid_history[-1]

    # -----------------------------
    # Regime detection
    # -----------------------------
    def get_realized_volatility(self, window: int = 12) -> float:
        if len(self.mid_history) < window + 1:
            return 0.0

        diffs = []
        mids = list(self.mid_history)
        for i in range(-window, -1):
            diffs.append(abs(mids[i + 1] - mids[i]))

        if not diffs:
            return 0.0
        return sum(diffs) / len(diffs)

    def is_trending_regime(self) -> bool:
        mom = self.get_momentum_signal()
        accel = self.get_acceleration()
        vol = self.get_realized_volatility()

        return abs(mom) > 0.8 and vol > 0.3 and accel > -0.3

    def is_bullish_regime(self) -> bool:
        return self.is_trending_regime() and self.get_momentum_signal() > 0

    # -----------------------------
    # Flow proxy / confirmation
    # -----------------------------
    def get_flow_proxy_score(self) -> float:
        imbalance = self.imbalance_history[-1] if self.imbalance_history else 0.0
        micro_pressure = self.get_microprice_pressure()
        short_mom = self.get_short_momentum()

        return 1.2 * imbalance + 0.8 * micro_pressure + 0.4 * short_mom

    def get_combined_alpha(self) -> float:
        momentum = self.get_momentum_signal()
        accel = self.get_acceleration()
        imbalance = self.imbalance_history[-1] if self.imbalance_history else 0.0
        micro_pressure = self.get_microprice_pressure()
        flow = self.get_flow_proxy_score()

        alpha = (
            0.90 * momentum
            + 0.50 * accel
            + 1.40 * imbalance
            + 0.70 * micro_pressure
            + 0.80 * flow
        )

        self.signal_history.append(alpha)
        return alpha

    # -----------------------------
    # Fair value
    # -----------------------------
    def get_true_value(self, order_depth: OrderDepth, position: int) -> Optional[float]:
        mid = self.get_mid_price(order_depth)
        micro = self.get_microprice(order_depth)

        if mid is None or micro is None:
            return None

        momentum = self.get_momentum_signal()
        imbalance = self.imbalance_history[-1] if self.imbalance_history else 0.0
        accel = self.get_acceleration()

        inventory_penalty = 1.1 * (position / self.limit)

        fair = (
            mid
            + 0.75 * momentum
            + 0.30 * (micro - mid)
            + 0.80 * imbalance
            + 0.30 * accel
            - inventory_penalty
        )
        return fair

    # -----------------------------
    # Position and sizing logic
    # -----------------------------
    def get_max_buy_size(self, position: int) -> int:
        return max(0, self.limit - position)

    def get_max_sell_size(self, position: int) -> int:
        return max(0, self.limit + position)

    def get_aggression_multiplier(self, order_depth: OrderDepth) -> float:
        spread = self.get_spread(order_depth)
        liquidity = self.get_depth_liquidity(order_depth)
        alpha = self.get_combined_alpha()

        mult = 1.0

        if spread is not None and spread <= 2:
            mult += 0.35
        if liquidity >= 40:
            mult += 0.25
        if alpha > 2.5:
            mult += 0.45
        elif alpha > 1.5:
            mult += 0.20

        return mult

    def get_desired_buy_size(self, order_depth: OrderDepth, position: int) -> int:
        alpha = self.get_combined_alpha()
        max_buy = self.get_max_buy_size(position)

        if alpha <= 0:
            return 0

        base = 6
        size = base

        if alpha > 1.0:
            size += 6
        if alpha > 2.0:
            size += 8
        if alpha > 3.0:
            size += 10

        size = int(size * self.get_aggression_multiplier(order_depth))

        inventory_factor = max(0.2, 1.0 - max(0, position) / self.limit)
        size = int(size * inventory_factor)

        return max(0, min(size, max_buy))

    def get_desired_exit_size(self, position: int) -> int:
        if position <= 0:
            return 0

        mom = self.get_momentum_signal()
        accel = self.get_acceleration()
        flow = self.get_flow_proxy_score()

        strength = 0
        if mom < 0:
            strength += 1
        if accel < 0:
            strength += 1
        if flow < 0:
            strength += 1

        if strength == 0:
            return 0
        if strength == 1:
            return max(1, position // 4)
        if strength == 2:
            return max(2, position // 2)
        return position

    # -----------------------------
    # Entry / exit conditions
    # -----------------------------
    def should_enter_long(self, order_depth: OrderDepth, position: int) -> bool:
        if position >= self.limit:
            return False

        momentum = self.get_momentum_signal()
        accel = self.get_acceleration()
        imbalance = self.imbalance_history[-1] if self.imbalance_history else 0.0
        flow = self.get_flow_proxy_score()
        spread = self.get_spread(order_depth)

        if spread is None:
            return False

        return (
            self.is_bullish_regime()
            and momentum > 0.6
            and accel > -0.15
            and imbalance > 0.05
            and flow > 0.10
            and spread <= 4
        )

    def should_exit_long(self, position: int) -> bool:
        if position <= 0:
            return False

        momentum = self.get_momentum_signal()
        accel = self.get_acceleration()
        imbalance = self.imbalance_history[-1] if self.imbalance_history else 0.0
        flow = self.get_flow_proxy_score()

        return (
            momentum < 0
            or accel < -0.4
            or imbalance < -0.10
            or flow < -0.15
        )

    # -----------------------------
    # Passive + aggressive execution
    # -----------------------------
    def sweep_asks(self, sell_orders: list[tuple[int, int]], max_qty: int, limit_price: float) -> list[tuple[int, int]]:
        fills: list[tuple[int, int]] = []
        remaining = max_qty

        for ask_price, ask_vol in sell_orders:
            available = abs(ask_vol)
            if remaining <= 0:
                break
            if ask_price <= limit_price:
                qty = min(remaining, available)
                if qty > 0:
                    fills.append((ask_price, qty))
                    remaining -= qty

        return fills

    def hit_bids_to_exit(self, buy_orders: list[tuple[int, int]], max_qty: int, limit_price: int) -> list[tuple[int, int]]:
        fills: list[tuple[int, int]] = []
        remaining = max_qty

        for bid_price, bid_vol in buy_orders:
            available = abs(bid_vol)
            if remaining <= 0:
                break
            if bid_price >= limit_price:
                qty = min(remaining, available)
                if qty > 0:
                    fills.append((bid_price, qty))
                    remaining -= qty

        return fills

    # -----------------------------
    # Main act function
    # -----------------------------
    def act(self, state: TradingState) -> None:
        if self.symbol not in state.order_depths:
            return

        order_depth = state.order_depths[self.symbol]
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return

        position = state.position.get(self.symbol, 0)

        self.update_history(order_depth)

        buy_orders, sell_orders = self.get_sorted_books(order_depth)
        best_bid, _, best_ask, _ = self.get_best_bid_ask(order_depth)

        if best_bid is None or best_ask is None:
            return

        true_value = self.get_true_value(order_depth, position)
        if true_value is None:
            return

        momentum = self.get_momentum_signal()
        micro = self.get_microprice(order_depth)
        mid = self.get_mid_price(order_depth)

        if micro is None or mid is None:
            return

        to_buy = self.limit - position
        to_sell = self.limit + position

        # aggressive long bias if trend positive
        bullish = momentum > 0.4 and micro >= mid
        very_bullish = momentum > 1.0 and micro >= mid

        # exit / de-risk if trend turns
        bearish = momentum < -0.2 or micro < mid

        # -------------------------
        # 1. Hard exit first
        # -------------------------
        if position > 0 and bearish:
            remaining = min(position, 20)

            for price, volume in buy_orders:
                if remaining <= 0:
                    break
                qty = min(remaining, volume)
                if qty > 0:
                    self.sell(price, qty)
                    remaining -= qty

            if remaining > 0:
                self.sell(best_ask - 1, remaining)

            return

        # -------------------------
        # 2. Aggressive buying
        # -------------------------
        take_threshold = true_value + (1.2 if very_bullish else 0.6)

        for price, volume in sell_orders:
            if to_buy <= 0:
                break
            if price <= take_threshold:
                qty = min(to_buy, -volume)
                self.buy(price, qty)
                to_buy -= qty

        # -------------------------
        # 3. Passive support bid
        # -------------------------
        if to_buy > 0 and bullish:
            clip = 12 if very_bullish else 6
            bid_price = best_bid + 1
            qty = min(to_buy, clip)
            if qty > 0:
                self.buy(bid_price, qty)

        # -------------------------
        # 4. Light profit taking if inventory large
        # -------------------------
        if position > self.limit * 0.6:
            clip = min(to_sell, max(4, position // 4))
            if clip > 0:
                self.sell(best_ask - 1, clip)


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
