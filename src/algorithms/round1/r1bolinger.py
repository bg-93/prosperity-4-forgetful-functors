import json
import math
from typing import cast
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

        #array appending whether or not position has pinned to the limit
        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

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
            self.buy(price, bid_size)

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
            self.sell(price, ask_size)

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
    def __init__(self, symbol: Symbol, limit: int) -> None:
        super().__init__(symbol, limit)
        self.price_history: deque[float] = deque(maxlen=20)

    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if buy_orders and sell_orders:
            best_bid, _ = buy_orders[0]
            best_ask, _ = sell_orders[0]
            return (best_bid + best_ask) // 2
        elif buy_orders:
            return buy_orders[0][0]
        elif sell_orders:
            return sell_orders[0][0]
        else:
            return 0

    def act(self, state: TradingState) -> None:
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders and not sell_orders:
            return

        position = state.position.get(self.symbol, 0)
        limit = self.limit
        to_buy = limit - position
        to_sell = limit + position

        max_clip = 20
        take_edge = 1
        make_edge = 1

        best_bid = 0
        bid_vol = 0
        best_ask = 0
        ask_vol = 0

        if buy_orders:
            best_bid, bid_vol = buy_orders[0]
        if sell_orders:
            best_ask, ask_vol = sell_orders[0]

        # --------- ANCHOR PRICES ---------
        if buy_orders and sell_orders:
            mid = (best_bid + best_ask) / 2
            total_vol = bid_vol + (-ask_vol)
            if total_vol > 0:
                microprice = (best_ask * bid_vol + best_bid * (-ask_vol)) / total_vol
            else:
                microprice = mid
        elif buy_orders:
            mid = float(best_bid)
            microprice = mid
        else:
            mid = float(best_ask)
            microprice = mid

        self.price_history.append(mid)

        # Not enough history yet: fall back to simple quoting
        if len(self.price_history) < 5:
            fair = mid - 1.0 * (position / limit)

            if sell_orders:
                for price, volume in sell_orders:
                    if to_buy > 0 and price <= fair - take_edge:
                        qty = min(max_clip, to_buy, -volume)
                        self.buy(price, qty)
                        to_buy -= qty

            if buy_orders:
                for price, volume in buy_orders:
                    if to_sell > 0 and price >= fair + take_edge:
                        qty = min(max_clip, to_sell, volume)
                        self.sell(price, qty)
                        to_sell -= qty

            if buy_orders and to_buy > 0:
                self.buy(best_bid + 1, min(max_clip, to_buy))
            if sell_orders and to_sell > 0:
                self.sell(best_ask - 1, min(max_clip, to_sell))
            return

        # --------- BOLLINGER BANDS ---------
        prices = list(self.price_history)
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        std_price = math.sqrt(variance)

        k = 100.0
        upper_band = mean_price + k * std_price
        lower_band = mean_price - k * std_price

        # --------- TREND ---------
        momentum = prices[-1] - prices[0]
        uptrend = momentum > 0
        downtrend = momentum < 0

        # --------- FAIR VALUE ---------
        # Base fair comes from Bollinger middle band
        fair = mean_price

        # Small microstructure adjustment
        fair += 0.25 * (microprice - mid)

        # Small momentum adjustment
        fair += 0.25 * momentum

        # Inventory control
        fair -= 1.5 * (position / limit)

        # --------- BAND POSITION SIGNAL ---------
        # Negative => near/below lower band
        # Positive => near/above upper band
        if std_price > 1e-6:
            zscore = (mid - mean_price) / std_price
        else:
            zscore = 0.0

        # --------- TAKE LOGIC ---------
        # Buy more aggressively on pullbacks in an uptrend
        if sell_orders:
            for price, volume in sell_orders:
                if to_buy <= 0:
                    break

                ask_size = -volume
                buy_threshold = fair - take_edge

                if uptrend and mid <= mean_price:
                    buy_threshold += 1
                if mid <= lower_band:
                    buy_threshold += 2

                if price <= buy_threshold:
                    qty = min(max_clip, to_buy, ask_size)
                    self.buy(price, qty)
                    to_buy -= qty
                    position += qty

        # Sell more selectively, especially in uptrend
        if buy_orders:
            for price, volume in buy_orders:
                if to_sell <= 0:
                    break

                bid_size = volume
                sell_threshold = fair + take_edge

                if uptrend:
                    sell_threshold += 1
                if mid >= upper_band:
                    sell_threshold -= 1  # okay to realize gains if stretched

                if price >= sell_threshold:
                    qty = min(max_clip, to_sell, bid_size)
                    self.sell(price, qty)
                    to_sell -= qty
                    position -= qty

        # --------- PASSIVE QUOTING ---------


        # BUY SIDE (more aggressive in uptrend)
        if to_buy > 0:
            if uptrend:
                bid_price = best_bid + 1
            else:
                bid_price = int(fair - make_edge)

            qty = min(max_clip, to_buy)
            self.buy(bid_price, qty)

        # SELL SIDE (much more conservative in uptrend)
        if to_sell > 0:
            if uptrend:
                ask_price = best_ask + 2 # push higher
            else:
                ask_price = max(int(fair + make_edge), best_ask - 1)

            qty = min(max_clip, to_sell)
            self.sell(ask_price, qty)


    def save(self) -> JSON:
        return {
            "window": list(self.window),
            "price_history": list(self.price_history),
        }

    def load(self, data: JSON) -> None:
        self.window = deque([], maxlen=self.window_size)
        self.price_history = deque([], maxlen=20)

        if isinstance(data, dict):
            if isinstance(data.get("window"), list):
                self.window = deque(cast(list, data["window"]), maxlen=self.window_size)
            if isinstance(data.get("price_history"), list):
                self.price_history = deque(cast(list, data["price_history"]), maxlen=20)

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
