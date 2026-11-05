"""Replay a saved sequence without overwriting it; requires local market data."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from factorlab.evolution import EvolutionLab


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args(); original=json.loads(args.source.read_text())
    keys={'name','pool','horizon','search_start','search_end','validation_start','validation_end','round_budget','harness'}
    config={k:v for k,v in original['config'].items() if k in keys}
    config['name']='重放 · '+config['name'][:90]
    lab=EvolutionLab(); study=lab.create(config); study_id=study['id']
    print('新实验ID：'+study_id,flush=True)
    lab.run_round(study_id,progress=print)
    fields={'key','kind','window','smooth','vol_window','alpha','parent','hypothesis'}
    for batch in original['rounds']:
        if batch['round']==0: continue
        specs=[{k:v for k,v in s.items() if k in fields} for s in batch['specs']]
        lab.run_round(study_id,specs,batch['feedback'],batch['source'],progress=print)
    if original['frozen']: lab.freeze(study_id)
    if original['review']: lab.review(study_id,progress=print)
    print('保存至 results/evolution_runs/'+study_id,flush=True)


if __name__=='__main__': main()
