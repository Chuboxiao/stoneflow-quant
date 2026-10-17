"""Stateful, full-universe breakout strategies using the public close callback.

No future rows, no order-fill assumptions and no daily equal-weight rebalance.
Exit intents survive rejected/partial sells until the actual position is flat.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class BreakoutSpec:
    key: str
    title: str
    entry_days: int = 20
    exit_days: int = 10
    max_positions: int = 20
    max_weight: float = .95
    amount_multiplier: float = 0
    min_amount: float = 0
    min_price: float = 0
    trend_filter: bool = False
    atr_risk: float = 0
    atr_stop: float = 0


SPECS = (
    BreakoutSpec("base", "普通20日突破"),
    BreakoutSpec("confirmed", "突破 + 成交额确认", amount_multiplier=1.5),
    BreakoutSpec("liquid", "确认 + 流动性过滤", amount_multiplier=1.5, min_amount=20_000_000, min_price=3),
    BreakoutSpec("trend", "确认 + 流动性 + 趋势", amount_multiplier=1.5, min_amount=20_000_000, min_price=3, trend_filter=True),
    BreakoutSpec("defensive", "趋势 + ATR仓位与退出", amount_multiplier=1.5, min_amount=20_000_000, min_price=3,
                 trend_filter=True, atr_risk=.001, atr_stop=3),
)


class PoolBreakout:
    def __init__(self, spec):
        self.spec = spec
        self.exiting = set()
        self.peaks = {}

    def on_close(self, context):
        s = self.spec
        # Public context returns copies ending at the signal close.
        close = context.history("close", max(61, s.entry_days+1), True)
        high = context.history("high", max(15, s.entry_days+1), True)
        low = context.history("low", max(15, s.exit_days+1), True)
        amount = context.history("amt", 21, False)
        trades = context.history("num_trades", 1, False).iloc[-1].to_numpy()
        raw = context.history("close", 1, False).iloc[-1].to_numpy()
        st = context.states("isST", 1).iloc[-1].to_numpy()
        status = context.states("tradestatus", 1).iloc[-1].to_numpy()
        symbols = context.symbols
        latest = close.iloc[-1].to_numpy()
        prior_high = high.iloc[-s.entry_days-1:-1].max().to_numpy()
        prior_low = low.iloc[-s.exit_days-1:-1].min().to_numpy()
        valid_high = high.iloc[-s.entry_days-1:-1].notna().sum().to_numpy() == s.entry_days
        valid_low = low.iloc[-s.exit_days-1:-1].notna().sum().to_numpy() == s.exit_days
        holdings = {name: qty for name, qty in context.positions.items() if qty > 1e-8}
        self.exiting.intersection_update(holdings)
        self.peaks = {name: value for name, value in self.peaks.items() if name in holdings}
        # ATR uses 14 adjusted true ranges, including the signal day.
        atr = np.full(len(symbols), np.nan)
        if len(close) >= 15 and len(high) >= 14 and len(low) >= 14:
            h, l = high.iloc[-14:].to_numpy(), low.iloc[-14:].to_numpy()
            prev = close.iloc[-15:-1].to_numpy()
            tr = np.maximum(h-l, np.maximum(np.abs(h-prev), np.abs(l-prev)))
            atr = np.mean(tr, axis=0)
        for j, name in enumerate(symbols):
            if name not in holdings:
                continue
            if np.isfinite(latest[j]):
                self.peaks[name] = max(self.peaks.get(name, latest[j]), latest[j])
            risk = st[j] != 0 or not np.isfinite(latest[j])
            channel_exit = valid_low[j] and latest[j] < prior_low[j]
            atr_exit = (s.atr_stop > 0 and np.isfinite(atr[j]) and
                        latest[j] < self.peaks.get(name, latest[j])-s.atr_stop*atr[j])
            if risk or channel_exit or atr_exit:
                self.exiting.add(name)
        valid = ((st == 0) & (status == 1) & valid_high & np.isfinite(latest) & (latest > prior_high)
                 & (raw >= s.min_price) & (amount.iloc[-1].to_numpy() > 0) & (trades > 0))
        # Same minimum history as the execution gate; do not let new listings take slots.
        valid &= close.notna().sum().to_numpy() >= 60
        mean_amount = amount.iloc[-21:-1].mean().to_numpy()
        valid &= (amount.iloc[-21:-1].notna().sum().to_numpy() == 20) & (mean_amount >= s.min_amount)
        if s.amount_multiplier:
            valid &= amount.iloc[-1].to_numpy() > mean_amount*s.amount_multiplier
        if s.trend_filter:
            ma20, ma60 = close.iloc[-20:].mean().to_numpy(), close.iloc[-60:].mean().to_numpy()
            valid &= close.iloc[-60:].notna().all().to_numpy() & (latest > ma60) & (ma20 > ma60)
        if s.atr_risk:
            valid &= np.isfinite(atr) & (atr > 0)
        ranked = sorted((j for j in np.flatnonzero(valid) if symbols[j] not in holdings),
                        key=lambda j: (-latest[j]/prior_high[j], symbols[j]))
        # Failed exits still occupy slots. Never assume a sale will fund an entry.
        slots = max(0, s.max_positions-len(holdings))
        weights = {}
        for j, name in enumerate(symbols):
            if name in holdings and name not in self.exiting and np.isfinite(raw[j]) and raw[j] > 0:
                # Epsilon avoids an accidental lot loss from floating-point division.
                weights[name] = (holdings[name]+1e-8)*raw[j]/context.equity
        # Preserve existing shares; reserve cash and do not top up partial entries.
        # Equity-cash includes stale marks and unpaid dividends; neither funds a buy.
        retained_value = max(0, 1-context.cash/context.equity)
        budget = max(0, s.max_weight-retained_value)
        added = 0
        for j in ranked[:slots]:
            weight = s.max_weight/s.max_positions
            if s.atr_risk:
                weight = min(weight, s.atr_risk/(atr[j]/latest[j]))
            weight = min(weight, budget)
            if weight <= 1e-10:
                break
            weights[symbols[j]] = weight
            budget -= weight
            added += 1
        if not self.exiting and not added:
            return None
        return weights
