from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class Tick:
    date: pd.Timestamp
    phase: str


class SimClock:
    """每个交易日先开盘撮合、后收盘决策；没有真实等待。"""

    def __init__(self, dates):
        self.dates = pd.DatetimeIndex(dates).copy()
        if self.dates.has_duplicates or not self.dates.is_monotonic_increasing:
            raise ValueError("模拟时钟需要不重复、递增的交易日")

    def __iter__(self):
        for date in self.dates:
            yield Tick(date, "OPEN")
            yield Tick(date, "CLOSE")
