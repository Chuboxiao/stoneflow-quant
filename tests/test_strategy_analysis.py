import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
import pandas as pd
from backtest.precision import Panel
from strategy_analysis import frozen_groups,bootstrap_mean,RestrictedBreakout,block_period,attribution
from test_breakout_pool import context


def panel():
    dates=pd.bdate_range('2023-09-01','2026-10-01');symbols=[f'{i+1:06d}.SZ' for i in range(6)]
    t=np.arange(len(dates))[:,None];j=np.arange(6)[None,:]
    price=20*np.exp(.0005*t+(.02+j*.01)*np.sin(t/(3+j)))
    close=pd.DataFrame(price,index=dates,columns=symbols)
    frames={key:close.copy()*value for key,value in {'open':1,'high':1.02,'low':.98,'close':1,'amt':1e6,'num_trades':1000}.items()}
    frames['cumadj']=close*0+1
    states={key:close*0+value for key,value in {'isST':0,'tradestatus':1,'preclose':20}.items()}
    return Panel(frames,states)


class AnalysisTests(unittest.TestCase):
    def test_membership_never_reads_future_prices_or_states(self):
        p=panel();_,thresholds,members=frozen_groups(p)
        cutoff=p.dates>='2025-01-01'
        p.adjusted[cutoff]=999999
        p.frames['amt'].loc[cutoff]=1
        p.states['isST'][cutoff]=1
        _,other_thresholds,other_members=frozen_groups(p)
        self.assertEqual(thresholds,other_thresholds)
        self.assertEqual(members,other_members)

    def test_frozen_groups_partition_and_freeze_date_st(self):
        p=panel();end=p.locations[pd.Timestamp('2024-12-31')]
        p.states['isST'][end,0]=1
        _,_,m=frozen_groups(p)
        self.assertNotIn('000001.SZ',m['frozen_all'])
        for a,b in [('trend_high','trend_low'),('vol_low','vol_high')]:
            self.assertFalse(set(m[a])&set(m[b]))
            self.assertEqual(set(m[a])|set(m[b]),set(m['frozen_all']))
        self.assertTrue(set(m['trend_calm'])<=set(m['trend_high'])&set(m['vol_low']))

    def test_bootstrap_uses_date_blocks_and_is_reproducible(self):
        values=np.sin(np.arange(90))
        self.assertEqual(bootstrap_mean(values),bootstrap_mean(values))
        self.assertAlmostEqual(bootstrap_mean(np.full(80,.01))['low'],.01)
        self.assertEqual(bootstrap_mean([np.nan])['days'],0)

    def test_restricted_callback_cannot_buy_other_symbols(self):
        ctx,_,_=context()
        strategy=RestrictedBreakout('one','one',['000002.SZ'])
        self.assertEqual(list(strategy.on_close(ctx)),['000002.SZ'])

    def test_period_drawdown_includes_initial_capital(self):
        eq=pd.DataFrame({'date':['2025-01-02','2025-01-03'],'equity':[80.,90.]})
        r=block_period(eq,'2025-01-02','2025-01-03',100)
        self.assertAlmostEqual(r['total_return'],-.1)
        self.assertAlmostEqual(r['max_drawdown'],-.2)

    def test_cash_and_late_dividend_attribution_reconciles(self):
        p=panel();s='000001.SZ'
        p.events[(s,2025)]=[{'dividRegistDate':'2025-01-02','dividOperateDate':'2025-01-06'}]
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);dest=d/'output'
            pd.DataFrame({'date':['2025-01-02','2025-01-03','2025-01-06'],
                'equity':[9999.,10098.,10118.],'daily_return':[-.0001,10098/9999-1,10118/10098-1]}).to_csv(d/'equity.csv',index=False)
            pd.DataFrame([{'symbol':s,'execution_date':'2025-01-02','signal_date':'2025-01-01','side':'BUY','notional':1000.,'commission':1.,'stamp_tax':0.,'transfer_fee':0.,'raw_execution_price':10.,'raw_open':10.,'filled_qty':100},
                          {'symbol':s,'execution_date':'2025-01-03','signal_date':'2025-01-02','side':'SELL','notional':1100.,'commission':1.,'stamp_tax':0.,'transfer_fee':0.,'raw_execution_price':11.,'raw_open':11.,'filled_qty':100}]).to_csv(d/'orders.csv',index=False)
            pd.DataFrame([{'date':'2025-01-02','symbol':s,'shares':100,'market_value':1000.}]).to_csv(d/'positions.csv',index=False)
            pd.DataFrame([{'date':'2025-01-06','symbol':s,'type':'EX_DIVIDEND_OR_BONUS','cash_delta':20.,'receivable_delta':0.,'shares_delta':0.}]).to_csv(d/'actions.csv',index=False)
            (d/'metrics.json').write_text(json.dumps({'initial_cash':10000}))
            r=attribution(d,p,dest,benchmark=pd.Series(10.,index=p.dates))
            self.assertLess(r['account_reconciliation_error'],1e-10)
            self.assertAlmostEqual(r['spell_reconciliation_error'],0)
            spells=pd.read_csv(dest/'holding_spells.csv')
            self.assertAlmostEqual(spells.net_pnl.sum(),118.)
            self.assertEqual(r['closed_spells'],1)


if __name__=='__main__':unittest.main()
