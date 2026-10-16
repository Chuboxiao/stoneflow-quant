from __future__ import annotations

import argparse
from pathlib import Path
from .data import MarketData
from .engine import BacktestEngine
from .limits import LimitPolicy
from .models import BacktestConfig, FeeModel
from .report import export_result
from .strategy import PeriodicEqualWeight


def main(argv=None):
    parser = argparse.ArgumentParser(description="第四讲：日频回测系统。默认 strict；缺少精确涨跌停资料拒单。")
    parser.add_argument("--data-dir", required=True, type=Path, help="包含七个 Feather 文件的目录")
    parser.add_argument("--symbols", nargs="+", default=["603950.SH", "002230.SZ"])
    parser.add_argument("--start", help="YYYY-MM-DD；默认首个共同有效收盘日期")
    parser.add_argument("--end", help="YYYY-MM-DD；默认数据最后一天")
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--limit-mode", choices=["strict", "conservative"], default="strict")
    parser.add_argument("--limits-csv", type=Path, help="外部精确涨跌停、停牌资料；格式见 examples")
    parser.add_argument("--rebalance-every", type=int, default=20)
    parser.add_argument("--invested-weight", type=float, default=0.98)
    parser.add_argument("--commission", type=float, default=0.0003)
    parser.add_argument("--min-commission", type=float, default=5)
    parser.add_argument("--slippage-bps", type=float, default=5)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("results/latest"))
    args = parser.parse_args(argv)
    try:
        market = MarketData.from_feather(args.data_dir, args.symbols)
        config = BacktestConfig(args.cash, args.lot_size, args.limit_mode)
        fees = FeeModel(args.commission, args.min_commission, args.slippage_bps)
        policy = LimitPolicy.from_csv(args.limits_csv, args.limit_mode)
        strategy = PeriodicEqualWeight(args.rebalance_every, args.invested_weight)
        engine = BacktestEngine(market, config, fees, policy)
        result = engine.run(strategy, args.start, args.end)
        result.metadata["strategy_parameters"] = {"rebalance_every":args.rebalance_every,
                                                   "invested_weight":args.invested_weight}
        report = export_result(result, args.output)
    except (ValueError, FileNotFoundError, RuntimeError, ImportError) as exc:
        parser.exit(2, f"运行失败：{exc}\n")
    m = result.metrics
    print(f"完成：{m['start']} 至 {m['end']}，{m['trading_days']} 个交易日")
    print(f"成交 {m['filled_orders']} 笔，拒单 {m['rejected_orders']} 笔，期末资产 {m['final_equity']:,.2f} 元")
    print(f"收益 {m['total_return']:.2%}，最大回撤 {m['max_drawdown']:.2%}")
    print(f"模式：{args.limit_mode}；复权单位教学账户")
    if args.limit_mode == "conservative":
        print("注意：当前使用保守代理，不是精确历史涨跌停判断。")
    if m["rejection_reasons"].get("MISSING_PRICE_LIMITS"):
        print("精确涨跌停资料不足，相关交易已拒绝；请补充 --limits-csv。")
    print(f"报告：{report}")
    return result


if __name__ == "__main__":
    main()
