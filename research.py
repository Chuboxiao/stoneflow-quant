"""任务二：两只证券、三个方案、六个独立子账户的可复现实验。"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import numpy as np
import pandas as pd
from backtest import MarketData, BacktestEngine, BacktestConfig, FeeModel
from backtest.breakout import BreakoutStrategy, BuyAndHold
from backtest.engine import BacktestResult
from backtest.limits import LimitPolicy
from backtest.report import export_result

CASES = {"breakout":"普通20日突破","confirmed":"成交额确认突破","hold":"买入并持有"}


def run_research(data_dir, symbols, start="2020-07-01", end="2026-10-16", cash=1000000,
                 limit_mode="conservative", fees=None, limits=None, output=None):
    if len(symbols)!=2: raise ValueError("研究比较需要恰好两只股票，分别使用一半初始资金")
    fees=fees or FeeModel()
    results, rows={},[]
    for case in CASES:
        children=[]
        for symbol in symbols:
            market=MarketData.from_feather(data_dir,[symbol])
            strategy=(BreakoutStrategy(amount_multiplier=1.5 if case=="confirmed" else None)
                      if case!="hold" else BuyAndHold())
            result=BacktestEngine(market,BacktestConfig(cash/2,100,limit_mode),fees,
                                  limits or LimitPolicy(limit_mode)).run(strategy,start,end)
            occupied=int((result.equity.market_value>1e-8).sum())
            row={"case":case,"strategy":CASES[case],"symbol":symbol,**result.metrics,
                 "exposure_ratio":occupied/len(result.equity)}
            rows.append(row)
            children.append(result)
            if output:
                export_result(result,Path(output)/"subaccounts"/case/symbol)
        results[case]=children
    base=results["breakout"]
    eq=base[0].equity[["date"]].copy()
    for field in ("cash","market_value","equity","fees","cumulative_fees","traded_notional","stale_positions"):
        eq[field]=base[0].equity[field].to_numpy()+base[1].equity[field].to_numpy()
    eq["net_value"]=eq.equity/cash
    eq["daily_return"]=eq.equity.div(eq.equity.shift(1).fillna(cash))-1
    eq["drawdown"]=eq.equity/np.maximum(cash,eq.equity.cummax())-1
    for i,s in enumerate(symbols): eq[f"reference_{s}"]=base[i].equity[f"reference_{s}"].to_numpy()
    combined=[]
    for case,children in results.items():
        values=children[0].equity.equity.to_numpy()+children[1].equity.equity.to_numpy()
        net=values/cash
        dd=values/np.maximum(cash,np.maximum.accumulate(values))-1
        if case!="breakout": eq[f"comparison_{case}"]=net
        combined.append({"case":case,"strategy":CASES[case],"symbol":"组合",
                         "total_return":float(net[-1]-1),"max_drawdown":float(dd.min()),
                         "annualized_return":float(net[-1]**(252/len(net))-1),
                         "filled_orders":sum(x.metrics["filled_orders"] for x in children),
                         "total_fees":sum(x.metrics["total_fees"] for x in children)})
    metrics=dict(base[0].metrics)
    metrics.update(initial_cash=cash,final_equity=float(eq.equity.iloc[-1]),total_return=float(eq.net_value.iloc[-1]-1),
                   annualized_return=float(eq.net_value.iloc[-1]**(252/len(eq))-1),max_drawdown=float(eq.drawdown.min()),
                   filled_orders=sum(x.metrics["filled_orders"] for x in base),
                   rejected_orders=sum(x.metrics["rejected_orders"] for x in base),
                   partial_orders=sum(x.metrics["partial_orders"] for x in base),
                   total_fees=float(eq.fees.sum()),stale_valuation_days=int((eq.stale_positions>0).sum()),
                   unexecuted_final_signal=any(x.metrics["unexecuted_final_signal"] for x in base))
    volatility=float(eq.daily_return.std(ddof=1))
    metrics["annualized_volatility"]=volatility*252**0.5
    metrics["sharpe_zero_risk_free"]=float(eq.daily_return.mean()/volatility*252**0.5) if volatility>1e-12 else None
    orders=pd.concat([x.orders for x in base],ignore_index=True).sort_values(["execution_date","symbol"]).reset_index(drop=True)
    orders["order_id"]=np.arange(1,len(orders)+1)
    metrics["rejection_reasons"]=orders.loc[orders.status=="REJECTED","reason"].value_counts().to_dict()
    positions=pd.concat([x.positions for x in base],ignore_index=True)
    positions["weight"]=positions.market_value/positions.date.map(eq.set_index("date").equity)
    signals=pd.concat([x.signals for x in base],ignore_index=True)
    metadata=dict(base[0].metadata)
    metadata.update(strategy="IndependentBreakoutAccounts",comparison=rows+combined,
                    research_title="趋势突破：成交额确认能否改善策略表现？",
                    research_rules={"entry_days":20,"exit_days":10,"amount_multiplier":1.5,
                                    "window_excludes_today":True,"independent_subaccounts":True,
                                    "allocation":0.5,"invested_weight":0.98})
    metadata["config"]={**metadata["config"],"initial_cash":cash}
    metadata["data_audit"]={"symbols":symbols,"source":str(data_dir),"subaccounts":[x.metadata["data_audit"] for x in base]}
    metadata["notes"]=[*metadata["notes"],"成交额非正或缺失的日线事后否决成交；这是执行可行性检查，不作为开盘选股信息。",
                       "两只股票各独立使用初始资金的一半；三种方案均扣费并采用同一撮合限制。",
                       "20/10/1.5 是预先给定的实验参数，未优化；全样本描述性比较，不是样本外有效性证明。"]
    result=BacktestResult(eq,orders,positions,signals,metrics,metadata)
    if output:
        export_result(result,output)
        pd.DataFrame(rows+combined).drop(columns=["rejection_reasons"],errors="ignore").to_csv(Path(output)/"comparison.csv",index=False,encoding="utf-8-sig")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",required=True)
    p.add_argument("--start",default="2020-07-01")
    p.add_argument("--end",default="2026-10-16")
    p.add_argument("--output",default="results/research")
    a=p.parse_args()
    r=run_research(a.data_dir,["603950.SH","002230.SZ"],a.start,a.end,output=a.output)
    print(json.dumps([x for x in r.metadata["comparison"] if x["symbol"]=="组合"],ensure_ascii=False,indent=2))
