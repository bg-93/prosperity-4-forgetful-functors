import numpy as np

NUM_PLAYERS = 1999
TRIALS = 5000   # can tune this

def research(x):
    return 200000 * np.log1p(x) / np.log(101)

def scale(y):
    return 7 * y / 100

def generate_others(trials=TRIALS, num_players=NUM_PLAYERS):
    n1 = int(0.3 * num_players)
    n2 = int(0.4 * num_players)
    n3 = num_players - n1 - n2

    others = np.concatenate([
        np.random.uniform(0, 100, size=(trials, n1)),
        np.random.normal(20, 5, size=(trials, n2)),
        np.random.normal(35, 7, size=(trials, n3)),
    ], axis=1)

    return np.clip(others, 0, 100)

def expected_speed_multipliers(others_matrix):
    """
    Returns E[s(z)] for z = 0,...,100
    """
    trials, num_players = others_matrix.shape
    n = num_players + 1

    s_mean = np.empty(101)

    for z in range(101):
        # rank = 1 + number strictly greater than z
        ranks = 1 + np.count_nonzero(others_matrix > z, axis=1)
        s = 0.9 - (ranks - 1) * (0.8 / (n - 1))
        s_mean[z] = s.mean()

    return s_mean

def optimise_allocation():
    others = generate_others()
    s_mean = expected_speed_multipliers(others)

    research_vals = np.array([research(x) for x in range(101)])
    scale_vals = np.array([scale(y) for y in range(101)])

    best_pnl = -np.inf
    best_alloc = None

    for z in range(101):
        s = s_mean[z]
        remaining = 100 - z

        for x in range(remaining + 1):
            y = remaining - x
            pnl = research_vals[x] * scale_vals[y] * s - 50000

            if pnl > best_pnl:
                best_pnl = pnl
                best_alloc = (x, y, z)

    return best_alloc, best_pnl, s_mean

best_alloc, best_pnl, s_mean = optimise_allocation()
print("Best allocation (Research, Scale, Speed):", best_alloc)
print("Best expected PnL:", best_pnl)
