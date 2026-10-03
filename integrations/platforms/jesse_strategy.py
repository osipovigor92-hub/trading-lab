"""Initial unoptimized EMA crossover for the free native Jesse research API."""
from jesse.strategies import Strategy


def ema(values, period):
    value, alpha = float(values[0]), 2 / (period + 1)
    for price in values[1:]:
        value += alpha * (float(price) - value)
    return value


class LabEMA(Strategy):
    def direction(self):
        values = self.candles[:, 2]
        if len(values) < 51:
            return 0
        a, b = ema(values, 20), ema(values, 50)
        old_a, old_b = ema(values[:-1], 20), ema(values[:-1], 50)
        return 1 if a > b and old_a <= old_b else -1 if a < b and old_a >= old_b else 0

    def should_long(self):
        return self.direction() == 1

    def should_short(self):
        return self.direction() == -1

    def should_cancel_entry(self):
        return True

    def go_long(self):
        qty = 100 / self.price
        self.buy = qty, self.price
        self.stop_loss = qty, self.price * .996
        self.take_profit = qty, self.price * 1.006

    def go_short(self):
        qty = 100 / self.price
        self.sell = qty, self.price
        self.stop_loss = qty, self.price * 1.004
        self.take_profit = qty, self.price * .994
