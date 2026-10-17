"""Predeclared full-pool breakout extension, saved separately from the 5DR study."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
import pandas as pd
from backtest.precision import Panel, PrecisionConfig, PrecisionEngine
from backtest.breakout_pool import PoolBreakout, SPECS
from research_5dr import START, END, TRAIN_START, TRAIN_END, write_json, save_result


def protocol():
    return {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "study": "full-pool 20/10 breakout extension",
        "performance_start": START, "performance_end": END,
        "training_start": TRAIN_START, "training_end": TRAIN_END,
        "retrospective": True,
        "disclosure": "Rules written in October 2026 after earlier 5DR and two-stock results were seen. Time-separated retrospective comparison, not genuinely blind prospective OOS.",
        "candidates": [asdict(s) for s in SPECS],
        "selection": "max 2024 annualized_return/(abs(max_drawdown)+0.05); tie by key; no evaluation-period reselection",
        "universe": "5451 course columns; dynamic historical non-ST eligibility, no claim of full historical A-share coverage",
        "rules": [
            "Entry: adjusted close exceeds maximum adjusted high of prior 20 sessions, excluding today; exit below prior 10 adjusted lows.",
            "At least 60 valid closes in the latest 61 sessions; known non-ST/trading status and positive amount/trade count.",
            "Maximum 20 actual positions, including pending exits; if oversubscribed, rank close/prior_high descending, code ascending.",
            "New entry <=4.75% equity; keep existing raw shares, no daily equal-weight rebalance; no partial-entry top-up.",
            "Total entry budget <=95% equity less all noncash equity, including unsold exits, stale marks and unpaid dividends. Drift of existing holdings can exceed95%.",
            "Persistent exit intentions until actual shares reach zero; failed new entry only retries with a fresh valid daily breakout signal.",
            "Volume confirmation: today's amount >1.5 times previous20-day mean; excludes today from reference mean.",
            "Liquidity: previous20-day mean amount>=20million yuan and raw close>=3yuan; applies to new entries only.",
            "Trend: adjusted close>MA60 and MA20>MA60; both include today's known close, applies to new entries only.",
            "Defensive: entry weight=min(4.75%,0.1%/(ATR14/close)); close below highest adjusted close observed while actually held minus3*currentATR14 also exits.",
            "ATR is simple mean of14 adjusted true ranges through signal close; all stops are close signals executed next open, never assumed stop-price fills."
        ],
        "execution": asdict(PrecisionConfig()),
        "stress": ["double all fees and slippage", "participation cap from1% to0.1% of lagged20-day mean amount"],
        "shared_limitations": "See docs/PRECISION_5DR.md: point-in-time state availability, daily opening proxy, tax/stock-delivery approximations, course-universe survivorship, no guaranteed queue fills.",
    }


def run(args):
    root = Path(args.output); root.mkdir(parents=True, exist_ok=True)
    path = root/"protocol.json"
    if not path.exists(): write_json(path, protocol())
    registered = json.loads(path.read_text())
    if registered["candidates"] != protocol()["candidates"]: raise ValueError("Frozen candidate definitions changed")
    if args.register_only: return
    write_json(root/"run_status.json", {"status":"RUNNING"})
    panel = Panel.load(args.data_dir, args.reference_dir, args.action_dir)
    write_json(root/"data_audit.json", panel.audit)
    overrides = Path("reference/breakout_corporate_reference_overrides.json")
    if overrides.exists():
        for item in json.loads(overrides.read_text()):
            if item["announced_at"] > item["ex_date"]: raise ValueError("Late event reference")
            panel.reference_overrides[(item["symbol"], item["ex_date"])] = item
    cfg = replace(PrecisionConfig(), allow_missing_actions=args.provisional)
    missing = set(); discrepancies = []; training = []; results = {}; comparison = []; stresses = []
    def execute(spec, begin, end, dest, config):
        print(dest, flush=True)
        result = PrecisionEngine(panel, config).run(PoolBreakout(spec), begin, end)
        save_result(result, root/dest)
        missing.update(tuple(x) for x in result["metrics"]["missing_actions"])
        discrepancies.extend({"run":dest,**x} for x in result["metrics"].get("event_reference_discrepancies",[]))
        return result
    for spec in SPECS:
        result = execute(spec, TRAIN_START, TRAIN_END, "training/"+spec.key, cfg)
        m = result["metrics"]
        training.append({"key":spec.key,"strategy":spec.title,"score":m["annualized_return"]/(abs(m["max_drawdown"])+.05),**m})
    selected = sorted(training, key=lambda x:(-x["score"], x["key"]))[0]["key"]
    write_json(root/"selection.json", {"selected_key":selected,"basis":"2024 only","provisional":args.provisional,"training":training})
    for spec in SPECS:
        result = execute(spec, START, END, "evaluation/"+spec.key, cfg)
        results[spec.key] = result
        comparison.append({"key":spec.key,"strategy":spec.title,"selected_on_2024":spec.key==selected,**result["metrics"]})
    for label, config in (("double_cost",replace(cfg,commission=cfg.commission*2,min_commission=cfg.min_commission*2,stamp=cfg.stamp*2,transfer=cfg.transfer*2,slippage_bps=cfg.slippage_bps*2)),
                          ("tight_capacity",replace(cfg,participation=.001))):
        for spec in SPECS:
            if spec.key not in {"base",selected}: continue
            result = execute(spec, START, END, "stress/"+label+"/"+spec.key, config)
            stresses.append({"scenario":label,"key":spec.key,"strategy":spec.title,**result["metrics"]})
    # Added as an attribution diagnostic after the initial provisional study.
    # Never enters training selection and is never named an out-of-sample winner.
    control_spec=replace(SPECS[0],key="half_exposure",title="普通突破 · 固定半仓参照",max_weight=.475)
    control_protocol=root/"control_protocol.json"
    if not control_protocol.exists():
        write_json(control_protocol,{"created_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"spec":asdict(control_spec),
            "purpose":"Descriptive attribution: is defensive improvement more than simply lower exposure?",
            "timing":"Added after provisional candidate results were observed; not part of model selection, not a blind test."})
    control=execute(control_spec,START,END,"diagnostic/half_exposure",cfg)
    write_json(root/"needed_actions.json", [list(x) for x in sorted(missing)])
    write_json(root/"event_discrepancies.json", discrepancies)
    if args.provisional:
        write_json(root/"run_status.json", {"status":"PROVISIONAL","missing_actions":len(missing),"discrepancies":len(discrepancies)})
        print(json.dumps({"selected":selected,"missing_actions":len(missing),"discrepancies":len(discrepancies)}),flush=True)
        return
    periods = []
    for key,result in results.items():
        eq = result["equity"]
        for title,begin,finish in (("2025",START,"2025-12-31"),("2026年前三季度","2026-01-01",END)):
            mask = (eq.date>=begin)&(eq.date<=finish); block=eq[mask]
            idx = np.flatnonzero(mask.to_numpy())[0]; starting=cfg.cash if idx==0 else eq.equity.iloc[idx-1]
            vals=block.equity.to_numpy(); peak=np.maximum.accumulate(np.r_[starting, vals])[1:]
            periods.append({"key":key,"period":title,"total_return":float(vals[-1]/starting-1),"max_drawdown":float((vals/peak-1).min()),"trading_days":len(block)})
    write_json(root/"comparison.json",comparison)
    pd.DataFrame(comparison).drop(columns=["missing_actions","event_reference_discrepancies","rejection_reasons"]).to_csv(root/"comparison.csv",index=False,encoding="utf-8-sig")
    metadata = {"status":"REVIEW_ONLY","study":"20日突破 · 全股票池","selected_key":selected,
                "performance_start":START,"performance_end":END,"trading_days":len(results["base"]["equity"]),
                "pool_size":len(panel.symbols),"comparison":comparison,"stress":stresses,"periods":periods,
                "data_audit":panel.audit,"raw_data_published":False,"protocol":registered,
                "exposure_control":{"strategy":control_spec.title,**control["metrics"]}}
    prior = Path("results/5dr_review/summary.json")
    if prior.exists():
        five = json.loads(prior.read_text()); metadata["benchmark"] = five.get("benchmark",[])
        metadata["five_dr_reference"] = [{k:r[k] for k in ("key","strategy","total_return","max_drawdown","total_fees")} for r in five["comparison"] if r["key"] in {"base",five["selected_key"]}]
        metadata["precision_audit"] = five["precision_audit"]
        # Confirm that reused state coverage refers to the same active evaluation cells.
        loc=(panel.dates>=START)&(panel.dates<=END)
        active=(panel.arrays["close"][loc]>0)&(panel.arrays["amt"][loc]>0)&(panel.arrays["num_trades"][loc]>0)
        unknown=~(np.isin(panel.states["isST"][loc],[0,1])&np.isin(panel.states["tradestatus"][loc],[0,1]))
        audit=metadata["precision_audit"]
        if (int(active.sum())!=audit["active_quote_cells"] or
            int((active&unknown).sum())!=audit["unknown_active_state_cells"] or
            panel.audit["reference_manifest_sha256"]!=five["data_audit"]["reference_manifest_sha256"]):
            raise ValueError("Historical state coverage changed since 5DR audit")
        write_json(root/"precision_audit.json", audit)
    write_json(root/"summary.json",metadata)
    files = ["backtest/precision.py","backtest/breakout_pool.py","research_breakout.py","research_5dr.py","validate_5dr.py","reference/corporate_reference_overrides.json"]
    if overrides.exists(): files.append(str(overrides))
    manifest = {"completed_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "runtime":{"python":platform.python_version(),"pandas":pd.__version__,"numpy":np.__version__},
                "protocol_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                "control_protocol_sha256":hashlib.sha256(control_protocol.read_bytes()).hexdigest(),
                "code_sha256":{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files},
                "course_sha256":{name:hashlib.sha256((Path(args.data_dir)/(name+".feather")).read_bytes()).hexdigest() for name in panel.frames},
                "reference_manifest_sha256":panel.audit["reference_manifest_sha256"],
                "action_cache_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(args.action_dir).glob("*.json"))}}
    write_json(root/"source_manifest.json",manifest)
    write_json(root/"run_status.json",{"status":"COMPLETE","completed_at":manifest["completed_at"]})
    print(json.dumps({"selected":selected,"comparison":[{k:r[k] for k in ("key","total_return","max_drawdown","total_fees")} for r in comparison]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",required=True)
    parser.add_argument("--reference-dir",default="data/reference/baostock-20230901-20260930")
    parser.add_argument("--action-dir",default="data/reference/actions")
    parser.add_argument("--output",default="results/breakout_review")
    parser.add_argument("--provisional",action="store_true")
    parser.add_argument("--register-only",action="store_true")
    args=parser.parse_args()
    try: run(args)
    except Exception as exc:
        Path(args.output).mkdir(parents=True,exist_ok=True)
        write_json(Path(args.output)/"run_status.json",{"status":"FAILED","error":str(exc)})
        raise
