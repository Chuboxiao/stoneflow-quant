from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
import pandas as pd


@dataclass(frozen=True)
class StrategyContext:
    date: pd.Timestamp
    symbols: tuple[str, ...]
    cash: float
    equity: float
    positions: Mapping[str, float]
    _history: object

    def history(self, field="close", lookback=None, adjusted=True):
        """只返回截至当前收盘的副本；没有供策略指定未来日期的参数。"""
        return self._history(field, lookback, adjusted)


class Strategy(Protocol):
    def on_close(self, context: StrategyContext) -> Mapping[str, float] | None: ...


class PeriodicEqualWeight:
    """系统验证用：每 N 个交易日等权配置；不包含任务二的选股逻辑。"""

    def __init__(self, every=20, invested_weight=0.98):
        if not isinstance(every, int) or every < 1 or not 0 < invested_weight <= 1:
            raise ValueError("调仓间隔须为正整数，投资比例须在 (0,1] 内")
        self.every = every
        self.invested_weight = invested_weight
        self._count = 0

    def on_close(self, context):
        rebalance = self._count % self.every == 0
        self._count += 1
        if not rebalance:
            return None
        prices = context.history("close", 1, adjusted=True).iloc[-1]
        available = [s for s in context.symbols if pd.notna(prices[s]) and prices[s] > 0]
        if not available:
            return None
        weight = self.invested_weight / len(available)
        return {s: weight for s in available}
