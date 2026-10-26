"""Verify saved factor results, source hashes and original-account parity."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def validate(directory):
    directory=Path(directory)
    data=json.loads((directory/'summary.json').read_text())
    manifest=json.loads((directory/'manifest.json').read_text())
    assertions=0
    def require(condition,message):
        nonlocal assertions
        assertions+=1
        if not condition: raise AssertionError(message)
    for path,sha in manifest['code_sha256'].items():
        require(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,'Source hash: '+path)
    for a in data['analyses']:
        for row in a['daily']:
            if row['entry_date']:
                require(row['date']<row['entry_date']<row['exit_date']<=data['end'],'Noncausal or out-of-range label')
            require(sum(row['group_selected']) in (0,row['factor_valid']),'Group membership size')
            require(all(x<=y for x,y in zip(row['group_observed'],row['group_selected'])),'Future observation rebuilt group')
            for key in ['ic','rank_ic','monotonicity']:
                require(row[key] is None or -1.0000000001<=row[key]<=1.0000000001,'Correlation out of bounds')
        for s in a['summary']:
            rows=[r for r in a['daily'] if r['horizon']==s['horizon']]
            ic=np.array([r['rank_ic'] for r in rows if r['rank_ic'] is not None])
            require(len(ic)==s['rank_ic']['observations'],'IC count')
            if len(ic):
                require(np.isclose(ic.mean(),s['rank_ic']['mean']),'IC mean')
            if len(ic)>1 and ic.std(ddof=1)>1e-15:
                require(np.isclose(ic.mean()/ic.std(ddof=1),s['rank_ic']['icir']),'Unannualized ICIR')
            require(sum(r['paired'] for r in rows)==s['observed_labels'],'Label count')
            require(sum(r['endpoint_censored'] for r in rows)==s['endpoint_censored_dates'],'Endpoint censoring')
    parity=[]
    for a in data['accounts']:
        m=a['metrics'];score=a['score']
        require(np.isclose((1+m['total_return'])**(252/m['trading_days'])-1,m['annualized_return']),'Annualization')
        if m['annualized_return']<=0:
            require(score['value'] is None and not score['eligible_for_ranking'],'Negative-return score guard')
        if a['period']=='new' and a['key'].startswith('reversal5_'):
            key='liquid' if '_liquid_' in a['key'] else 'base'
            cost='double_cost' if a['key'].endswith('double_cost') else 'normal'
            old=ROOT/'results/5dr_review'/('evaluation/'+key if cost=='normal' else 'stress/double_cost/'+key)
            new=directory/'accounts'/f'reversal5_{key}'/cost
            original=json.loads((old/'metrics.json').read_text())
            for metric in ['total_return','annualized_return','max_drawdown','total_fees','filled_orders','rejected_orders']:
                require(m[metric]==original[metric],'Original 5DR parity: '+metric)
            files={}
            for name in ['equity.csv','orders.csv','positions.csv','actions.csv','valuation.csv']:
                files[name]=hashlib.sha256((old/name).read_bytes()).hexdigest()==hashlib.sha256((new/name).read_bytes()).hexdigest()
                require(files[name],'Ledger parity: '+name)
            parity.append({'account':a['key'],'metrics_exact':True,'byte_identical_ledgers':files})
    output={'passed':True,'checks':assertions,'analyses':len(data['analyses']),'account_parity':parity,
            'source_hashes_current':True,'original_reports_and_backtest_preserved':True,
            'note':'Independent checks of saved aggregates and existing economic ledgers; does not establish strategy validity.'}
    (directory/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in output.items() if k!='account_parity'},ensure_ascii=False))
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',default='results/factors')
    args=parser.parse_args();validate(args.results)
