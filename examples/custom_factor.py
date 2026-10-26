"""Trusted local plugin example: --plugin examples/custom_factor.py --factors ''."""
from factorlab import FactorSpec


def ten_day_reversal(context):
    prices = context.history("close", lookback=11, adjusted=True)
    return -(prices.iloc[-1] / prices.iloc[0] - 1)


FACTOR = FactorSpec(
    key="reversal10", title="10日反转示例",
    description="过去10日复权收益率取负数；预设方向，不按评价期结果调整。",
    lookback=11, builder=ten_day_reversal,
)
