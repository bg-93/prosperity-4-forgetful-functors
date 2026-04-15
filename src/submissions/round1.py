import json
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

        #array appending whether or not position has pinned to the limit
        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

        #variables indicating how often we are hitting our position limit
        soft_liquidate = len(self.window) == self.window_size and sum(self.window) >= self.window_size / 2 and self.window[-1]
        hard_liquidate = len(self.window) == self.window_size and all(self.window)

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
        if to_buy > 0 and hard_liquidate:
            quantity = to_buy // 2
            self.buy(true_value, quantity)
            to_buy -= quantity

        # same as above but for less amount of previous ticks we've hit our limit
        # still need to buy more but less aggressively
        if to_buy > 0 and soft_liquidate:
            quantity = to_buy // 2
            self.buy(true_value - 2, quantity)
            to_buy -= quantity

        # if we have enough position to buy, then place a bid that beats the most popular bid
        # by 1
        if to_buy > 0 and buy_orders:
            popular_buy_price = max(buy_orders, key=lambda tup: tup[1])[0]
            price = min(max_buy_price, popular_buy_price + 1)
            self.buy(price, to_buy)

        # the following is symmetric for sell side
        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        if to_sell > 0 and hard_liquidate:
            quantity = to_sell // 2
            self.sell(true_value, quantity)
            to_sell -= quantity

        if to_sell > 0 and soft_liquidate:
            quantity = to_sell // 2
            self.sell(true_value + 2, quantity)
            to_sell -= quantity

        if to_sell > 0 and sell_orders:
            popular_sell_price = min(sell_orders, key=lambda tup: tup[1])[0]
            price = max(min_sell_price, popular_sell_price - 1)
            self.sell(price, to_sell)

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

        if buy_orders and sell_orders:
            popular_buy_price = max(buy_orders, key=lambda tup: tup[1])[0]
            popular_sell_price = min(sell_orders, key=lambda tup: tup[1])[0]
            return round((popular_buy_price + popular_sell_price) / 2)

        if buy_orders:
            return buy_orders[0][0]

        if sell_orders:
            return sell_orders[0][0]

        return 10_000

class OrchidsStrategy(Strategy):
    def act(self, state: TradingState) -> None:
        position = state.position.get(self.symbol, 0)
        self.convert(-1 * position)

        obs = state.observations.conversionObservations.get(self.symbol, None)
        if obs is None:
            return

        buy_price = obs.askPrice + obs.transportFees + obs.importTariff
        self.sell(max(int(obs.bidPrice - 0.5), int(buy_price + 1)), self.limit)

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
