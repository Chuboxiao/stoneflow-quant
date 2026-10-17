"""Reproduce the 2025-01-02—2026-09-30 homework; no automatic publishing."""
from __future__ import annotations
import argparse
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import time
import platform
import numpy as np
import pandas as pd
from backtest.precision import Panel,PrecisionConfig,PrecisionEngine,Reversal5DR,SPECS
from backtest.report import json_safe

START,END="2025-01-02","2026-09-30"
TRAIN_START,TRAIN_END="2024-01-02","2024-12-31"


def write_json(path,obj):
    path.write_text(json.dumps(json_safe(obj),ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


def save_result(result,directory):
    directory.mkdir(parents=True,exist_ok=True)
    for key in ("equity","orders","positions","signals","actions","valuation"):
        frame=result[key]
        if not len(frame.columns):frame=pd.DataFrame(columns=["date","symbol","type"])
        frame.to_csv(directory/f"{key}.csv",index=False,encoding="utf-8-sig")
    write_json(directory/"metrics.json",result["metrics"])
    write_json(directory/"parameters.json",{"spec":result["spec"],"execution":result["config"]})


def protocol():
    return {"registered_before_evaluation":True,"performance_start":START,"performance_end":END,
            "training_start":TRAIN_START,"training_end":TRAIN_END,"universe":"all course matrix columns, daily historical eligibility",
            "initial_cash":1_000_000,"candidates":[asdict(x) for x in SPECS],
            "selection":"max 2024 annualized_return / (abs(max_drawdown)+0.05); tie by key",
            "primary_comparison":"2024-selected model versus baseline in 2025-2026",
            "evaluation_variants":"All five retained and marked descriptive; no reselection on evaluation period",
            "st_policy":"isST == 0 at signal and execution; missing state excluded; new ST positions seek exit",
            "pricing":"raw cash/share account; adjusted close * cumadj for 5-session returns",
            "execution":asdict(PrecisionConfig()),
            "corporate_actions":"Cash dividends net of fixed 20% tax; receivable until payable; stock delivery lock; unsupported events stop final run",
            "endpoint":"close valuation, no forced liquidation; final signals excluded",
            "known_limits":["historical isST has effective dates, not publication timestamps",
              "provider preclose + board rule is not official limit-price file",
              "opening prints are execution proxies, daily volume cannot prove order queue fills",
              "no free access to full official delisting/corporate-event ledger; no claim of exact live account replication",
              "fractional bonus allocations rounded down; missing stock delivery date assumed ex-date and counted",
              "cash-dividend 20% deduction is conservative, not individualized holding-period taxation"]}


def run(data_dir,reference_dir,action_dir,output,provisional=False,register_only=False):
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    registration=root/"protocol.json"
    if not registration.exists():
        content=protocol();content["created_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z")
        write_json(registration,content)
    if register_only:return
    write_json(root/"run_status.json",{"status":"RUNNING","started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    registered=json.loads(registration.read_text())
    if registered["candidates"]!=protocol()["candidates"]:raise ValueError("Registered candidate specifications changed")
    panel=Panel.load(data_dir,reference_dir,action_dir)
    write_json(root/"data_audit.json",panel.audit)
    coverage=[]
    for i,date in enumerate(panel.dates):
        if not START<=str(date.date())<=END:continue
        active=(panel.arrays["close"][i]>0)&(panel.arrays["amt"][i]>0)&(panel.arrays["num_trades"][i]>0)
        known=np.isin(panel.states["isST"][i],[0,1])&np.isin(panel.states["tradestatus"][i],[0,1])
        coverage.append({"date":str(date.date()),"active_quotes":int(active.sum()),
                         "st_quotes":int((active&(panel.states["isST"][i]==1)).sum()),
                         "unknown_state_quotes":int((active&~known).sum()),
                         "historical_non_st":int((active&known&(panel.states["isST"][i]==0)).sum())})
    precision_audit={"coverage_by_day":coverage,"active_quote_cells":sum(x["active_quotes"] for x in coverage),
                     "unknown_active_state_cells":sum(x["unknown_state_quotes"] for x in coverage),
                     "st_active_cells_excluded":sum(x["st_quotes"] for x in coverage),
                     "raw_cash_account":True,"price_rounding":"ROUND_HALF_UP, no binary bankers rounding",
                     "universe_completeness":"Limited to course package; historical whole-market completeness not established",
                     "st_timestamp_assumption":"Effective-date status is assumed available before opening; announcement-time vintages unavailable"}
    precision_audit["known_state_coverage"]=1-precision_audit["unknown_active_state_cells"]/max(1,precision_audit["active_quote_cells"])
    write_json(root/"precision_audit.json",precision_audit)
    missing=set();training=[];results={}
    config=replace(PrecisionConfig(),allow_missing_actions=provisional)
    for spec in SPECS:
        print("Training",spec.key,flush=True)
        result=PrecisionEngine(panel,config).run(Reversal5DR(spec),TRAIN_START,TRAIN_END)
        save_result(result,root/"training"/spec.key)
        missing.update(tuple(x) for x in result["metrics"]["missing_actions"])
        m=result["metrics"]
        training.append({"key":spec.key,"strategy":spec.title,"score":m["annualized_return"]/(abs(m["max_drawdown"])+.05),**m})
    selected=sorted(training,key=lambda x:(-x["score"],x["key"]))[0]["key"]
    write_json(root/"selection.json",{"selected_key":selected,"basis":"2024 only","provisional":provisional,
                                     "protocol_sha256":hashlib.sha256(registration.read_bytes()).hexdigest(),
                                     "training":training})
    comparison=[]
    for spec in SPECS:
        print("Evaluation",spec.key,flush=True)
        result=PrecisionEngine(panel,config).run(Reversal5DR(spec),START,END)
        save_result(result,root/"evaluation"/spec.key)
        results[spec.key]=result
        missing.update(tuple(x) for x in result["metrics"]["missing_actions"])
        comparison.append({"key":spec.key,"strategy":spec.title,"selected_on_2024":spec.key==selected,**result["metrics"]})
    write_json(root/"needed_actions.json",[list(x) for x in sorted(missing)])
    write_json(root/"comparison.json",comparison)
    pd.DataFrame(comparison).drop(columns=["missing_actions","rejection_reasons"]).to_csv(root/"comparison.csv",index=False,encoding="utf-8-sig")
    # Stress the selected model and baseline under identical additional assumptions.
    stresses=[]
    selected_specs=[x for x in SPECS if x.key in {"base",selected}]
    for label,stress_cfg in (("double_cost",replace(config,commission=config.commission*2,min_commission=config.min_commission*2,stamp=config.stamp*2,transfer=config.transfer*2,slippage_bps=config.slippage_bps*2)),
                             ("tight_capacity",replace(config,participation=.001)),
                             ("gross_dividend",replace(config,dividend_tax=0)),
                             ("carry_stale",replace(config,impairment_after=100000))):
        for spec in selected_specs:
            print("Stress",label,spec.key,flush=True)
            result=PrecisionEngine(panel,stress_cfg).run(Reversal5DR(spec),START,END)
            save_result(result,root/"stress"/label/spec.key)
            missing.update(tuple(x) for x in result["metrics"]["missing_actions"])
            stresses.append({"scenario":label,"key":spec.key,"strategy":spec.title,**result["metrics"]})
    write_json(root/"stress.json",stresses)
    # Keep the two original stocks as diagnostics, without using them for 5DR selection.
    from backtest.breakout import BreakoutStrategy,BuyAndHold
    focus=[]
    for symbol in ("603950.SH","002230.SZ"):
        j=panel.index[symbol]
        one=Panel({k:v[[symbol]].copy() for k,v in panel.frames.items()},
                  {k:pd.DataFrame(v[:,j],index=panel.dates,columns=[symbol]) for k,v in panel.states.items()},panel.events,reference_overrides=panel.reference_overrides)
        for case,title in (("breakout","普通20日突破"),("confirmed","成交额确认突破"),("hold","买入持有")):
            print("Focus",symbol,case,flush=True)
            strategy=BuyAndHold(.95) if case=="hold" else BreakoutStrategy(amount_multiplier=1.5 if case=="confirmed" else None,weight=.95)
            result=PrecisionEngine(one,replace(config,cash=config.cash/2)).run(strategy,START,END)
            save_result(result,root/"focus"/symbol/case)
            missing.update(tuple(x) for x in result["metrics"]["missing_actions"])
            focus.append({"symbol":symbol,"strategy":title,"case":case,**result["metrics"]})
    write_json(root/"focus_stocks.json",focus)
    write_json(root/"needed_actions.json",[list(x) for x in sorted(missing)])
    if provisional:
        write_json(root/"run_status.json",{"status":"PROVISIONAL","missing_actions":len(missing)})
        print(json.dumps({"provisional":True,"missing_actions":len(missing),"selected":selected}),flush=True)
        return
    periods=[]
    for key,result in results.items():
        eq=result["equity"]
        for title,begin,finish in (("2025",START,"2025-12-31"),("2026年前三季度","2026-01-01",END),
                                  ("2025上半年",START,"2025-06-30"),("2025下半年","2025-07-01","2025-12-31")):
            mask=(eq.date>=begin)&(eq.date<=finish)
            block=eq[mask];idx=np.flatnonzero(mask.to_numpy())[0]
            starting=config.cash if idx==0 else eq.equity.iloc[idx-1]
            vals=block.equity.to_numpy();peak=np.maximum.accumulate(np.r_[starting,vals])[1:]
            periods.append({"key":key,"period":title,"total_return":float(vals[-1]/starting-1),
                            "max_drawdown":float((vals/peak-1).min()),"trading_days":len(block)})
    write_json(root/"periods.json",periods)
    metadata={"status":"REVIEW_ONLY","selected_key":selected,"performance_start":START,"performance_end":END,
              "trading_days":424,"pool_size":len(panel.symbols),"protocol_sha256":hashlib.sha256(registration.read_bytes()).hexdigest(),
              "data_audit":panel.audit,"comparison":comparison,"stress":stresses,"periods":periods,
              "notes":registered["known_limits"],"raw_data_published":False,"precision_audit":precision_audit,"focus_stocks":focus}
    benchmark_path=Path(reference_dir).parent/"csi300.csv"
    if benchmark_path.exists():
        benchmark=pd.read_csv(benchmark_path,parse_dates=["date"]).set_index("date")["close"]
        reference=float(benchmark.loc[:pd.Timestamp(START)-pd.Timedelta(days=1)].iloc[-1])
        normalized=benchmark.reindex(pd.to_datetime(results["base"]["equity"].date))/reference
        if normalized.notna().all():
            metadata["benchmark"]=[{"date":str(d.date()),"net_value":float(v)} for d,v in normalized.items()]
            metadata["benchmark_note"]="CSI300 price index / 2024-12-31 close, no costs, not a tradeable-account backtest"
    write_json(root/"summary.json",metadata)
    source_files=["backtest/precision.py","research_5dr.py","validate_5dr.py","tools/fetch_reference.py","tools/fetch_actions.py","reference/corporate_reference_overrides.json"]
    code_root=Path(__file__).resolve().parent
    source_manifest={"runtime":{"python":platform.python_version(),"pandas":pd.__version__,"numpy":np.__version__},
                     "code_sha256":{name:hashlib.sha256((code_root/name).read_bytes()).hexdigest() for name in source_files},
                     "course_sha256":{name:hashlib.sha256((Path(data_dir)/f"{name}.feather").read_bytes()).hexdigest() for name in panel.frames},
                     "reference_manifest_sha256":panel.audit["reference_manifest_sha256"],
                     "action_cache_sha256":{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(action_dir).glob("*.json"))},
                     "completed_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    write_json(root/"source_manifest.json",source_manifest)
    write_json(root/"run_status.json",{"status":"COMPLETE","completed_at":source_manifest["completed_at"]})
    print(json.dumps({"selected":selected,"comparison":[{k:r[k] for k in ("key","total_return","max_drawdown","total_fees")} for r in comparison]},ensure_ascii=False,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",required=True)
    p.add_argument("--reference-dir",default="data/reference/baostock-20230901-20260930")
    p.add_argument("--action-dir",default="data/reference/actions")
    p.add_argument("--output",default="results/5dr_review")
    p.add_argument("--provisional",action="store_true")
    p.add_argument("--register-only",action="store_true")
    args=p.parse_args()
    try:
        run(args.data_dir,args.reference_dir,args.action_dir,args.output,args.provisional,args.register_only)
    except Exception as exc:
        Path(args.output).mkdir(parents=True,exist_ok=True)
        write_json(Path(args.output)/"run_status.json",{"status":"FAILED","error":str(exc)})
        raise
