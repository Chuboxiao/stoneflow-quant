import io
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from backtest.precision import Panel, Reversal5DR, ReversalSpec
from factorlab.core import (FactorSpec, FactorContext, REGISTRY, compute_scores, evaluate,
                            forward_labels, quantile_groups, ic_statistics, load_factor_csv)
from factorlab.portfolio import FactorPortfolio
from factorlab.runner import strategy_score
from factorlab.presentation import render_report
from web_server import Application


def fixture():
    dates=pd.bdate_range('2024-01-01',periods=100)
    columns=[f'{i:06d}.SZ' for i in range(1,41)]
    rng=np.random.default_rng(9)
    prices=10*np.cumprod(1+rng.normal(0,.01,(100,40)),axis=0)
    close=pd.DataFrame(prices,index=dates,columns=columns)
    frames={k:close.copy() for k in ('open','high','low','close','amt','num_trades','cumadj')}
    frames['amt'][:]=1e8;frames['num_trades'][:]=10000;frames['cumadj'][:]=1
    frames['high']*=1.02;frames['low']*=.98
    states={k:close.copy() for k in ('isST','tradestatus','preclose')}
    states['isST'][:]=0;states['tradestatus'][:]=1
    return frames,states


class FactorTests(unittest.TestCase):
    def setUp(self):
        self.frames,self.states=fixture()
        self.panel=Panel(self.frames,self.states)

    def test_builder_history_is_causal_and_mutation_isolated(self):
        ctx=FactorContext(self.panel,70)
        h=ctx.history(lookback=6)
        self.assertEqual(h.index[-1],self.panel.dates[70])
        h.iloc[-1,0]=999
        self.assertNotEqual(self.panel.adjusted[70,0],999)
        with self.assertRaises(ValueError): ctx.history('amt',adjusted=True)

    def test_reversal5_direction_and_cumadj(self):
        self.frames['cumadj'].iloc[70:,0]=2
        p=Panel(self.frames,self.states)
        scores=compute_scores(p,REGISTRY['reversal5'])
        self.assertAlmostEqual(scores[70,0],-(p.adjusted[70,0]/p.adjusted[65,0]-1))

    def test_future_price_and_status_do_not_change_past_scores_or_membership(self):
        score=compute_scores(self.panel,REGISTRY['reversal5'])
        before=evaluate(self.panel,score,self.panel.dates[70],self.panel.dates[80],horizons=(1,))
        self.frames['close'].iloc[76:]*=2;self.states['isST'].iloc[76:]=1
        changed=Panel(self.frames,self.states)
        after_score=compute_scores(changed,REGISTRY['reversal5'])
        np.testing.assert_allclose(score[:76],after_score[:76],equal_nan=True)
        after=evaluate(changed,after_score,changed.dates[70],changed.dates[80],horizons=(1,))
        self.assertEqual(before['coverage'][:6],after['coverage'][:6])

    def test_next_open_forward_labels_and_strict_cutoff(self):
        self.frames['open'].iloc[71]=10;self.frames['open'].iloc[72]=11
        p=Panel(self.frames,self.states)
        values,entry,exit_=forward_labels(p,70,1,p.dates[72])
        np.testing.assert_allclose(values,.1)
        self.assertEqual(entry,str(p.dates[71].date()))
        self.assertEqual(exit_,str(p.dates[72].date()))
        values,entry,exit_=forward_labels(p,70,1,p.dates[71])
        self.assertTrue(np.isnan(values).all());self.assertIsNone(entry)

    def test_positive_and_negative_rank_ic(self):
        self.frames['open'].iloc[71]=10
        self.frames['open'].iloc[72]=10*(1+np.arange(40)*.001)
        p=Panel(self.frames,self.states)
        scores=np.tile(np.arange(40),(100,1)).astype(float)
        result=evaluate(p,scores,p.dates[70],p.dates[74],horizons=(1,))
        self.assertAlmostEqual(result['daily'][0]['rank_ic'],1.)
        negative=evaluate(p,-scores,p.dates[70],p.dates[74],horizons=(1,))
        self.assertAlmostEqual(negative['daily'][0]['rank_ic'],-1.)

    def test_unknown_and_st_not_ranked_but_future_st_not_used(self):
        self.states['isST'].iloc[70,0]=np.nan;self.states['isST'].iloc[70,1]=1
        self.states['isST'].iloc[71:,2]=1
        p=Panel(self.frames,self.states)
        result=evaluate(p,np.ones((100,40)),p.dates[70],p.dates[74],horizons=(1,))
        self.assertEqual(result['coverage'][0]['eligible'],38)

    def test_missing_exit_does_not_rebuild_quantile_members(self):
        self.frames['open'].iloc[72,39]=np.nan
        p=Panel(self.frames,self.states)
        result=evaluate(p,np.tile(np.arange(40),(100,1)).astype(float),p.dates[70],p.dates[74],horizons=(1,))
        row=result['daily'][0]
        self.assertEqual(row['group_selected'][-1],8)
        self.assertEqual(row['group_observed'][-1],7)
        self.assertEqual(row['missing_labels'],1)

    def test_ties_not_split_and_low_cardinality_not_forced_into_five_groups(self):
        self.assertTrue((quantile_groups(np.ones(40))==0).all())
        values=np.repeat(np.arange(5),8)
        groups=quantile_groups(values.astype(float))
        for v in range(5): self.assertEqual(len(set(groups[values==v])),1)

    def test_constant_factor_undefined_ic_not_zero(self):
        result=evaluate(self.panel,np.ones((100,40)),self.panel.dates[70],self.panel.dates[74],horizons=(1,))
        self.assertTrue(np.isnan(result['daily'][0]['rank_ic']))
        self.assertIsNone(result['summary'][0]['rank_ic']['mean'])

    def test_endpoint_censoring_and_no_october_style_padding(self):
        scores=compute_scores(self.panel,REGISTRY['reversal5'])
        end=self.panel.dates[80]
        result=evaluate(self.panel,scores,self.panel.dates[70],end,horizons=(1,5))
        self.assertEqual(result['summary'][0]['endpoint_censored_dates'],2)
        self.assertEqual(result['summary'][1]['endpoint_censored_dates'],6)
        for row in result['daily']:
            if row['exit_date']: self.assertLessEqual(pd.Timestamp(row['exit_date']),end)

    def test_csv_duplicates_unknown_and_nonfinite_rejected(self):
        date=str(self.panel.dates[70].date());symbol=self.panel.symbols[0]
        good=f'date,symbol,value\n{date},{symbol},2\n'
        matrix=load_factor_csv(io.StringIO(good),self.panel,direction=-1)
        self.assertEqual(matrix[70,0],-2)
        self.assertTrue(np.isnan(matrix[69]).all())
        for text in [good+f'{date},{symbol},3\n',good.replace(symbol,'BOGUS'),good.replace(',2\n',',inf\n')]:
            with self.assertRaises(ValueError):load_factor_csv(io.StringIO(text),self.panel)

    def test_custom_builder_contract_and_short_history(self):
        bad=FactorSpec('bad','bad','bad',1,lambda ctx:np.ones(40))
        with self.assertRaises(ValueError):compute_scores(self.panel,bad)
        scores=compute_scores(self.panel,REGISTRY['momentum20'])
        self.assertTrue(np.isnan(scores[:20]).all())

    def test_breakout_high_window_excludes_today(self):
        baseline=compute_scores(self.panel,REGISTRY['breakout20'])
        self.frames['high'].iloc[70]=1e9
        after=compute_scores(Panel(self.frames,self.states),REGISTRY['breakout20'])
        np.testing.assert_allclose(baseline[70],after[70])

    def test_factor_adapter_reproduces_legacy_5dr_targets(self):
        for pool in ['base','liquid']:
            old=Reversal5DR(ReversalSpec('x','x',min_amount=2e7 if pool=='liquid' else 0,min_price=3 if pool=='liquid' else 0))
            new=FactorPortfolio(REGISTRY['reversal5'],pool)
            self.assertEqual(old.weights(self.panel,70,{},0)[0],new.weights(self.panel,70,{},0)[0])

    def test_negative_annual_return_cannot_win_by_larger_drawdown(self):
        score=strategy_score({'annualized_return':-.1,'max_drawdown':-.5})
        self.assertIsNone(score['value']);self.assertFalse(score['eligible_for_ranking'])

    def test_icir_is_unannualized_hac_has_overlap_lag(self):
        values=np.linspace(-.2,.3,40)
        stats=ic_statistics(values,20)
        self.assertAlmostEqual(stats['icir'],values.mean()/values.std(ddof=1))
        self.assertGreaterEqual(stats['hac_lags'],19)
        self.assertIsNone(ic_statistics([1.,1.,1.],1)['icir'])

    def test_imported_text_cannot_close_embedded_json_script(self):
        malicious={'description':'</script><script>alert(1)</script>'}
        rendered=render_report(malicious)
        self.assertNotIn('</script><script>alert(1)',rendered)
        self.assertIn('\\u003c/script',rendered)

    def test_invalid_horizons_and_misalignment_fail(self):
        for horizons in [(0,), (True,), (1,1)]:
            with self.assertRaises(ValueError):evaluate(self.panel,np.ones((100,40)),self.panel.dates[70],self.panel.dates[75],horizons=horizons)
        with self.assertRaises(ValueError):evaluate(self.panel,np.ones((99,40)),self.panel.dates[70],self.panel.dates[75])

    def test_factor_identifier_and_lookback_contract(self):
        for key,lookback in [('../outside',6),('ok',True),('ok',0),('ok',2.5)]:
            with self.assertRaises(ValueError):FactorSpec(key,'test','test',lookback,lambda ctx:None)


class FactorWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        frames,states=fixture()
        for name,frame in frames.items():
            frame.rename_axis('date').reset_index().to_feather(self.root/f'{name}.feather')
        self.reference=self.root/'reference';self.reference.mkdir()
        for symbol in frames['close'].columns:
            pd.DataFrame({'date':frames['close'].index,'close':frames['close'][symbol],
                          'isST':0,'tradestatus':1,'preclose':frames['close'][symbol]}).to_csv(self.reference/f'{symbol}.csv.gz',index=False)
        self.app=Application(self.root,self.root/'runs')
        self.app.reference_dir=self.reference
        self.app.factor_runs_dir=self.root/'factor_runs'
        self.app.factor_directory=self.root/'empty'
        self.payload={'factors':['reversal5'],'start':str(frames['close'].index[70].date()),
                      'end':str(frames['close'].index[90].date()),'pool':'base','horizons':[1,5]}

    def tearDown(self):
        self.app.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def test_unsafe_plugin_or_unknown_web_arguments_rejected(self):
        with self.assertRaises(ValueError):self.app.validate_factor({**self.payload,'plugin':'/tmp/arbitrary.py'})
        with self.assertRaises(ValueError):self.app.validate_factor({**self.payload,'factors':['unknown']})

    def test_missing_reference_never_silently_means_non_st(self):
        self.app.reference_dir=self.root/'missing'
        with self.assertRaises(ValueError):self.app.validate_factor(self.payload)

    def test_future_range_and_duplicate_horizons_rejected(self):
        with self.assertRaises(ValueError):self.app.validate_factor({**self.payload,'end':'2026-10-16'})
        with self.assertRaises(ValueError):self.app.validate_factor({**self.payload,'horizons':[5,5]})

    def test_real_factor_job_saves_report_without_overwriting_original_runs(self):
        self.assertIsNone(self.app.factor_summary())
        job=self.app.submit_factor(self.payload)
        self.app.pool.shutdown(wait=True)
        state=self.app.jobs[job['job_id']]
        self.assertEqual(state['status'],'completed',state)
        result=self.app.factor_summary()
        self.assertEqual(len(result['analyses']),1)
        self.assertTrue((self.app.factor_directory/'daily.csv').exists())
        self.assertTrue((self.app.factor_directory/'report.html').exists())
        self.assertEqual(list((self.root/'runs').iterdir()),[])
