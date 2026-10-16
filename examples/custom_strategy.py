"""如何替换策略：只需实现 on_close，返回目标权重或 None。"""
from backtest import BacktestConfig, BacktestEngine, MarketData
from backtest.limits import LimitPolicy
from backtest.report import export_result


class MyStrategy:
    def on_close(self, context):
        # 这里拿到的副本最多到 context.date，不会暴露未来行情。
        history = context.history("close", lookback=6, adjusted=True)
        if len(history) < 6:
            return None
        # 占位示例：保持现金。任务二时在此定义选股、卖出和仓位规则。
        return {}


def run(data_dir, limits_csv):
    data = MarketData.from_feather(data_dir, ["603950.SH", "002230.SZ"])
    engine = BacktestEngine(data, BacktestConfig(limit_mode="strict"),
                            limits=LimitPolicy.from_csv(limits_csv, "strict"))
    result = engine.run(MyStrategy())
    return export_result(result, "results/custom")
