from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from backtest.broker import SimBroker
from backtest.clock import SimClock
from backtest.data import FIELDS, MarketData
from backtest.engine import BacktestEngine
from backtest.limits import LimitPolicy
from backtest.models import BacktestConfig, FeeModel
from backtest.report import export_result
from backtest.strategy import PeriodicEqualWeight


def market(close=None, opens=None, factors=None, symbols=("A",), start="2024-01-02"):
    close = np.array(close if close is not None else [10,10,10,10], dtype=float)
    if close.ndim == 1:
        close = close[:,None]
    n = close.shape[0]
    dates = pd.bdate_range(start, periods=n)
    opens = np.array(opens, dtype=float).reshape(close.shape) if opens is not None else close.copy()
    factors = np.array(factors, dtype=float).reshape(close.shape) if factors is not None else np.ones(close.shape)
    frames = {}
    for f in FIELDS:
        if f == "cumadj": values = factors
        elif f == "open": values = opens
        elif f == "high": values = np.maximum(opens, close)
        elif f == "low": values = np.minimum(opens, close)
        elif f == "close": values = close
        else: values = np.full(close.shape, 1000000.0)
        frames[f] = pd.DataFrame(values, index=dates, columns=symbols)
    return MarketData(frames)


def exact_policy(data, overrides=None):
    overrides = overrides or {}
    rows = []
    for date in data.dates:
        for s in data.symbols:
            row = {"date":date,"symbol":s,"upper_limit":np.nan,"lower_limit":np.nan,
                   "no_limit":1,"suspended":0}
            row.update(overrides.get((date,s), {}))
            rows.append(row)
    return LimitPolicy("strict", pd.DataFrame(rows))


def broker(data, cash=10000, overrides=None, fees=None):
    return SimBroker(data, BacktestConfig(cash), fees or FeeModel(0,0,0), exact_policy(data, overrides))


class Always:
    def __init__(self, weights): self.weights = weights
    def on_close(self, context): return self.weights


class BacktestTests(unittest.TestCase):
    def test_clock_orders_open_before_close(self):
        dates = pd.bdate_range("2024-01-01",periods=2)
        self.assertEqual([t.phase for t in SimClock(dates)], ["OPEN","CLOSE","OPEN","CLOSE"])

    def test_next_session_open_no_same_close_fill(self):
        d = market([10,11,12], opens=[10,11,12])
        r = BacktestEngine(d, BacktestConfig(10000), FeeModel(0,0,0), exact_policy(d)).run(Always({"A":0.5}))
        first = r.orders.iloc[0]
        self.assertEqual(first.signal_date, "2024-01-02")
        self.assertEqual(first.execution_date, "2024-01-03")
        self.assertEqual(first.raw_execution_price, 11)
        self.assertEqual(r.equity.iloc[0].market_value, 0)

    def test_context_is_asof_and_history_is_a_copy(self):
        d = market([10,11,12,13])
        seen = []
        class Inspect:
            def on_close(self, ctx):
                values = ctx.history()
                seen.append((values.index[-1], ctx.date, len(values)))
                values.iloc[:,:] = -99
                return None
        BacktestEngine(d).run(Inspect())
        self.assertTrue(all(a == b for a,b,_ in seen))
        self.assertEqual([x[2] for x in seen], [1,2,3,4])
        self.assertEqual(d.raw("close",d.dates[0],"A"),10)

    def test_split_does_not_destroy_account_value(self):
        d = market([10,5,5], factors=[1,2,2])
        b = broker(d)
        b.trade(d.dates[0],"A","BUY",100)
        self.assertEqual(b.mark(d.dates[1],"close"),10000)
        row = b.position_rows(d.dates[1],10000)[0]
        self.assertEqual(row["adjusted_units"],100)
        self.assertEqual(row["raw_equivalent_qty"],200)
        self.assertEqual(b.cash,9000)  # 没有凭空添加一份分红现金。

    def test_dividend_adjusted_units_continuity(self):
        d = market([10,9,9], factors=[1,10/9,10/9])
        b = broker(d)
        b.trade(d.dates[0],"A","BUY",100)
        self.assertAlmostEqual(b.mark(d.dates[1],"close"),10000)
        self.assertEqual(b.cash,9000)

    def test_exact_limit_up_rejects_buy(self):
        d = market([10,11,11])
        b = broker(d, overrides={(d.dates[1],"A"):{"no_limit":0,"upper_limit":11,"lower_limit":9}})
        o = b.trade(d.dates[1],"A","BUY",100)
        self.assertEqual(o.reason,"LIMIT_UP_OR_CONSERVATIVE_GUARD")
        self.assertEqual(b.positions["A"],0)
        self.assertEqual(b.cash,10000)

    def test_exact_limit_down_rejects_sell(self):
        d = market([10,9,9])
        b = broker(d, overrides={(d.dates[1],"A"):{"no_limit":0,"upper_limit":11,"lower_limit":9}})
        b.trade(d.dates[0],"A","BUY",100)
        self.assertEqual(b.trade(d.dates[1],"A","SELL",100).reason,"LIMIT_DOWN_OR_CONSERVATIVE_GUARD")
        self.assertEqual(b.positions["A"],100)

    def test_strict_missing_data_fails_closed(self):
        d = market()
        b = SimBroker(d,BacktestConfig(),FeeModel(0,0,0),LimitPolicy("strict"))
        self.assertEqual(b.trade(d.dates[1],"A","BUY",100).reason,"MISSING_PRICE_LIMITS")
        self.assertEqual(b.positions["A"],0)

    def test_conservative_guard_and_direction(self):
        d = market([10,10.5,9])
        b = SimBroker(d,BacktestConfig(limit_mode="conservative"),FeeModel(0,0,0),LimitPolicy("conservative"))
        self.assertEqual(b.trade(d.dates[1],"A","BUY",100).reason,"LIMIT_UP_OR_CONSERVATIVE_GUARD")
        # 下跌本身不是禁止买入的理由；代理仅保守约束买涨、卖跌。
        self.assertEqual(b.trade(d.dates[2],"A","BUY",100).status,"FILLED")

    def test_conservative_reference_adjusts_corporate_action(self):
        d = market([10,5,5], factors=[1,2,2])
        self.assertEqual(d.previous_reference(d.dates[1],"A"),5)

    def test_t_plus_one(self):
        d = market()
        b = broker(d)
        b.trade(d.dates[0],"A","BUY",100)
        self.assertEqual(b.trade(d.dates[0],"A","SELL",100).reason,"T_PLUS_ONE_OR_NO_POSITION")
        self.assertEqual(b.trade(d.dates[1],"A","SELL",100).status,"FILLED")

    def test_commission_reserved_before_buy(self):
        d = market()
        b = broker(d,cash=1004,fees=FeeModel(0.0003,5,0))
        self.assertEqual(b.trade(d.dates[0],"A","BUY",100).reason,"INSUFFICIENT_CASH")
        b = broker(d,cash=1005,fees=FeeModel(0.0003,5,0))
        self.assertEqual(b.trade(d.dates[0],"A","BUY",100).status,"FILLED")
        self.assertAlmostEqual(b.cash,0)

    def test_historical_sell_stamp_tax(self):
        fees = FeeModel(0,0,0)
        self.assertEqual(fees.fees(10000,"SELL","2023-08-25"),(0,10))
        self.assertEqual(fees.fees(10000,"SELL","2023-08-28"),(0,5))
        self.assertEqual(fees.fees(10000,"BUY","2023-08-25"),(0,0))

    def test_missing_open_is_not_forward_filled_for_execution(self):
        d = market([10,10,10],opens=[10,np.nan,10])
        b = broker(d)
        self.assertEqual(b.trade(d.dates[1],"A","BUY",100).reason,"UNAVAILABLE_OPEN_OR_FACTOR")

    def test_missing_close_is_flagged_not_silently_zeroed(self):
        d = market([10,10,np.nan],opens=[10,10,10])
        r = BacktestEngine(d,BacktestConfig(10000),FeeModel(0,0,0),exact_policy(d)).run(Always({"A":0.5}))
        self.assertEqual(r.equity.iloc[-1].equity,10000)
        self.assertEqual(r.metrics["stale_valuation_days"],1)

    def test_failed_sell_does_not_release_cash_for_buy(self):
        d = market([[10,10],[10,10],[10,10]],symbols=("A","B"))
        b = broker(d,overrides={(d.dates[1],"A"):{"no_limit":0,"upper_limit":12,"lower_limit":10}})
        b.rebalance(d.dates[0],d.dates[0],{"A":1})
        b.rebalance(d.dates[1],d.dates[0],{"B":1})
        self.assertEqual(b.positions["A"],1000)
        self.assertEqual(b.positions["B"],0)
        self.assertEqual(b.cash,0)

    def test_no_same_day_high_low_close_amt_in_open_execution(self):
        d = market([10,50,10],opens=[10,10,10])
        b = broker(d)
        b.trade(d.dates[1],"A","BUY",100)
        self.assertEqual(b.orders[-1].raw_execution_price,10)
        self.assertEqual(b.orders[-1].notional,1000)

    def test_last_day_signal_is_not_filled(self):
        d = market([10,10])
        class LastDay:
            def on_close(self,ctx):
                return {"A":1} if ctx.date == d.dates[-1] else None
        r = BacktestEngine(d,limits=exact_policy(d)).run(LastDay())
        self.assertTrue(r.orders.empty)
        self.assertTrue(r.metrics["unexecuted_final_signal"])
        self.assertEqual(r.signals.iloc[0].execution,"OUTSIDE_BACKTEST_RANGE")

    def test_invalid_weights_rejected(self):
        for weights in ({"A":-0.1},{"A":1.1},{"A":float("nan")},{"UNKNOWN":0.5}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                BacktestEngine(market()).run(Always(weights))

    def test_data_alignment_rejected(self):
        d = market()
        frames = {k:v.copy() for k,v in d._frames.items()}
        frames["open"] = frames["open"].iloc[::-1]
        with self.assertRaises(ValueError): MarketData(frames)

    def test_exact_limits_duplicate_rejected(self):
        row = {"date":"2024-01-02","symbol":"A","upper_limit":11,"lower_limit":9,"no_limit":0,"suspended":0}
        with self.assertRaises(ValueError): LimitPolicy("strict",pd.DataFrame([row,row]))

    def test_suspended_external_record(self):
        d = market()
        b = broker(d,overrides={(d.dates[1],"A"):{"suspended":1}})
        self.assertEqual(b.trade(d.dates[1],"A","BUY",100).reason,"SUSPENDED")

    def test_engine_cannot_reuse_state(self):
        engine = BacktestEngine(market())
        engine.run(Always({}))
        with self.assertRaises(RuntimeError): engine.run(Always({}))

    def test_cash_positions_and_equity_reconcile(self):
        d = market([[10,20],[11,19],[12,18],[10,20]],symbols=("A","B"))
        r = BacktestEngine(d,BacktestConfig(100000),FeeModel(),exact_policy(d)).run(PeriodicEqualWeight(1))
        values = r.positions.groupby("date")["market_value"].sum()
        np.testing.assert_allclose(r.equity["cash"]+values.to_numpy(),r.equity["equity"])
        self.assertTrue((r.equity.cash >= 0).all())
        self.assertAlmostEqual(r.metrics["total_fees"],r.orders.commission.sum()+r.orders.stamp_tax.sum())

    def test_report_and_records_export(self):
        d = market()
        r = BacktestEngine(d,limits=exact_policy(d)).run(PeriodicEqualWeight())
        with tempfile.TemporaryDirectory() as tmp:
            path = export_result(r,tmp)
            self.assertIn("复权单位",path.read_text())
            self.assertIn("<polyline",path.read_text())
            stored = json.loads((Path(tmp)/"metrics.json").read_text())
            self.assertEqual(stored["filled_orders"],r.metrics["filled_orders"])
            self.assertEqual(len(pd.read_csv(Path(tmp)/"equity.csv")),len(d.dates))

    def test_future_data_does_not_change_earlier_account(self):
        d = market([[10,20],[11,19],[12,18],[10,20],[11,21],[12,22]],symbols=("A","B"))
        early = MarketData({k:v.iloc[:4].copy() for k,v in d._frames.items()})
        full_result = BacktestEngine(d,BacktestConfig(100000),FeeModel(),exact_policy(d)).run(PeriodicEqualWeight(1))
        early_result = BacktestEngine(early,BacktestConfig(100000),FeeModel(),exact_policy(early)).run(PeriodicEqualWeight(1))
        pd.testing.assert_frame_equal(full_result.equity.iloc[:4].reset_index(drop=True),early_result.equity)
        pd.testing.assert_frame_equal(full_result.orders.iloc[:len(early_result.orders)].reset_index(drop=True),early_result.orders)

    def test_absolute_factor_normalization_does_not_change_returns(self):
        d = market([10,10,5,5.5], factors=[98,98,196,196])
        scaled = {k:v.copy() for k,v in d._frames.items()}
        scaled["cumadj"] *= 100
        other = MarketData(scaled)
        a = BacktestEngine(d,BacktestConfig(10000),FeeModel(0,0,0),exact_policy(d)).run(PeriodicEqualWeight(20))
        b = BacktestEngine(other,BacktestConfig(10000),FeeModel(0,0,0),exact_policy(other)).run(PeriodicEqualWeight(20))
        np.testing.assert_allclose(a.equity.equity,b.equity.equity)

    def test_cannot_adjust_amount_or_trade_count(self):
        d = market()
        with self.assertRaises(ValueError): d.history(d.dates[-1],"amt",adjusted=True)

    def test_nan_exact_limit_date_rejected(self):
        row = {"date":pd.NaT,"symbol":"A","upper_limit":11,"lower_limit":9,"no_limit":0,"suspended":0}
        with self.assertRaises(ValueError): LimitPolicy("strict",pd.DataFrame([row]))


if __name__ == "__main__":
    unittest.main()
