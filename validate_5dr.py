"""Independent replay of saved raw-share ledgers (does not invoke the engine)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_UP
import numpy as np
import pandas as pd


def product(a,b):
    return float((Decimal(str(a))*Decimal(str(b))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def validate_run(directory):
    metrics=json.loads((directory/"metrics.json").read_text())
    parameters=json.loads((directory/"parameters.json").read_text())
    cfg=parameters["execution"]
    eq=pd.read_csv(directory/"equity.csv")
    orders=pd.read_csv(directory/"orders.csv")
    pos=pd.read_csv(directory/"positions.csv")
    actions=pd.read_csv(directory/"actions.csv")
    signals=pd.read_csv(directory/"signals.csv")
    cash=cfg["cash"];receivable=0.;holdings=defaultdict(float)
    errors=[];max_cash_error=max_shares_error=max_equity_error=0.
    checks=0
    def require(condition,message):
        nonlocal checks
        checks+=1
        if not condition:errors.append(message)
    require(not metrics["missing_actions"],"Missing held corporate actions")
    require(not metrics.get("event_reference_discrepancies"),"Corporate-event reference mismatch")
    require(not cfg["allow_missing_actions"],"Provisional engine was used")
    require(bool((signals.is_st==0).all()),"A signal selected ST/unknown")
    for day in eq.itertuples(index=False):
        acts=actions[actions.date==day.date]
        for row in acts.itertuples(index=False):
            cash+=row.cash_delta;receivable+=row.receivable_delta;holdings[row.symbol]+=row.shares_delta
            require(row.type!="PROVISIONAL_FACTOR_UNITS",f"{day.date}: synthetic share fallback")
        today=orders[orders.execution_date==day.date]
        for row in today.itertuples(index=False):
            require(row.signal_date<row.execution_date,f"{day.date}: noncausal order")
            require(row.planned_qty<=row.requested_qty+1e-7,f"{day.date}: plan exceeds request")
            if row.notional>0:
                sign=1 if row.side=="BUY" else -1
                fees=row.commission+row.stamp_tax+row.transfer_fee
                cash-=sign*row.notional+fees;holdings[row.symbol]+=sign*row.filled_qty
                require(row.filled_qty<=row.planned_qty+1e-7,f"{day.date}: fill exceeds fixed order")
                require(row.planned_qty<=50_000,f"{day.date}: single-order maximum")
                require(row.filled_qty*row.sizing_reference_close<=row.lagged_mean_amount20*cfg["participation"]+1e-5,f"{day.date}: exceeds lagged liquidity cap")
                require(abs(row.filled_qty-round(row.filled_qty))<1e-7,f"{day.date}: noninteger raw shares")
                require(abs(row.notional-product(row.filled_qty,row.raw_execution_price))<.00001,f"{day.date}: wrong notional")
                require(abs(row.commission-max(cfg["min_commission"],product(row.notional,cfg["commission"])))<.00001,f"{day.date}: wrong commission")
                require(abs(row.stamp_tax-(product(row.notional,cfg["stamp"]) if row.side=="SELL" else 0))<.00001,f"{day.date}: wrong stamp")
                require(abs(row.transfer_fee-product(row.notional,cfg["transfer"]))<.00001,f"{day.date}: wrong transfer fee")
                require(row.lower_limit-1e-7<=row.raw_execution_price<=row.upper_limit+1e-7,f"{day.date}: execution outside limits")
                star=row.symbol.startswith(("688","689"))
                if row.side=="BUY":
                    require(row.signal_is_st==0 and row.execution_is_st==0,f"{day.date}: ST/unknown buy")
                    require(row.raw_open<row.upper_limit-1e-7 and row.raw_execution_price<row.upper_limit-1e-7,f"{day.date}: limit-up buy")
                    require(row.filled_qty>=200 if star else row.filled_qty%100==0,f"{day.date}: invalid buy lot")
                else:
                    require(row.raw_open>row.lower_limit+1e-7 and row.raw_execution_price>row.lower_limit+1e-7,f"{day.date}: limit-down sell")
                    fully_sold=abs(holdings[row.symbol])<1e-7
                    require(fully_sold or (row.filled_qty>=200 if star else row.filled_qty%100==0),f"{day.date}: invalid sell lot")
                require(holdings[row.symbol]>=-1e-7,f"{day.date}: short position")
            else:
                require(row.filled_qty==0 and row.commission==0 and row.stamp_tax==0 and row.transfer_fee==0,f"{day.date}: rejected order moved money")
            require(abs(cash-row.cash_after)<1e-5,f"{day.date}: order cash mismatch")
        snapshot=pos[pos.date==day.date]
        saved=dict(zip(snapshot.symbol,snapshot.shares))
        share_error=max((abs(holdings[s]-saved.get(s,0)) for s in holdings),default=0)
        max_shares_error=max(max_shares_error,share_error)
        cash_error=abs(cash-day.cash);max_cash_error=max(max_cash_error,cash_error)
        account_error=abs(day.cash+snapshot.market_value.sum()+receivable-day.equity)
        max_equity_error=max(max_equity_error,account_error)
        require(share_error<1e-5,f"{day.date}: shares mismatch")
        require(cash_error<1e-5,f"{day.date}: daily cash mismatch")
        require(abs(receivable-day.dividend_receivable)<1e-5,f"{day.date}: dividend receivable mismatch")
        require(account_error<1e-5,f"{day.date}: equity mismatch")
        require(bool(((snapshot.shares*snapshot.valuation_mark-snapshot.market_value).abs()<1e-5).all()),f"{day.date}: position market value mismatch")
        require(day.cash>=-1e-5,f"{day.date}: negative cash")
        require(abs(day.fees-(today.commission+today.stamp_tax+today.transfer_fee).sum())<1e-5,f"{day.date}: daily fees mismatch")
    require(abs(eq.net_value.iloc[-1]-1-metrics["total_return"])<1e-12,"Return mismatch")
    return {"run":str(directory),"passed":not errors,"checks":checks,"errors":errors[:30],
            "max_cash_error":max_cash_error,"max_shares_error":max_shares_error,"max_equity_error":max_equity_error}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--results",default="results/5dr_review")
    args=parser.parse_args();root=Path(args.results)
    records=[]
    for path in sorted(root.rglob("metrics.json")):
        result=validate_run(path.parent);result["run"]=str(path.parent.relative_to(root));records.append(result)
    output={"passed":bool(records) and all(x["passed"] for x in records),"runs_checked":len(records),
            "checks":sum(x["checks"] for x in records),"runs":records}
    (root/"validation.json").write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in output.items() if k!="runs"},ensure_ascii=False))
    if not output["passed"]:raise SystemExit(1)


if __name__=="__main__":main()
