import unittest
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
from backtest.breakout_pool import BreakoutSpec, PoolBreakout


def context(count=3, holdings=None, latest=12., amount=30_100_000., cutoff=60):
    symbols=tuple(f"{i+1:06d}.SZ" for i in range(count))
    dates=pd.bdate_range("2024-01-01",periods=80)
    frames={name:pd.DataFrame(value,index=dates,columns=symbols) for name,value in
            {"close":10.,"high":11.,"low":9.,"amt":20_000_000.,"num_trades":1000.,"cumadj":1.}.items()}
    frames["close"].iloc[60]=latest
    frames["high"].iloc[60]=99. # today's high must never become today's entry threshold
    frames["amt"].iloc[60]=amount
    states={name:pd.DataFrame(value,index=dates,columns=symbols) for name,value in {"isST":0.,"tradestatus":1.}.items()}
    def history(field,lookback=None,adjusted=True):
        start=max(0,cutoff+1-lookback) if lookback else 0
        frame=frames[field].iloc[start:cutoff+1].copy()
        return frame*frames["cumadj"].iloc[start:cutoff+1] if adjusted else frame
    def state(field,lookback=1):return states[field].iloc[max(0,cutoff+1-lookback):cutoff+1].copy()
    cash=1_000_000.-sum(qty*frames["close"].loc[dates[cutoff],s] for s,qty in (holdings or {}).items())
    result=SimpleNamespace(symbols=symbols,date=dates[cutoff],equity=1_000_000.,cash=cash,
                           positions={s:(holdings or {}).get(s,0) for s in symbols},history=history,states=state)
    return result,frames,states


class PoolBreakoutTests(unittest.TestCase):
    def test_channel_and_amount_reference_exclude_signal_day(self):
        ctx,_,_=context()
        strategy=PoolBreakout(BreakoutSpec("test","test",amount_multiplier=1.5,max_positions=2))
        weights=strategy.on_close(ctx)
        self.assertEqual(list(weights),["000001.SZ","000002.SZ"])
        self.assertAlmostEqual(sum(weights.values()),.95)

    def test_adjust_all_price_fields_and_exclude_st_unknown(self):
        ctx,frames,states=context()
        frames["close"].iloc[60]=6
        frames["cumadj"].iloc[60]=2
        states["isST"].iloc[60]=[0,1,np.nan]
        weights=PoolBreakout(BreakoutSpec("test","test")).on_close(ctx)
        self.assertEqual(list(weights),["000001.SZ"])

    def test_exit_intent_survives_rejection_and_occupies_slot(self):
        spec=BreakoutSpec("test","test",max_positions=2)
        strategy=PoolBreakout(spec)
        held={"000001.SZ":1000,"000002.SZ":1000}
        ctx,frames,_=context(holdings=held)
        frames["close"].iloc[60,0]=8
        frames["low"].iloc[60,0]=1 # exclude today's low from exit threshold
        first=strategy.on_close(ctx)
        self.assertNotIn("000001.SZ",first)
        self.assertNotIn("000003.SZ",first)
        # Assume the sale failed; price recovers but actual shares are still held.
        frames["close"].iloc[60,0]=10
        retry=strategy.on_close(ctx)
        self.assertNotIn("000001.SZ",retry)
        self.assertNotIn("000003.SZ",retry)
        ctx.positions["000001.SZ"]=0
        after_sale=strategy.on_close(ctx)
        self.assertIn("000003.SZ",after_sale)

    def test_no_daily_equal_weight_rebalance_or_partial_topup(self):
        ctx,frames,_=context(holdings={"000001.SZ":100})
        frames["close"].iloc[60]=10
        strategy=PoolBreakout(BreakoutSpec("test","test"))
        self.assertIsNone(strategy.on_close(ctx))
        frames["close"].iloc[60,1]=12
        weights=strategy.on_close(ctx)
        self.assertAlmostEqual(weights["000001.SZ"]*ctx.equity/10,100,places=6)

    def test_atr_position_size_and_close_only_persistent_stop(self):
        ctx,frames,_=context()
        frames["high"].iloc[60]=13
        defensive=BreakoutSpec("test","test",atr_risk=.001,atr_stop=3)
        weights=PoolBreakout(defensive).on_close(ctx)
        self.assertLess(weights["000001.SZ"],.95/20)
        ctx.positions["000001.SZ"]=100
        strategy=PoolBreakout(defensive)
        strategy.peaks["000001.SZ"]=25 # previously observed close while actually held
        weights=strategy.on_close(ctx)
        self.assertNotIn("000001.SZ",weights)
        self.assertIn("000001.SZ",strategy.exiting)

    def test_future_prices_and_state_do_not_change_prefix(self):
        left,_,_=context()
        right,frames,states=context()
        for frame in frames.values():frame.iloc[61:]=999999
        states["isST"].iloc[61:]=1
        spec=BreakoutSpec("test","test",amount_multiplier=1.5,trend_filter=True,atr_risk=.001)
        self.assertEqual(PoolBreakout(spec).on_close(left),PoolBreakout(spec).on_close(right))

    def test_trend_requires_complete_sixty_session_window(self):
        ctx,frames,_=context()
        # Still 60 good observations in61 sessions, but MA60 itself has a missing day.
        frames["close"].iloc[10]=np.nan
        spec=BreakoutSpec("test","test",trend_filter=True)
        self.assertIsNone(PoolBreakout(spec).on_close(ctx))


if __name__=="__main__":unittest.main()
