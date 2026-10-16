import unittest
import numpy as np
from backtest.strategy import StrategyContext
from backtest.breakout import BreakoutStrategy
from test_backtest import market, broker


class BreakoutTests(unittest.TestCase):
    def context(self,data,holding=0):
        date=data.dates[-1]
        return StrategyContext(date,data.symbols,100000,100000,{"A":holding},
                               lambda field,lookback,adjusted:data.history(date,field,lookback,adjusted))

    def test_entry_excludes_current_high(self):
        d=market([10]*20+[11])
        self.assertEqual(BreakoutStrategy().on_close(self.context(d)),{"A":.98})

    def test_exit_excludes_current_low(self):
        d=market([10]*20+[9])
        self.assertEqual(BreakoutStrategy().on_close(self.context(d,100)),{})

    def test_holding_does_not_rebalance_every_day(self):
        d=market([10]*20+[11])
        self.assertIsNone(BreakoutStrategy().on_close(self.context(d,100)))

    def test_amount_confirmation_uses_prior_twenty_days(self):
        d=market([10]*20+[11])
        d._frames["amt"].iloc[-1,0]=1400000
        self.assertIsNone(BreakoutStrategy(amount_multiplier=1.5).on_close(self.context(d)))
        d._frames["amt"].iloc[-1,0]=1600000
        self.assertEqual(BreakoutStrategy(amount_multiplier=1.5).on_close(self.context(d)),{"A":.98})

    def test_zero_amount_vetoes_fill(self):
        d=market()
        d._frames["amt"].iloc[1,0]=0
        b=broker(d)
        self.assertEqual(b.trade(d.dates[1],"A","BUY",100).reason,"ZERO_OR_MISSING_DAILY_AMOUNT")

    def test_missing_high_does_not_generate_breakout(self):
        d=market([10]*20+[11])
        d._frames["high"].iloc[3,0]=np.nan
        self.assertIsNone(BreakoutStrategy().on_close(self.context(d)))
