from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FeeModel:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_bps: float = 5.0

    def __post_init__(self):
        for x in (self.commission_rate, self.minimum_commission, self.slippage_bps):
            if not math.isfinite(x) or x < 0:
                raise ValueError("费用和滑点必须为有限的非负数")
        if self.commission_rate >= 1 or self.slippage_bps >= 10000:
            raise ValueError("佣金率必须小于 1，滑点必须小于 10000 bps")

    def fees(self, notional: float, side: str, date) -> tuple[float, float]:
        if notional <= 0:
            return 0.0, 0.0
        commission = round(max(self.minimum_commission, notional * self.commission_rate), 2)
        # 课程范围内股票卖方印花税；2023-08-28 起减半。
        rate = 0.001 if str(date)[:10] < "2023-08-28" else 0.0005
        stamp = round(notional * rate, 2) if side == "SELL" else 0.0
        return commission, stamp


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    lot_size: int = 100
    limit_mode: str = "strict"
    trading_days_per_year: int = 252

    def __post_init__(self):
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("初始资金必须为有限正数")
        if not isinstance(self.lot_size, int) or self.lot_size < 1:
            raise ValueError("lot_size 必须为正整数")
        if self.limit_mode not in {"strict", "conservative"}:
            raise ValueError("limit_mode 只能为 strict 或 conservative")
        if self.trading_days_per_year <= 0:
            raise ValueError("年交易日数必须为正数")


@dataclass
class Order:
    order_id: int
    signal_date: str
    execution_date: str
    symbol: str
    side: str
    requested_raw_equivalent_qty: float
    filled_raw_equivalent_qty: float = 0.0
    filled_adjusted_units: float = 0.0
    raw_execution_price: float | None = None
    adjusted_execution_price: float | None = None
    notional: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    status: str = "REJECTED"
    reason: str = ""
    limit_source: str = ""


@dataclass(frozen=True)
class PriceLimits:
    upper: float | None
    lower: float | None
    source: str
    known: bool = True
    suspended: bool = False
