import tempfile
import unittest
from pathlib import Path
from web_server import Application
from test_backtest import market


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        for key,value in market()._frames.items():
            value.rename_axis('date').reset_index().to_feather(self.root/f'{key}.feather')
        self.app=Application(self.root,self.root/'runs')
        self.payload=dict(symbols=['A'],start='2024-01-02',end='2024-01-05',strategy_id='equal_weight',limit_mode='strict')

    def tearDown(self):
        self.app.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def test_dataset_connection(self): self.assertTrue(self.app.bootstrap()['data_connected'])
    def test_unknown_symbol_rejected(self):
        with self.assertRaises(ValueError): self.app.validate({**self.payload,'symbols':['NOPE']})
    def test_nonfinite_cash_rejected(self):
        with self.assertRaises(ValueError): self.app.validate({**self.payload,'cash':float('nan')})
    def test_strategy_requires_two_subaccounts(self):
        with self.assertRaises(ValueError): self.app.validate({**self.payload,'strategy_id':'research'})
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError): self.app.run_directory('../other')
    def test_real_job_saves_readable_result_and_fails_closed(self):
        job=self.app.submit(self.payload)
        self.app.pool.shutdown(wait=True)
        state=self.app.jobs[job['job_id']]
        self.assertEqual(state['status'],'completed')
        result=self.app.read_run(state['run_id'])
        self.assertEqual(result['metrics']['filled_orders'],0)
        self.assertGreater(result['metrics']['rejected_orders'],0)
        self.assertEqual(len(result['equity']),4)
