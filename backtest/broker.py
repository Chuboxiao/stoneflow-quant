from __future__ import annotations

import math
from dataclasses import asdict
import pandas as pd
from .models import BacktestConfig, FeeModel, Order
from .limits import LimitPolicy

EPS = 1e-8


class SimBroker:
    """只做开盘撮合。持仓是复权单位，raw_equivalent_qty 不是登记持股数。"""

    def __init__(self, market, config: BacktestConfig, fees: FeeModel, limits: LimitPolicy):
        self.market, self.config, self.fees, self.limits = market, config, fees, limits
        self.cash = float(config.initial_cash)
        self.positions = {s: 0.0 for s in market.symbols}
        self._today_buys = {}
        self._marks = {}
        self._mark_dates = {}
        self.orders: list[Order] = []

    def mark(self, date, field):
        for symbol, units in self.positions.items():
            price = self.market.adjusted(field, date, symbol)
            if self.market.positive(price):
                self._marks[symbol] = price
                self._mark_dates[symbol] = f"{pd.Timestamp(date).date()} {field}"
            elif units > EPS and symbol not in self._marks:
                raise ValueError(f"{symbol} 有持仓但没有可用估值价格")
        return self.cash + sum(q * self._marks.get(s, 0.0) for s, q in self.positions.items())

    def _reject(self, order, reason):
        order.reason = reason
        self.orders.append(order)
        return order

    def trade(self, date, symbol, side, raw_quantity, signal_date=None):
        date = pd.Timestamp(date)
        if symbol not in self.positions or side not in {"BUY", "SELL"}:
            raise ValueError("证券代码或订单方向无效")
        if not math.isfinite(raw_quantity) or raw_quantity <= 0:
            raise ValueError("订单数量必须为有限正数")
        order = Order(len(self.orders) + 1, str(pd.Timestamp(signal_date or date).date()),
                      str(date.date()), symbol, side, float(raw_quantity))
        raw_open, scale = self.market.raw("open", date, symbol), self.market.scale(date, symbol)
        if not self.market.positive(raw_open) or not self.market.positive(scale):
            return self._reject(order, "UNAVAILABLE_OPEN_OR_FACTOR")
        # 日线事后可成交性否决：全天成交额为零证明当天没有任何成交。
        # 只否决成交，不给策略提供未来信息，不用正成交额决定开盘成交数量。
        amount = self.market.raw("amt", date, symbol)
        if not self.market.positive(amount):
            return self._reject(order, "ZERO_OR_MISSING_DAILY_AMOUNT")
        bounds = self.limits.get(date, symbol, self.market)
        order.limit_source = bounds.source
        if not bounds.known:
            return self._reject(order, "MISSING_PRICE_LIMITS")
        if bounds.suspended:
            return self._reject(order, "SUSPENDED")
        if side == "BUY" and bounds.upper is not None and raw_open >= bounds.upper - EPS:
            return self._reject(order, "LIMIT_UP_OR_CONSERVATIVE_GUARD")
        if side == "SELL" and bounds.lower is not None and raw_open <= bounds.lower + EPS:
            return self._reject(order, "LIMIT_DOWN_OR_CONSERVATIVE_GUARD")
        # 拒绝落在外部精确价格区间外的异常开盘数据，避免错误成交。
        if bounds.source == "external_exact" and (
                (bounds.upper is not None and raw_open > bounds.upper + EPS) or
                (bounds.lower is not None and raw_open < bounds.lower - EPS)):
            return self._reject(order, "OPEN_OUTSIDE_LIMIT_RANGE")
        slip = self.fees.slippage_bps / 10000
        if side == "BUY":
            raw_price = math.ceil(raw_open * (1 + slip) * 100 - EPS) / 100
        else:
            raw_price = math.floor(raw_open * (1 - slip) * 100 + EPS) / 100
        if raw_price <= 0:
            return self._reject(order, "INVALID_EXECUTION_PRICE")
        if ((side == "BUY" and bounds.upper is not None and raw_price > bounds.upper + EPS) or
                (side == "SELL" and bounds.lower is not None and raw_price < bounds.lower - EPS)):
            return self._reject(order, "SLIPPAGE_OUTSIDE_LIMIT_RANGE")
        lot = self.config.lot_size
        reduced_reason = ""
        if side == "BUY":
            affordable = max(0.0, min(self.cash - self.fees.minimum_commission,
                                      self.cash / (1 + self.fees.commission_rate)))
            qty = math.floor(min(raw_quantity, affordable / raw_price) / lot + EPS) * lot
            if qty <= 0:
                reason = "INSUFFICIENT_CASH" if affordable / raw_price < lot else "BELOW_MINIMUM_LOT"
                return self._reject(order, reason)
            while qty > 0:
                commission, stamp = self.fees.fees(qty * raw_price, side, date)
                if qty * raw_price + commission <= self.cash + EPS:
                    break
                qty -= lot
            if qty <= 0:
                return self._reject(order, "INSUFFICIENT_CASH")
            if qty < raw_quantity - EPS:
                reduced_reason = "CASH_OR_LOT_ROUNDING"
        else:
            locked = self._today_buys.get((date, symbol), 0.0)
            available_units = max(0.0, self.positions[symbol] - locked)
            available_raw = available_units * scale
            if available_raw <= EPS:
                return self._reject(order, "T_PLUS_ONE_OR_NO_POSITION")
            if raw_quantity >= self.positions[symbol] * scale - EPS and locked <= EPS:
                qty = available_raw  # 允许全部清仓，包括复权单位模型中的等价零股。
            else:
                qty = math.floor(min(raw_quantity, available_raw) / lot + EPS) * lot
            if qty <= EPS:
                return self._reject(order, "BELOW_MINIMUM_LOT_OR_T_PLUS_ONE")
            if qty < raw_quantity - EPS:
                reduced_reason = "POSITION_T_PLUS_ONE_OR_LOT_ROUNDING"
            commission, stamp = self.fees.fees(qty * raw_price, side, date)
            if self.cash + qty * raw_price < commission + stamp - EPS:
                return self._reject(order, "INSUFFICIENT_CASH_FOR_FEES")
        notional = qty * raw_price
        units = qty / scale
        if side == "BUY":
            self.cash -= notional + commission + stamp
            self.positions[symbol] += units
            key = (date, symbol)
            self._today_buys[key] = self._today_buys.get(key, 0.0) + units
        else:
            self.cash += notional - commission - stamp
            self.positions[symbol] = max(0.0, self.positions[symbol] - units)
        if self.cash < -EPS:
            raise ArithmeticError("现金变为负数，账户约束失效")
        if abs(self.cash) < EPS:
            self.cash = 0.0
        order.filled_raw_equivalent_qty = float(qty)
        order.filled_adjusted_units = float(units)
        order.raw_execution_price = raw_price
        order.adjusted_execution_price = raw_price * scale
        order.notional, order.commission, order.stamp_tax = notional, commission, stamp
        order.status = "FILLED" if abs(qty - raw_quantity) <= EPS else "PARTIAL"
        order.reason = reduced_reason or "FILLED"
        self.orders.append(order)
        return order

    def rebalance(self, date, signal_date, weights):
        equity = self.mark(date, "open")
        gaps = {}
        for symbol in self.market.symbols:
            target = weights.get(symbol, 0.0) * equity
            price = self.market.adjusted("open", date, symbol)
            if self.market.positive(price):
                gaps[symbol] = target - self.positions[symbol] * price
            elif self.positions[symbol] > EPS or target > EPS:
                # 记录失败意图，不能将缺失开盘价前向填充后假成交。
                side = "SELL" if target <= EPS else "BUY"
                self.trade(date, symbol, side, float(self.config.lot_size), signal_date)
        # 固定按代码排序，使结果不依赖用户输入证券顺序；先卖后买。
        for side in ("SELL", "BUY"):
            for symbol in sorted(gaps):
                gap = gaps[symbol]
                if (side == "SELL" and gap >= -EPS) or (side == "BUY" and gap <= EPS):
                    continue
                raw = self.market.raw("open", date, symbol)
                self.trade(date, symbol, side, abs(gap) / raw, signal_date)

    def position_rows(self, date, equity):
        rows = []
        for symbol, units in self.positions.items():
            raw_close = self.market.raw("close", date, symbol)
            scale = self.market.scale(date, symbol)
            price = self._marks.get(symbol, 0.0)
            fresh = self.market.positive(self.market.adjusted("close", date, symbol))
            value = units * price
            rows.append({
                "date": str(pd.Timestamp(date).date()), "symbol": symbol,
                "adjusted_units": units,
                "raw_equivalent_qty": units * scale if self.market.positive(scale) else None,
                "raw_close": raw_close if self.market.positive(raw_close) else None,
                "adjusted_mark": price, "market_value": value,
                "weight": value / equity if equity > 0 else None,
                "stale_valuation": bool(units > EPS and not fresh),
                "mark_as_of": self._mark_dates.get(symbol, ""),
            })
        return rows

    def order_rows(self):
        return [asdict(x) for x in self.orders]
