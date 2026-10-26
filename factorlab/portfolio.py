"""Adapter: send a factor to the existing raw-share PrecisionEngine."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .core import FactorContext, eligible_mask


@dataclass(frozen=True)
class PortfolioSpec:
    key: str
    title: str
    top_n: int = 20
    every: int = 1
    weight: float = .95


class FactorPortfolio:
    def __init__(self, factor, pool="base", top_n=20, every=1, weight=.95, scores=None):
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1 or every < 1 or not 0 < weight <= 1:
            raise ValueError("无效组合参数")
        self.factor, self.pool, self.scores = factor, pool, scores
        self.spec = PortfolioSpec(f"{factor.key}_{pool}", factor.title, top_n, every, weight)

    def weights(self, panel, i, holdings, day_number):
        if self.scores is None:
            value = self.factor.builder(FactorContext(panel, i))
            if not isinstance(value, pd.Series) or value.index.has_duplicates or set(value.index) - set(panel.symbols):
                raise ValueError("因子builder必须返回无重复、代码合法的Series")
            values = value.reindex(panel.symbols).to_numpy(float) * self.factor.direction
        else:
            values = self.scores[i]
        eligible = eligible_mask(panel, i, self.pool) & np.isfinite(values)
        emergency = any(not eligible[j] for j in holdings)
        if day_number % self.spec.every and not emergency:
            return None, {"rebalance": False, "eligible": int(eligible.sum())}
        ranked = sorted(np.flatnonzero(eligible), key=lambda j: (-values[j], panel.symbols[j]))
        if day_number % self.spec.every:
            ranked = [j for j in ranked if j in holdings]
        chosen = ranked[:self.spec.top_n]
        return {j: self.spec.weight / self.spec.top_n for j in chosen}, {"rebalance": True, "eligible": int(eligible.sum())}
