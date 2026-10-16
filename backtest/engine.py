from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import platform
from types import MappingProxyType
import numpy as np
import pandas as pd
from .broker import SimBroker
from .clock import SimClock
from .limits import LimitPolicy
from .models import BacktestConfig, FeeModel, Order
from .strategy import StrategyContext


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    orders: pd.DataFrame
    positions: pd.DataFrame
    signals: pd.DataFrame
    metrics: dict
    metadata: dict


def validate_weights(weights, symbols):
    if not hasattr(weights, "items"):
        raise ValueError("策略必须返回代码到目标权重的映射，或 None")
    result = {}
    for symbol, value in weights.items():
        if symbol not in symbols:
            raise ValueError(f"目标权重包含未加载的证券：{symbol}")
        value = float(value)
        if not math.isfinite(value) or value < 0 or value > 1:
            raise ValueError("权重必须为 [0,1] 内的有限值；不支持做空")
        result[symbol] = value
    if sum(result.values()) > 1 + 1e-10:
        raise ValueError("总目标权重不得超过 1；不支持杠杆")
    return result


class BacktestEngine:
    def __init__(self, market, config=None, fees=None, limits=None):
        self.market = market
        self.config = config or BacktestConfig()
        self.fees = fees or FeeModel()
        self.limits = limits or LimitPolicy(self.config.limit_mode)
        if self.config.limit_mode != self.limits.mode:
            raise ValueError("配置的涨跌停模式和 LimitPolicy 不一致")
        self._used = False

    def run(self, strategy, start=None, end=None):
        if self._used:
            raise RuntimeError("每次回测请新建引擎和策略，避免复用状态")
        self._used = True
        start = pd.Timestamp(start) if start else self.market.common_first_date()
        end = pd.Timestamp(end) if end else self.market.dates[-1]
        dates = self.market.dates[(self.market.dates >= start) & (self.market.dates <= end)]
        if len(dates) < 2:
            raise ValueError("回测区间至少需要两个交易日")
        broker = SimBroker(self.market, self.config, self.fees, self.limits)
        equity_rows, positions, signals = [], [], []
        pending = None
        previous_equity = self.config.initial_cash
        peak = self.config.initial_cash
        cumulative_fees = 0.0
        for tick in SimClock(dates):
            date = tick.date
            if tick.phase == "OPEN":
                broker.mark(date, "open")
                if pending is not None:
                    signal_date, targets = pending
                    broker.rebalance(date, signal_date, targets)
                    pending = None
            else:
                equity = broker.mark(date, "close")
                current_orders = [o for o in broker.orders if o.execution_date == str(date.date())]
                fees = sum(o.commission + o.stamp_tax for o in current_orders)
                cumulative_fees += fees
                peak = max(peak, equity)
                snapshots = broker.position_rows(date, equity)
                positions.extend(snapshots)
                equity_rows.append({
                    "date": str(date.date()), "cash": broker.cash,
                    "market_value": equity - broker.cash, "equity": equity,
                    "net_value": equity / self.config.initial_cash,
                    "daily_return": equity / previous_equity - 1,
                    "drawdown": equity / peak - 1, "fees": fees,
                    "cumulative_fees": cumulative_fees,
                    "traded_notional": sum(o.notional for o in current_orders),
                    "stale_positions": sum(r["stale_valuation"] for r in snapshots),
                })
                previous_equity = equity
                context = StrategyContext(
                    date, self.market.symbols, broker.cash, equity,
                    MappingProxyType(dict(broker.positions)),
                    lambda field, lookback, adjusted, d=date: self.market.history(d, field, lookback, adjusted),
                )
                decision = strategy.on_close(context)
                if decision is not None:
                    targets = validate_weights(decision, self.market.symbols)
                    for symbol in self.market.symbols:
                        signals.append({"signal_date": str(date.date()), "symbol": symbol,
                                        "target_weight": targets.get(symbol, 0.0),
                                        "execution": "OUTSIDE_BACKTEST_RANGE" if date == dates[-1]
                                        else "NEXT_TRADING_OPEN"})
                    pending = (date, targets)
        frame = pd.DataFrame(equity_rows)
        orders = pd.DataFrame(broker.order_rows(), columns=[f.name for f in fields(Order)])
        pos = pd.DataFrame(positions)
        signal_frame = pd.DataFrame(signals, columns=["signal_date", "symbol", "target_weight", "execution"])
        returns = frame["daily_return"]
        volatility = float(returns.std(ddof=1))
        n = len(frame)
        final_net = float(frame["net_value"].iloc[-1])
        filled = orders[orders["notional"] > 0]
        metrics = {
            "start": str(dates[0].date()), "end": str(dates[-1].date()), "trading_days": n,
            "initial_cash": self.config.initial_cash, "final_equity": float(frame["equity"].iloc[-1]),
            "total_return": final_net - 1,
            "annualized_return": final_net ** (self.config.trading_days_per_year / n) - 1,
            "annualized_volatility": volatility * np.sqrt(self.config.trading_days_per_year),
            "sharpe_zero_risk_free": float(returns.mean() / volatility * np.sqrt(self.config.trading_days_per_year))
            if volatility > 1e-12 else None,
            "max_drawdown": float(frame["drawdown"].min()),
            "total_fees": float(frame["fees"].sum()), "filled_orders": len(filled),
            "rejected_orders": int((orders["status"] == "REJECTED").sum()),
            "partial_orders": int((orders["status"] == "PARTIAL").sum()),
            "stale_valuation_days": int((frame["stale_positions"] > 0).sum()),
            "unexecuted_final_signal": pending is not None,
            "rejection_reasons": orders.loc[orders["status"] == "REJECTED", "reason"].value_counts().to_dict(),
        }
        # 买入持有单只证券的复权价格参考线，忽略费用，仅从回测起始日归一。
        for symbol in self.market.symbols:
            prices = self.market.history(dates[-1], "close", adjusted=True).reindex(dates)[symbol]
            reference = float(prices.iloc[0])
            frame[f"reference_{symbol}"] = (prices.ffill() / reference).to_numpy() if self.market.positive(reference) else np.nan
        metadata = {
            "runtime": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
            "data_audit": self.market.audit(), "config": asdict(self.config), "fees": asdict(self.fees),
            "accounting": "adjusted_units_with_fixed_factor_reference",
            "strategy": type(strategy).__name__,
            "timing": "close signal -> next trading open; last signal never filled inside range",
            "limit_mode": self.config.limit_mode,
            "limit_sources_used": sorted(set(orders["limit_source"]) - {""}),
            "notes": [
                "持仓采用复权单位；raw_equivalent_qty 为模型等价股数，不是实际登记股数。",
                "cumadj 无法区分现金分红、送股、配股；不生成虚构分红现金或声称精确再投资。",
                "conservative 使用因子还原的参考价与向内一分钱的 5% 保护；可能过度拒单，也不能证明精确识别所有历史涨停。",
                "strict 缺少对应日期和证券的外部精确涨跌停资料时拒绝交易。",
                "开盘定价使用当日 open、cumadj 和盘前涨跌停资料；全天成交额非正或缺失仅用于事后否决不可能的成交，不用于盘前选股或估计容量。",
                "当日 cumadj 假设在盘前已知；真实实盘应使用当时已经公布的公司行为资料。",
                "仅模拟开盘成交；没有盘口排队、成交量容量、盘中撮合及真实分红到账日。",
                "缺失收盘持仓采用最后有效估值并标记 stale；退市后不会虚构清仓，相关结果须单独复核。",
                "默认每笔买入按 100 等价股取整，适用于本次主板教学示例，未完整实现各板块申报规则。",
                "卖方印花税按 2023-08-28 前后两档；不含过户费等全部真实费用。年化假设每年 252 个交易日，无风险利率为零。",
                "最后一天不强制清仓，期末资产按持仓收盘估值；未扣除假设清仓费用。",
            ],
        }
        return BacktestResult(frame, orders, pos, signal_frame, metrics, metadata)
