from typing import Literal, Optional


Side = Literal["buy", "sell"]


def add_order(book: dict[int, int], price: int, qty: int) -> dict[int, int]:
    new_book = book.copy()
    new_book[price] = new_book.get(price, 0) + qty
    return new_book


def compute_clearing(bids: dict[int, int], asks: dict[int, int]) -> tuple[int, int]:
    """
    Returns:
        clearing_price, clearing_volume
    """
    candidate_prices = sorted(set(bids.keys()) | set(asks.keys()))
    best_price = None
    best_volume = -1

    for p in candidate_prices:
        demand = sum(q for price, q in bids.items() if price >= p)
        supply = sum(q for price, q in asks.items() if price <= p)
        traded = min(demand, supply)

        if traded > best_volume or (traded == best_volume and (best_price is None or p > best_price)):
            best_volume = traded
            best_price = p

    if best_price is None:
        raise ValueError("No candidate prices found")

    return best_price, best_volume


def filled_buy_quantity(
    bids: dict[int, int],
    clearing_price: int,
    clearing_volume: int,
    my_price: int,
    my_qty: int,
    existing_qty_ahead_at_my_price: int,
) -> int:
    """
    Computes fill for YOUR buy order, assuming you are last in queue at my_price.
    """
    if my_price < clearing_price:
        return 0

    # Volume consumed by strictly better bid prices
    better_bid_volume = sum(q for price, q in bids.items() if price > my_price and price >= clearing_price)

    # Remaining matched volume available to my price level
    remaining_for_my_level = clearing_volume - better_bid_volume
    if remaining_for_my_level <= 0:
        return 0

    # Existing queue at my price goes before you
    fill_after_queue = remaining_for_my_level - existing_qty_ahead_at_my_price
    if fill_after_queue <= 0:
        return 0

    return min(my_qty, fill_after_queue)


def filled_sell_quantity(
    asks: dict[int, int],
    clearing_price: int,
    clearing_volume: int,
    my_price: int,
    my_qty: int,
    existing_qty_ahead_at_my_price: int,
) -> int:
    """
    Computes fill for YOUR sell order, assuming you are last in queue at my_price.
    Lower ask price has priority.
    """
    if my_price > clearing_price:
        return 0

    # Volume consumed by strictly better ask prices
    better_ask_volume = sum(q for price, q in asks.items() if price < my_price and price <= clearing_price)

    # Remaining matched volume available to my price level
    remaining_for_my_level = clearing_volume - better_ask_volume
    if remaining_for_my_level <= 0:
        return 0

    # Existing queue at my price goes before you
    fill_after_queue = remaining_for_my_level - existing_qty_ahead_at_my_price
    if fill_after_queue <= 0:
        return 0

    return min(my_qty, fill_after_queue)


def simulate_order(
    bids: dict[int, int],
    asks: dict[int, int],
    my_side: Side,
    my_price: int,
    my_qty: int,
    starting_position: int = 0,
) -> dict:
    """
    bids: positive quantities
    asks: positive quantities
    my_side: 'buy' or 'sell'
    my_price: price of your order
    my_qty: positive quantity
    starting_position: your position before auction

    Returns dict with:
      clearing_price
      clearing_volume
      filled_qty
      ending_position
    """
    if my_qty <= 0:
        raise ValueError("my_qty must be positive")

    existing_bids = bids.copy()
    existing_asks = asks.copy()

    if my_side == "buy":
        existing_qty_ahead = existing_bids.get(my_price, 0)
        new_bids = add_order(existing_bids, my_price, my_qty)
        new_asks = existing_asks
    else:
        existing_qty_ahead = existing_asks.get(my_price, 0)
        new_bids = existing_bids
        new_asks = add_order(existing_asks, my_price, my_qty)

    clearing_price, clearing_volume = compute_clearing(new_bids, new_asks)

    if my_side == "buy":
        filled_qty = filled_buy_quantity(
            bids=new_bids,
            clearing_price=clearing_price,
            clearing_volume=clearing_volume,
            my_price=my_price,
            my_qty=my_qty,
            existing_qty_ahead_at_my_price=existing_qty_ahead,
        )
        ending_position = starting_position + filled_qty
    else:
        filled_qty = filled_sell_quantity(
            asks=new_asks,
            clearing_price=clearing_price,
            clearing_volume=clearing_volume,
            my_price=my_price,
            my_qty=my_qty,
            existing_qty_ahead_at_my_price=existing_qty_ahead,
        )
        ending_position = starting_position - filled_qty

    return {
        "clearing_price": clearing_price,
        "clearing_volume": clearing_volume,
        "filled_qty": filled_qty,
        "ending_position": ending_position,
    }


# ---------------- DRYLAND FLAX ----------------

bids = {
    30: 30000,
    29: 5000,
    28: 12000,
    27: 28000,
}

asks = {
    28: 40000,
    31: 20000,
    32: 20000,
    33: 30000,
}

# Example: you place a buy order for 5000 at price 30
result = simulate_order(
    bids=bids,
    asks=asks,
    my_side="buy",
    my_price=30,
    my_qty=5000,
    starting_position=0,
)

print(result)

qty = list(range(1,100001))
prices = [30,29,28,27]

maxReturn = 0
maxPrice = 0
maxQty = 0
for num in qty:
    for price in prices:
        result = simulate_order(
            bids=bids,
            asks=asks,
            my_side="buy",
            my_price=price,
            my_qty=num,
            starting_position=0,
        )

        filled = result["filled_qty"]
        clearing_price = result["clearing_price"]
        ret = filled * (30 - clearing_price)

        if(ret>maxReturn):
            maxReturn = ret
            maxPrice = price
            maxQty = num

print(f'DRYLAND: bidding at ${maxPrice} and quantity: {maxQty} and return: {maxReturn}')

#_________________ EMBER MUSHROOM


bids1 = {
    20: 43000,
    19: 17000,
    18: 6000,
    17: 5000,
    16: 10000,
    15: 5000,
    14: 10000,
    13: 7000
}

asks1 = {
    12: 20000,
    13: 25000,
    14: 35000,
    15: 6000,
    16: 5000,
    17: 0,
    18: 10000,
    19: 12000
}

qty1 = list(range(1,100001))
prices1 = [22,21,20,19,18,17,16,15,14,13,12,11]

maxReturn1 = 0
maxPrice1 = 0
maxQty1 = 0
for num in qty1:
    for price in prices1:
        result = simulate_order(
            bids=bids1,
            asks=asks1,
            my_side="buy",
            my_price=price,
            my_qty=num,
            starting_position=0,
        )

        filled = result["filled_qty"]
        clearing_price = result["clearing_price"]
        ret = filled * (20 - clearing_price - 0.1)

        if(ret>maxReturn1):
            maxReturn1 = ret
            maxPrice1 = price
            maxQty1 = num
        elif(ret==maxReturn):
            if price < maxPrice1:
                maxPrice1 = price
                maxQty1 = num

print(f'MUSHROOM: bidding at ${maxPrice1} and quantity: {maxQty1} and return: {maxReturn1}')
print(simulate_order(
            bids=bids1,
            asks=asks1,
            my_side="buy",
            my_price=20,
            my_qty=19999,
            starting_position=0,
        ))
