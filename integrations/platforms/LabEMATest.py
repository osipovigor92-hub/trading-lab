"""Initial unoptimized EMA crossover for native Freqtrade historical tests only."""
from freqtrade.strategy import IStrategy


class LabEMATest(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '5m'
    can_short = True
    startup_candle_count = 50
    minimal_roi = {'0': .006}
    stoploss = -.004
    process_only_new_candles = True

    def populate_indicators(self, dataframe, metadata):
        dataframe['ema20'] = dataframe['close'].ewm(span=20, adjust=False).mean()
        dataframe['ema50'] = dataframe['close'].ewm(span=50, adjust=False).mean()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        up = (dataframe.ema20 > dataframe.ema50) & (dataframe.ema20.shift(1) <= dataframe.ema50.shift(1))
        down = (dataframe.ema20 < dataframe.ema50) & (dataframe.ema20.shift(1) >= dataframe.ema50.shift(1))
        dataframe.loc[up & (dataframe.volume > 0), 'enter_long'] = 1
        dataframe.loc[down & (dataframe.volume > 0), 'enter_short'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[dataframe.ema20 < dataframe.ema50, 'exit_long'] = 1
        dataframe.loc[dataframe.ema20 > dataframe.ema50, 'exit_short'] = 1
        return dataframe
