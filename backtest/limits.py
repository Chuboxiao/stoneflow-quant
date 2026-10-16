from __future__ import annotations

import math
from pathlib import Path
import pandas as pd
from .models import PriceLimits


class LimitPolicy:
    """strict 缺资料拒绝交易；conservative 为明确标注的五个百分点代理保护。"""

    def __init__(self, mode="strict", limits: pd.DataFrame | None = None):
        if mode not in {"strict", "conservative"}:
            raise ValueError("未知涨跌停模式")
        self.mode = mode
        self._rows = {}
        if limits is not None:
            required = {"date", "symbol", "upper_limit", "lower_limit", "no_limit", "suspended"}
            if not required.issubset(limits.columns):
                raise ValueError(f"涨跌停文件需要列：{sorted(required)}")
            for row in limits.to_dict("records"):
                date, symbol = pd.Timestamp(row["date"]), str(row["symbol"])
                key = (date, symbol)
                if pd.isna(date) or date != date.normalize() or key in self._rows:
                    raise ValueError("涨跌停日期无效或 date,symbol 重复")
                for flag in ("no_limit", "suspended"):
                    if row[flag] not in (0, 1, False, True):
                        raise ValueError(f"{flag} 必须是 0 或 1")
                no_limit, suspended = bool(row["no_limit"]), bool(row["suspended"])
                if no_limit or suspended:
                    upper = lower = None
                else:
                    upper, lower = float(row["upper_limit"]), float(row["lower_limit"])
                    if not (math.isfinite(upper) and math.isfinite(lower) and upper >= lower > 0):
                        raise ValueError("涨跌停价必须为有限正数且涨停价不低于跌停价")
                self._rows[key] = PriceLimits(upper, lower, "external_exact", suspended=suspended)

    @classmethod
    def from_csv(cls, path: str | Path | None, mode="strict"):
        frame = pd.read_csv(path, dtype={"symbol": str}) if path else None
        return cls(mode, frame)

    def get(self, date, symbol, market):
        key = (pd.Timestamp(date), symbol)
        if key in self._rows:
            return self._rows[key]
        if self.mode == "strict":
            return PriceLimits(None, None, "missing_exact", known=False)
        ref = market.previous_reference(date, symbol)
        if not market.positive(ref):
            return PriceLimits(None, None, "missing_reference", known=False)
        # 向内保留一分钱：比常见 5% 限制更保守，并非官方涨跌停价。
        upper = max(0.01, (math.floor(ref * 1.05 * 100 + 1e-8) - 1) / 100)
        lower = (math.ceil(ref * 0.95 * 100 - 1e-8) + 1) / 100
        return PriceLimits(upper, lower, "proxy_5pct_inward_1tick")
