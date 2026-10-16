"""从落盘账本独立重放现金与单位持仓，不调用引擎的记账函数。"""
from pathlib import Path
import json
import unittest
import numpy as np
import pandas as pd


def validate(directory):
    directory = Path(directory)
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    equity = pd.read_csv(directory / "equity.csv")
    orders = pd.read_csv(directory / "orders.csv")
    positions = pd.read_csv(directory / "positions.csv")
    fills = orders[orders.notional > 0].copy()
    signs = fills.side.map({"BUY":-1.0,"SELL":1.0})
    fills["cash_change"] = signs * fills.notional - fills.commission - fills.stamp_tax
    cash_changes = fills.groupby("execution_date").cash_change.sum().reindex(equity.date,fill_value=0)
    replay_cash = metrics["initial_cash"] + cash_changes.cumsum().to_numpy()
    cash_error = float(np.max(np.abs(replay_cash - equity.cash.to_numpy())))
    position_error = 0.0
    for symbol in positions.symbol.unique():
        sf = fills[fills.symbol == symbol].copy()
        sf["unit_change"] = sf.side.map({"BUY":1.0,"SELL":-1.0}) * sf.filled_adjusted_units
        change = sf.groupby("execution_date").unit_change.sum().reindex(equity.date,fill_value=0)
        recorded = positions[positions.symbol == symbol].set_index("date").reindex(equity.date)
        position_error = max(position_error,float(np.max(np.abs(change.cumsum().to_numpy() - recorded.adjusted_units))))
    market_values = positions.groupby("date").market_value.sum().reindex(equity.date)
    equity_error = float(np.max(np.abs(equity.cash + market_values.to_numpy() - equity.equity)))
    costs_error = abs(float(orders.commission.sum()+orders.stamp_tax.sum()) - metrics["total_fees"])
    timing_ok = bool((pd.to_datetime(orders.signal_date) < pd.to_datetime(orders.execution_date)).all())
    zero_for_rejections = bool((orders.loc[orders.status == "REJECTED","notional"] == 0).all())
    assert cash_error < 1e-6, cash_error
    assert position_error < 1e-7, position_error
    assert equity_error < 1e-6, equity_error
    assert costs_error < 1e-6, costs_error
    assert timing_ok and zero_for_rejections
    assert (equity.cash >= -1e-8).all()
    assert np.isclose(equity.equity.iloc[-1],metrics["final_equity"])
    return {"cash_replay_max_error":cash_error,"position_replay_max_error":position_error,
            "equity_reconciliation_max_error":equity_error,"fee_reconciliation_error":costs_error,
            "all_signal_dates_before_execution":timing_ok,"all_rejected_orders_zero_notional":zero_for_rejections,
            "cash_always_nonnegative":True,"trading_days":len(equity),
            "filled_orders":metrics["filled_orders"],"rejected_orders":metrics["rejected_orders"]}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root/"tests"))
    tests = unittest.TextTestRunner(verbosity=1).run(suite)
    if not tests.wasSuccessful():
        raise SystemExit("测试失败，未写入验证成功结果")
    result = {"unit_tests_passed":tests.testsRun,"demo":validate(root/"results/demo"),
              "strict_audit":validate(root/"results/strict_audit")}
    strict = result["strict_audit"]
    assert strict["filled_orders"] == 0 and strict["rejected_orders"] > 0
    result["strict_missing_limits_fail_closed"] = True
    if (root/"results/research/metrics.json").exists():
        result["research"] = validate(root/"results/research")
        result["research_subaccounts"] = {
            str(p.relative_to(root/"results/research/subaccounts")):validate(p)
            for p in (root/"results/research/subaccounts").glob("*/*") if p.is_dir()}
    (root/"results/validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
