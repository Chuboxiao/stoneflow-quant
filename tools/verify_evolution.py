"""Independently recompute saved diagnostics with Python's standard library."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parent.parent


def verify(study_id):
    if len(study_id)!=12 or any(c not in '0123456789abcdef' for c in study_id): raise ValueError('无效实验ID')
    directory=ROOT/'results/evolution_runs'/study_id
    s=json.loads((directory/'study.json').read_text());checks=0;files=0
    def close(a,b):
        nonlocal checks
        assert a is not None and b is not None and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12),(a,b)
        checks+=1
    for path in sorted((directory/'diagnostics').glob('*.json')):
        data=json.loads(path.read_text());files+=1
        valid=[r['rank_ic'] for r in data['daily'] if r['rank_ic'] is not None]
        close(mean(valid),data['summary'][0]['rank_ic']['mean'])
        assert len(valid)==data['summary'][0]['rank_ic']['observations'];checks+=1
        for row in data['daily']:
            assert not row['exit_date'] or row['exit_date']<=data['end'];checks+=1
        for period in data['periods']:
            values=[r['rank_ic'] for r in data['daily'] if r['date'].startswith(period['period']) and r['rank_ic'] is not None]
            if values: close(mean(values),period['mean'])
        suffix=path.stem.rsplit('_',1)[-1]
        key=path.stem[:-(len(suffix)+1)]
        if key in s['candidates'] and suffix in ('search','validation'):
            close(mean(valid),s['candidates'][key]['metrics'][suffix]['rank_ic'])
    for row in s['candidates'].values():
        assert row['prefix_check'] and row['completed'];checks+=1
        if row['spec']['parent']: assert row['spec']['parent'] in s['candidates'];checks+=1
    fingerprints=[r['spec']['fingerprint'] for r in s['candidates'].values()]
    assert len(fingerprints)==len(set(fingerprints));checks+=1
    assert s['rounds_completed']<=s['config']['round_budget'];checks+=1
    for batch in s['rounds']:
        if batch['round']>0: assert len(batch['specs'])<=3;checks+=1
    if s['frozen']:
        assert s['frozen']['members']==s['pool'] and s['frozen']['no_reselection'];checks+=1
        assert all(batch['finished_at']<=s['frozen']['at'] for batch in s['rounds']);checks+=1
    result={'study_id':study_id,'checks':checks,'diagnostic_files':files,'status':'PASS',
            'study_sha256':hashlib.sha256((directory/'study.json').read_bytes()).hexdigest(),
            'scope':'独立核对每日IC/期间均值/区间截止/父子与冻结记录；不构成净交易验证。'}
    (directory/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--id',required=True)
    print(json.dumps(verify(parser.parse_args().id),ensure_ascii=False,indent=2))
