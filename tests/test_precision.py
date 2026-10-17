import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from backtest.precision import Panel,PrecisionEngine,PrecisionConfig,Reversal5DR,ReversalSpec,MissingActions,bounds


def fixture():
    dates=pd.bdate_range("2024-01-01",periods=100)
    columns=["000001.SZ","600001.SH","688001.SH"]
    close=pd.DataFrame(10.,index=dates,columns=columns)
    frames={k:close.copy() for k in ("open","high","low","close","amt","num_trades","cumadj")}
    frames["high"][:]=11.;frames["low"][:]=9.
    frames["amt"][:]=1e8;frames["num_trades"][:]=1e4;frames["cumadj"][:]=1.
    states={k:close.copy() for k in ("isST","tradestatus","preclose")}
    states["isST"][:]=0.;states["tradestatus"][:]=1.
    return frames,states


class PrecisionTests(unittest.TestCase):
    def engine(self,frames=None,states=None,events=None,config=None):
        f,s=fixture()
        return PrecisionEngine(Panel(frames or f,states or s,events),config or PrecisionConfig())

    def spec(self,**kwargs):
        return ReversalSpec("test","test",top_n=1,**kwargs)

    def test_half_up_limit_price(self):
        self.assertEqual(bounds(5.75,.1),(5.18,6.33))
        self.assertEqual(bounds(.05,.1),(.04,.06))

    def test_first_session_uses_pre_period_signal(self):
        engine=self.engine();p=engine.p
        result=engine.run(Reversal5DR(self.spec()),p.dates[70],p.dates[75])
        first=result["orders"].iloc[0]
        self.assertEqual(first.signal_date,str(p.dates[69].date()))
        self.assertEqual(first.execution_date,str(p.dates[70].date()))
        self.assertEqual(first.sizing_reference_close,10.)

    def test_st_and_unknown_excluded_from_ranking(self):
        f,s=fixture();s["isST"].iloc[70,0]=1;s["isST"].iloc[70,1]=np.nan
        p=Panel(f,s);w,_=Reversal5DR(self.spec()).weights(p,70,{},0)
        self.assertEqual(set(w),{2})

    def test_emergency_exit_does_not_overallocate_after_failed_sales(self):
        f,s=fixture();s["isST"].iloc[70,2]=1
        p=Panel(f,s);strategy=Reversal5DR(self.spec(every=5))
        weights,_=strategy.weights(p,70,{0:1000,1:1000,2:1000},1)
        self.assertLessEqual(sum(weights.values()),.95+1e-10)
        self.assertEqual(len(weights),1)

    def test_new_st_at_execution_cannot_buy(self):
        f,s=fixture();s["isST"].iloc[70,0]=1
        engine=self.engine(f,s);p=engine.p
        result=engine.run(Reversal5DR(self.spec()),p.dates[70],p.dates[72])
        first=result["orders"].iloc[0]
        self.assertEqual(first.reason,"ST_EXCLUDED_AT_EXECUTION")

    def test_limit_up_buy_and_limit_down_sell_rejected(self):
        f,s=fixture();f["open"].iloc[70,0]=11
        e=self.engine(f,s);r=e.run(Reversal5DR(self.spec()),e.p.dates[70],e.p.dates[72])
        self.assertEqual(r["orders"].iloc[0].reason,"LIMIT_UP_CANNOT_BUY")
        f,s=fixture();f["close"].iloc[71,0]=12;f["high"].iloc[71,0]=12
        f["open"].iloc[72,0]=9;s["preclose"].iloc[72,0]=10
        e=self.engine(f,s);r=e.run(Reversal5DR(self.spec()),e.p.dates[70],e.p.dates[74])
        self.assertIn("LIMIT_DOWN_CANNOT_SELL",r["orders"].reason.tolist())

    def test_quantity_does_not_use_future_open(self):
        f,s=fixture();base=self.engine(f,s);r=base.run(Reversal5DR(self.spec()),base.p.dates[70],base.p.dates[72])
        f["open"].iloc[70,0]=10.5
        changed=self.engine(f,s);r2=changed.run(Reversal5DR(self.spec()),changed.p.dates[70],changed.p.dates[72])
        self.assertEqual(r["orders"].iloc[0].requested_qty,r2["orders"].iloc[0].requested_qty)
        self.assertEqual(r["orders"].iloc[0].planned_qty,r2["orders"].iloc[0].planned_qty)

    def test_cash_dividend_is_cash_not_synthetic_share_growth(self):
        f,s=fixture();dates=f["close"].index;day=str(dates[72].date())
        f["close"].iloc[72:,0]=9;f["open"].iloc[72:,0]=9
        f["cumadj"].iloc[72:,0]=10/9
        s["preclose"].iloc[72:,0]=9
        event={"dividRegistDate":str(dates[71].date()),"dividOperateDate":day,
               "dividPayDate":str(dates[73].date()),"dividCashPsBeforeTax":"1"}
        e=self.engine(f,s,{("000001.SZ",2024):[event]})
        r=e.run(Reversal5DR(self.spec(every=100)),dates[70],dates[75])
        before=r["positions"][r["positions"].date==str(dates[71].date())]
        ex=r["positions"][r["positions"].date==day]
        self.assertEqual(before.shares.iloc[0],ex.shares.iloc[0])
        eq=r["equity"].set_index("date")
        self.assertGreater(eq.loc[day,"dividend_receivable"],0)
        self.assertEqual(eq.loc[str(dates[73].date()),"dividend_receivable"],0)
        self.assertAlmostEqual(r["actions"].query("type == 'EX_DIVIDEND_OR_BONUS'").dividend_tax.sum(),before.shares.iloc[0]*.2)

    def test_missing_held_action_stops_final_run(self):
        f,s=fixture();f["cumadj"].iloc[72:,0]=1.1
        e=self.engine(f,s)
        with self.assertRaises(MissingActions):
            e.run(Reversal5DR(self.spec(every=100)),e.p.dates[70],e.p.dates[75])

    def test_inconsistent_dividend_and_preclose_stop_final_run(self):
        f,s=fixture();dates=f["close"].index;f["cumadj"].iloc[72:,0]=10/9
        event={"dividRegistDate":str(dates[71].date()),"dividOperateDate":str(dates[72].date()),"dividCashPsBeforeTax":"1"}
        e=self.engine(f,s,{("000001.SZ",2024):[event]})
        with self.assertRaises(MissingActions):e.run(Reversal5DR(self.spec(every=100)),dates[70],dates[75])

    def test_differential_distribution_keeps_actual_and_reference_ratios_separate(self):
        f,s=fixture();dates=f["close"].index
        for key in ("open","close"):f[key].iloc[72:,0]=6.57
        f["high"].iloc[72:,0]=7.;f["low"].iloc[72:,0]=6.
        f["cumadj"].iloc[72:,0]=10/6.57;s["preclose"].iloc[72:,0]=6.57
        date=str(dates[72].date())
        event={"dividRegistDate":str(dates[71].date()),"dividOperateDate":date,"dividCashPsBeforeTax":"1","dividReserveToStockPs":".5"}
        e=self.engine(f,s,{("000001.SZ",2024):[event]})
        e.p.reference_overrides[("000001.SZ",date)]={"reference_cash_per_share":.8,"reference_share_ratio":.4,"actual_cash_per_share":1.,"actual_share_ratio":.5,"source":"synthetic-test"}
        r=e.run(Reversal5DR(self.spec(every=100)),dates[70],dates[75])
        before=r["positions"][r["positions"].date==str(dates[71].date())].shares.iloc[0]
        after=r["positions"][r["positions"].date==date].shares.iloc[0]
        self.assertEqual(after,before*1.5)
        self.assertFalse(r["metrics"]["event_reference_discrepancies"])

    def test_future_prices_and_st_do_not_change_past(self):
        f,s=fixture();e=self.engine(f,s);r=e.run(Reversal5DR(self.spec()),e.p.dates[70],e.p.dates[80])
        for k in f:
            if k!="cumadj":f[k].iloc[81:]=1234
        for k in s:s[k].iloc[81:]=np.nan
        e2=self.engine(f,s);r2=e2.run(Reversal5DR(self.spec()),e2.p.dates[70],e2.p.dates[85])
        pd.testing.assert_frame_equal(r["equity"],r2["equity"].iloc[:len(r["equity"])].reset_index(drop=True))
        orders2=r2["orders"][r2["orders"].execution_date<=str(e.p.dates[80].date())]
        pd.testing.assert_frame_equal(r["orders"],orders2.reset_index(drop=True),check_dtype=False)

    def test_zero_amount_never_fills(self):
        f,s=fixture();f["amt"].iloc[70,0]=0
        e=self.engine(f,s);r=e.run(Reversal5DR(self.spec()),e.p.dates[70],e.p.dates[72])
        self.assertEqual(r["orders"].iloc[0].reason,"ZERO_OR_MISSING_FULL_DAY_TRADING")

    def test_capacity_uses_previous_days_not_execution_day_amount(self):
        f,s=fixture();e=self.engine(f,s);r=e.run(Reversal5DR(self.spec()),e.p.dates[70],e.p.dates[72])
        f["amt"].iloc[70,0]=1
        e2=self.engine(f,s);r2=e2.run(Reversal5DR(self.spec()),e2.p.dates[70],e2.p.dates[72])
        self.assertEqual(r["orders"].iloc[0].planned_qty,r2["orders"].iloc[0].planned_qty)

    def test_missing_prices_do_not_create_sale_or_cash(self):
        f,s=fixture()
        for k in ("close","open","high","low"):f[k].iloc[72:,0]=np.nan
        e=self.engine(f,s,config=replace(PrecisionConfig(),impairment_after=3))
        r=e.run(Reversal5DR(self.spec(every=100)),e.p.dates[70],e.p.dates[80])
        self.assertGreater(r["metrics"]["ending_impaired_positions"],0)
        self.assertEqual(r["equity"].cash.iloc[-1],r["equity"].cash.iloc[1])
        self.assertTrue((r["positions"].shares>0).all())

    def test_arbitrary_python_strategy_has_only_asof_history_copies(self):
        e=self.engine();seen=[]
        class Custom:
            def __init__(self):self.calls=0
            def on_close(self,ctx):
                self.calls+=1
                frame=ctx.history(lookback=3)
                seen.append((ctx.date,frame.index[-1],ctx.states(lookback=1).index[-1]))
                frame[:]=-123
                return {ctx.symbols[0]:.5} if self.calls==1 else None
        r=e.run(Custom(),e.p.dates[70],e.p.dates[75])
        self.assertTrue(all(a==b==c for a,b,c in seen))
        self.assertEqual(e.p.frames["close"].iloc[69,0],10.)
        self.assertGreater(r["metrics"]["filled_orders"],0)

    def test_bonus_shares_are_locked_until_their_listing_date(self):
        f,s=fixture();dates=f["close"].index
        for key in ("open","close"):f[key].iloc[72:,0]=5.
        f["high"].iloc[72:,0]=6.;f["low"].iloc[72:,0]=4.
        f["cumadj"].iloc[72:,0]=2.;s["preclose"].iloc[72:,0]=5.
        event={"dividRegistDate":str(dates[71].date()),"dividOperateDate":str(dates[72].date()),
               "dividReserveToStockPs":"1","dividStockMarketDate":str(dates[74].date())}
        class Exit:
            def on_close(self,ctx):
                if ctx.date==dates[69]:return {ctx.symbols[0]:.95}
                if ctx.date>=dates[71]:return {}
        e=self.engine(f,s,{("000001.SZ",2024):[event]})
        r=e.run(Exit(),dates[70],dates[76]);pos=r["positions"]
        ex=pos[pos.date==str(dates[72].date())].iloc[0]
        self.assertEqual(ex.shares,100000)
        self.assertEqual(ex.locked_shares,50000)
        sold=r["orders"].query("side == 'SELL' and filled_qty > 0")
        early=sold[sold.execution_date<str(dates[74].date())]
        self.assertLessEqual(early.filled_qty.sum(),50000)


if __name__=="__main__":unittest.main()
