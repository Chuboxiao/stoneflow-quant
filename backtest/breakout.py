"""可编程策略示例：根据真实持仓作状态判断，不是固定参数公式模板。"""
import numpy as np


class BreakoutStrategy:
    def __init__(self, entry_days=20, exit_days=10, amount_multiplier=None, weight=0.98):
        self.entry_days, self.exit_days = entry_days, exit_days
        self.amount_multiplier, self.weight = amount_multiplier, weight

    def on_close(self, context):
        if len(context.symbols)!=1:
            raise ValueError("突破策略使用独立子账户，每次只加载一只股票")
        symbol = context.symbols[0]
        close = context.history("close",1,True).iloc[-1,slice(None)][symbol]
        amount = context.history("amt",self.entry_days+1,False)[symbol]
        if not np.isfinite(close) or len(amount)<self.entry_days+1 or not amount.iloc[-1]>0:
            return None
        holding = context.positions[symbol]>1e-8
        if holding:
            lows = context.history("low",self.exit_days+1,True)[symbol].iloc[:-1]
            if len(lows)==self.exit_days and np.isfinite(lows).all() and close < lows.min():
                return {}  # 下一交易日尝试清仓；失败后仍按实际持仓判断。
            return None  # 不每天重置仓位，保持已买入的单位数。
        highs = context.history("high",self.entry_days+1,True)[symbol].iloc[:-1]
        if len(highs)!=self.entry_days or not np.isfinite(highs).all() or close<=highs.max():
            return None
        if self.amount_multiplier is not None:
            previous = amount.iloc[:-1]
            if not np.isfinite(previous).all() or amount.iloc[-1]<=previous.mean()*self.amount_multiplier:
                return None
        return {symbol:self.weight}


class BuyAndHold:
    def __init__(self, weight=0.98): self.weight=weight
    def on_close(self, context):
        symbol=context.symbols[0]
        if context.positions[symbol]>1e-8: return None
        return {symbol:self.weight}
