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

        bid_size = max(0, min(max_clip, to_buy))
        ask_size = max(0, min(max_clip, to_sell))

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
    def act(self, state: TradingState) -> None:
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return

        best_bid, bid_vol = buy_orders[0]
        best_ask, ask_vol = sell_orders[0]
        ask_size = -ask_vol

        mid = (best_bid + best_ask) / 2
        if bid_vol + ask_size == 0:
            microprice = mid
        else:
            microprice = (best_ask * bid_vol + best_bid * ask_size) / (bid_vol + ask_size)

        if not hasattr(self, "history"):
            self.history = deque(maxlen=80)

        self.history.append(int(round(mid)))

        position = state.position.get(self.symbol, 0)
        limit = self.limit
        to_buy = limit - position
        to_sell = limit + position

        # -------- MOMENTUM --------
        short_mom = 0.0
        med_mom = 0.0
        long_mom = 0.0

        if len(self.history) >= 5:
            short_mom = self.history[-1] - self.history[-5]
        if len(self.history) >= 12:
            med_mom = self.history[-1] - self.history[-12]
        if len(self.history) >= 25:
            long_mom = self.history[-1] - self.history[-25]

        momentum = 0.65 * short_mom + 0.25 * med_mom + 0.10 * long_mom

        # -------- VERY AGGRESSIVE FAIR --------
        fair = (
            mid
            + 1.2 * momentum
            + 0.30 * (microprice - mid)
            - 0.005 * position
        )

        # -------- VERY AGGRESSIVE BUY SIZE --------
        if momentum >= 6:
            buy_clip = 80
        elif momentum >= 3:
            buy_clip = 50
        elif momentum >= 1:
            buy_clip = 35
        else:
            buy_clip = 20

        # keep buying until basically full
        can_buy = position <  limit

        # -------- TAKE ASKS HARD --------
        if can_buy:
            # willing to pay above fair in strong trend
            take_threshold = fair + 8
            if momentum >= 4:
                take_threshold = fair + 3
            if momentum >= 7:
                take_threshold = fair + 4

            for price, volume in sell_orders:
                if to_buy <= 0:
                    break

                ask_qty = -volume
                if price <= take_threshold:
                    qty = min(buy_clip, to_buy, ask_qty)
                    if qty > 0:
                        self.buy(price, qty)
                        to_buy -= qty
                        position += qty

        # recompute
        to_buy = limit - position
        to_sell = limit + position

        # -------- POST AGGRESSIVE BID --------
        if to_buy > 0 and can_buy:
            spread = best_ask - best_bid

            if momentum >= 5:
                bid_price = best_ask      # join the ask / cross next if available
            elif spread >= 2:
                bid_price = best_bid + 1  # improve bid
            else:
                bid_price = best_bid      # stay at best bid if tight

            qty = min(buy_clip, to_buy)
            if qty > 0:
                self.buy(int(round(bid_price)), qty)

        # -------- ONLY TINY INVENTORY BLEED --------
        # do not meaningfully sell unless almost max long
        if position >= int(0.95 * limit) and to_sell > 0:
            ask_price = best_ask + 3
            qty = min(8, position, to_sell)
            if qty > 0:
                self.sell(ask_price, qty)

    def save(self) -> JSON:
        return {
            "window": list(self.window),
            "history": list(self.history),
        }

    def load(self, data: JSON) -> None:
        if isinstance(data, dict):
            window_data = data.get("window", [])
            history_data = data.get("history", [])

            if isinstance(window_data, list):
                self.window = deque(window_data, maxlen=self.window_size)
            else:
                self.window = deque([], maxlen=self.window_size)

            if isinstance(history_data, list):
                self.history = deque((int(x) for x in history_data), maxlen=80)
            else:
                self.history = deque([], maxlen=80)
        else:
            self.window = deque([], maxlen=self.window_size)
            self.history = deque([], maxlen=80)

    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]

        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return 10_000

        best_bid, bid_vol = buy_orders[0]
        best_ask, ask_vol = sell_orders[0]

        ask_vol = -ask_vol

        fair = (best_bid + best_ask) / 2

        return round(fair)



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
