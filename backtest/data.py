from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

FIELDS = ("open", "high", "low", "close", "amt", "num_trades", "cumadj")


class MarketData:
    """原始价格不填充；复权单位价格 = 原价 × 当日因子 / 固定基准因子。"""

    def __init__(self, frames: dict[str, pd.DataFrame], source: str = "in-memory"):
        if set(frames) != set(FIELDS):
            raise ValueError(f"需要七个字段：{FIELDS}")
        self._frames = {k: v.copy(deep=True) for k, v in frames.items()}
        base = self._frames["close"]
        if base.empty or base.columns.has_duplicates:
            raise ValueError("证券数据为空或证券列重复")
        if not isinstance(base.index, pd.DatetimeIndex):
            raise ValueError("日期必须是 DatetimeIndex")
        if base.index.tz is not None or base.index.hasnans:
            raise ValueError("交易日期必须是无时区、非缺失日期")
        if base.index.has_duplicates or not base.index.is_monotonic_increasing:
            raise ValueError("交易日必须严格递增且不重复")
        if not base.index.equals(base.index.normalize()):
            raise ValueError("日频数据的日期必须归一到午夜")
        for name, frame in self._frames.items():
            if not frame.index.equals(base.index) or not frame.columns.equals(base.columns):
                raise ValueError(f"{name} 的日期或证券顺序与 close 不一致")
            self._frames[name] = frame.astype(float)
        self.dates = base.index.copy()
        self.symbols = tuple(str(x) for x in base.columns)
        self.source = source
        self._locations = {date: i for i, date in enumerate(self.dates)}
        self.reference_factors = {}
        for symbol in self.symbols:
            factor = self._frames["cumadj"][symbol]
            valid = factor[np.isfinite(factor) & (factor > 0)]
            if valid.empty:
                raise ValueError(f"{symbol} 没有有效累计复权因子")
            self.reference_factors[symbol] = float(valid.iloc[0])

    @classmethod
    def from_feather(cls, directory, symbols):
        directory = Path(directory).expanduser().resolve()
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("请提供不重复的证券代码")
        frames = {}
        for field in FIELDS:
            path = directory / f"{field}.feather"
            if not path.is_file():
                raise FileNotFoundError(path)
            try:
                df = pd.read_feather(path, columns=["date", *symbols])
            except Exception as exc:
                raise ValueError(f"无法读取 {path.name}；请检查证券代码及 pyarrow：{exc}") from exc
            df["date"] = pd.to_datetime(df["date"], errors="raise")
            frames[field] = df.set_index("date").loc[:, list(symbols)]
        return cls(frames, str(directory))

    def raw(self, field, date, symbol) -> float:
        return float(self._frames[field].at[pd.Timestamp(date), symbol])

    @staticmethod
    def positive(value):
        return bool(np.isfinite(value) and value > 0)

    def scale(self, date, symbol) -> float:
        factor = self.raw("cumadj", date, symbol)
        return factor / self.reference_factors[symbol] if self.positive(factor) else np.nan

    def adjusted(self, field, date, symbol) -> float:
        price, scale = self.raw(field, date, symbol), self.scale(date, symbol)
        return price * scale if self.positive(price) and self.positive(scale) else np.nan

    def previous_reference(self, date, symbol) -> float:
        """近似当日除权参考前收，不能替代交易所官方涨跌停价。"""
        i = self._locations[pd.Timestamp(date)]
        if i == 0:
            return np.nan
        prev = self.dates[i - 1]
        p, a, b = (self.raw("close", prev, symbol),
                   self.raw("cumadj", prev, symbol), self.raw("cumadj", date, symbol))
        return p * a / b if all(self.positive(x) for x in (p, a, b)) else np.nan

    def history(self, as_of, field="close", lookback=None, adjusted=False):
        if field not in FIELDS:
            raise ValueError(f"未知字段：{field}")
        end = self._locations[pd.Timestamp(as_of)] + 1
        if lookback is not None and (not isinstance(lookback, int) or lookback < 1):
            raise ValueError("lookback 必须为正整数")
        start = max(0, end - lookback) if lookback is not None else 0
        frame = self._frames[field].iloc[start:end].copy(deep=True)
        if adjusted:
            if field not in {"open", "high", "low", "close"}:
                raise ValueError("只对价格复权，不能给成交额或成交笔数乘复权因子")
            factors = self._frames["cumadj"].iloc[start:end]
            frame = frame.where(frame > 0) * factors.where(factors > 0)
            frame = frame.div(pd.Series(self.reference_factors), axis="columns")
        return frame

    def common_first_date(self):
        valid = self._frames["close"].gt(0) & self._frames["cumadj"].gt(0)
        dates = self.dates[valid.all(axis=1)]
        if dates.empty:
            raise ValueError("所选证券没有共同有效日期")
        return dates[0]

    def audit(self):
        return {
            "source": self.source, "rows": len(self.dates), "symbols": list(self.symbols),
            "first_date": str(self.dates[0].date()), "last_date": str(self.dates[-1].date()),
            "reference_factors": self.reference_factors,
            "missing_values": {k: int(v.isna().sum().sum()) for k, v in self._frames.items()},
            "first_valid_close": {s: str(self._frames["close"][s].first_valid_index().date())
                                  if self._frames["close"][s].first_valid_index() is not None else None
                                  for s in self.symbols},
        }
