import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.precision import Panel
from factorlab.core import FactorContext, REGISTRY
from factorlab.evolution import EvolutionLab, configuration, score, seeds, validate_spec


def panel_fixture():
    dates = pd.bdate_range('2023-09-01', '2025-01-10')
    rng = np.random.default_rng(72)
    prices = pd.DataFrame(10*np.cumprod(1+rng.normal(0,.012,(len(dates),40)),axis=0), index=dates,
                          columns=[f'{i:06d}.SZ' for i in range(40)])
    frames = {k: prices.copy() for k in ('open','high','low','close','amt','num_trades','cumadj')}
    frames['high'] *= 1.02; frames['low'] *= .98
    frames['amt'][:] = 1e8; frames['num_trades'][:] = 10000; frames['cumadj'][:] = 1
    states = {k: prices.copy() for k in ('isST','tradestatus','preclose')}
    states['isST'][:] = 0; states['tradestatus'][:] = 1
    return Panel(frames, states)


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.panel = panel_fixture()
        self.lab = EvolutionLab(self.root/'studies', lambda:self.panel, self.root/'cache')
        self.params = dict(search_start='2024-01-02', search_end='2024-04-05',
                           validation_start='2024-04-08', validation_end='2024-07-12', round_budget=2)

    def tearDown(self): self.tmp.cleanup()

    def test_config_disallows_overlap_review_selection_and_unknown_fields(self):
        for changes in [dict(validation_start='2024-04-01'),dict(validation_end='2026-01-01'),
                        dict(horizon=True),dict(horizon=5.0),dict(round_budget=0),dict(code='execute')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): configuration({**self.params,**changes})

    def test_canonical_formula_duplicate_and_untrusted_code(self):
        a=validate_spec(dict(key='a',kind='reversal',window=5,hypothesis='短期反转'))
        b=validate_spec(dict(key='b',kind='reversal',window=5,hypothesis='换了名称'))
        self.assertEqual(a['fingerprint'],b['fingerprint'])
        with self.assertRaises(ValueError): validate_spec(dict(key='a',kind='reversal',window=5,hypothesis='短期反转',formula='eval(1)'))
        with self.assertRaises(ValueError): self.lab.path('../../outside')

    def test_all_seed_formulas_match_existing_factor_builders(self):
        for spec in seeds():
            actual=score(self.panel.frames,spec)
            for i in (80,140,200):
                np.testing.assert_allclose(actual[i],REGISTRY[spec['key']].builder(FactorContext(self.panel,i)),equal_nan=True,atol=1e-10)

    def test_every_operator_is_prefix_causal_and_rank_mix_respects_pool(self):
        definitions=seeds()+[validate_spec(dict(key=kind,kind=kind,window=20,hypothesis='测试截断因果性')) for kind in
                             ('smooth_reversal','risk_reversal','amount_reversal','range_position','rank_mix')]
        mask=np.ones(self.panel.adjusted.shape,dtype=bool);mask[:,0]=False
        for spec in definitions:
            full=score(self.panel.frames,spec,mask)
            prefix=score({k:v.iloc[:160] for k,v in self.panel.frames.items()},spec,mask[:160])
            np.testing.assert_allclose(full[:160],prefix,equal_nan=True)
            if spec['kind']=='rank_mix': self.assertTrue(np.isnan(full[:,0]).all())

    def test_real_seed_evaluation_persists_and_enforces_cutoffs(self):
        s=self.lab.create(self.params);result=self.lab.run_round(s['id'])
        self.assertEqual(len(result['candidates']),5)
        self.assertEqual(result['status'],'ready')
        restarted=EvolutionLab(self.root/'studies',lambda:self.panel,self.root/'cache')
        self.assertEqual(restarted.read(s['id'])['candidates'],result['candidates'])
        for path in (self.root/'studies'/s['id']/'diagnostics').glob('*validation.json'):
            import json
            full=json.loads(path.read_text())
            self.assertTrue(all(not r['exit_date'] or r['exit_date'] <= self.params['validation_end'] for r in full['daily']))
        with self.assertRaises(ValueError): self.lab.run_round(s['id'],[dict(key='renamed',kind='reversal',window=5,hypothesis='重复五日反转')])
        frozen=self.lab.freeze(s['id'])
        self.assertTrue(frozen['frozen']['no_reselection'])
        with self.assertRaises(ValueError): self.lab.run_round(s['id'])

    def test_interruption_keeps_request_and_resume_does_not_duplicate_trials(self):
        s=self.lab.create(self.params);original=self.lab.assess;calls=[]
        def fail_once(study,values,key,phases=('search','validation')):
            calls.append(key)
            if key=='momentum20': raise RuntimeError('模拟掉电')
            return original(study,values,key,phases)
        with patch.object(self.lab,'assess',side_effect=fail_once):
            with self.assertRaises(RuntimeError): self.lab.run_round(s['id'])
        interrupted=self.lab.read(s['id'])
        self.assertEqual(interrupted['status'],'interrupted')
        self.assertEqual(list(interrupted['candidates']),['reversal5'])
        with patch.object(self.lab,'assess',wraps=original) as monitor:
            result=self.lab.run_round(s['id'])
        self.assertEqual(len(result['candidates']),5)
        self.assertFalse(any(call.args[2]=='reversal5' for call in monitor.call_args_list))
        self.assertIsNone(result['pending'])

    def test_changed_config_cannot_reuse_experiment(self):
        s=self.lab.create(self.params);s['config']['pool']='base';self.lab.save(s)
        with self.assertRaisesRegex(ValueError,'配置被修改'): self.lab.run_round(s['id'])

    def test_study_lock_prevents_concurrent_mutation(self):
        s=self.lab.create(self.params)
        with self.lab.lock(s['id']):
            with self.assertRaises(RuntimeError): self.lab.freeze(s['id'])

    def test_review_requires_freeze_and_no_implicit_fallback_factor(self):
        s=self.lab.create(self.params)
        with self.assertRaises(ValueError): self.lab.review(s['id'])
        with self.assertRaises(ValueError): self.lab.freeze(s['id'])
        s['baseline']={'pool':[],'metrics':None};self.lab.save(s)
        self.assertEqual(self.lab.freeze(s['id'])['frozen']['members'],[])

    def test_fixed_policy_requires_real_combination_gain(self):
        s=self.lab.create(self.params)
        m={'rank_ic':.05,'positive_months':.75,'months':4,'coverage':1.,'spread':.01,'days':60}
        def positive(*args,**kwargs): return {'search':copy.deepcopy(m),'validation':copy.deepcopy(m)}
        with patch.object(self.lab,'assess',side_effect=positive): result=self.lab.run_round(s['id'])
        self.assertEqual(result['pool'],['reversal5'])
        self.assertTrue(any('增量不足' in reason for reason in result['candidates']['lowvol20']['reasons']))


if __name__=='__main__': unittest.main()
