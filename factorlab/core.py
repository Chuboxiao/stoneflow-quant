"""Cross-sectional diagnostics. Forward labels are quotes, never assumed fills.

Custom builders receive only copies of history ending at the signal close.
Unknown/ST names are removed at that close, never by their future status.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import re
import numpy as np
import pandas as pd


class FactorContext:
    def __init__(self, panel, location):
        self.__panel, self.__location = panel, location
        self.date = panel.dates[location]
        self.symbols = panel.symbols

    def history(self, field="close", lookback=21, adjusted=True):
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
            raise ValueError("lookback必须为正整数")
        if field not in self.__panel.frames:
            raise ValueError("未知行情字段")
        start, stop = max(0, self.__location + 1 - lookback), self.__location + 1
        data = self.__panel.frames[field].iloc[start:stop].copy(deep=True)
        if adjusted:
            if field not in {"open", "high", "low", "close"}:
                raise ValueError("仅价格字段可复权；成交额不能乘cumadj")
            data = data.where(data > 0) * self.__panel.frames["cumadj"].iloc[start:stop].where(lambda x: x > 0)
        return data


@dataclass(frozen=True)
class FactorSpec:
    key: str
    title: str
    description: str
    lookback: int
    builder: Callable
    # Prespecified direction: never flipped after seeing IC.
    direction: int = 1

    def __post_init__(self):
        if (not isinstance(self.key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}',self.key)
                or isinstance(self.direction,bool) or self.direction not in (-1, 1)
                or isinstance(self.lookback,bool) or not isinstance(self.lookback,int)
                or self.lookback < 1 or not callable(self.builder)):
            raise ValueError("无效因子定义")


def reversal5(ctx):
    h = ctx.history(lookback=6)
    return -(h.iloc[-1] / h.iloc[0] - 1)


def momentum20(ctx):
    h = ctx.history(lookback=21)
    return h.iloc[-1] / h.iloc[0] - 1


def breakout20(ctx):
    return ctx.history(lookback=1).iloc[-1] / ctx.history("high", 21).iloc[:-1].max(skipna=False) - 1


def amount20(ctx):
    h = ctx.history("amt", 21, adjusted=False)
    return h.iloc[-1] / h.iloc[:-1].mean(skipna=False) - 1


def lowvol20(ctx):
    h = ctx.history(lookback=21)
    return -h.pct_change(fill_method=None).iloc[1:].std(ddof=1,skipna=False)


REGISTRY = {
    spec.key: spec for spec in (
        FactorSpec("reversal5", "5DR · 五日反转", "−(复权收盘价 / 5日前复权收盘价 − 1)，分数越高表示近期跌幅越大。", 6, reversal5),
        FactorSpec("momentum20", "20日动量", "复权收盘价 / 20日前复权收盘价 − 1；预设正向。", 21, momentum20),
        FactorSpec("breakout20", "20日突破幅度", "复权收盘价 / 此前20日最高复权high − 1；高点窗口不含今天。", 21, breakout20),
        FactorSpec("amount20", "成交额放大", "当日成交额 / 此前20日平均成交额 − 1；预设正向，不代表已证实有效。", 21, amount20),
        FactorSpec("lowvol20", "20日低波动", "过去20个单日复权收益的样本标准差取负数；预设低波动高分。", 21, lowvol20),
    )
}


def compute_scores(panel, spec, start=None, end=None):
    result = np.full(panel.adjusted.shape, np.nan)
    for i, date in enumerate(panel.dates):
        if i + 1 < spec.lookback or (start and date < pd.Timestamp(start)) or (end and date > pd.Timestamp(end)):
            continue
        values = spec.builder(FactorContext(panel, i))
        if not isinstance(values, pd.Series) or values.index.has_duplicates:
            raise ValueError("因子builder必须返回以证券代码为索引的Series，不允许重复代码")
        if set(values.index) - set(panel.symbols):
            raise ValueError("因子包含股票池外的证券代码")
        result[i] = pd.to_numeric(values.reindex(panel.symbols), errors="raise").to_numpy(float) * spec.direction
    result[~np.isfinite(result)] = np.nan
    return result


def load_factor_csv(path, panel, direction=1):
    """Explicitly supplied long CSV: date,symbol,value, known at that close.

    Imported values cannot be proven causal; this is recorded in the report.
    Missing cells stay missing; duplicates/unknown dates and codes fail closed.
    """
    if direction not in (-1, 1):
        raise ValueError("direction只能为1或−1")
    frame = pd.read_csv(path, dtype={"symbol": str})
    if set(frame.columns) != {"date", "symbol", "value"} or frame.empty:
        raise ValueError("CSV必须且仅包含date,symbol,value三列，并包含数据")
    frame["date"] = pd.to_datetime(frame.date, errors="raise")
    frame["value"] = pd.to_numeric(frame.value, errors="raise")
    if (frame.duplicated(["date", "symbol"]).any() or frame.date.isna().any()
            or frame.symbol.isna().any() or not np.isfinite(frame.value).all()):
        raise ValueError("CSV有重复记录、缺失键或非有限数值")
    if set(frame.symbol) - set(panel.symbols) or not frame.date.isin(panel.dates).all():
        raise ValueError("CSV含行情中不存在的证券或交易日")
    return (frame.pivot(index="date", columns="symbol", values="value")
            .reindex(index=panel.dates, columns=panel.symbols).to_numpy(float) * direction)


def eligible_mask(panel, i, pool="base"):
    if pool not in ("base", "liquid"):
        raise ValueError("未知股票池")
    a = panel.arrays
    valid = ((panel.states["isST"][i] == 0) & (panel.states["tradestatus"][i] == 1)
             & (panel.age[i] >= 60) & panel.valid20[i]
             & (a["amt"][i] > 0) & (a["num_trades"][i] > 0)
             & np.isfinite(panel.mean_amt[i]))
    if pool == "liquid":
        valid &= (panel.mean_amt[i] >= 20_000_000) & (a["close"][i] >= 3)
    return valid


def correlation(x, y, ranked=False):
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[mask], np.asarray(y)[mask]
    if len(x) < 3:
        return np.nan
    if ranked:
        x, y = pd.Series(x).rank(method="average").to_numpy(), pd.Series(y).rank(method="average").to_numpy()
    x, y = x - x.mean(), y - y.mean()
    denominator = np.linalg.norm(x) * np.linalg.norm(y)
    return float(np.dot(x, y) / denominator) if denominator > 1e-15 else np.nan


def quantile_groups(values, count=5):
    """Equal values stay together; never manufacture monotonicity by ticker ties."""
    groups = np.zeros(len(values), dtype=int)
    mask = np.isfinite(values)
    if mask.sum() and np.unique(values[mask]).size >= count:
        rank = pd.Series(values[mask]).rank(method="average").to_numpy()
        groups[mask] = np.minimum(count, np.floor((rank - .5) / mask.sum() * count).astype(int) + 1)
    return groups


def ic_statistics(values, horizon):
    values = np.asarray(values, float)
    good = np.isfinite(values)
    n = int(good.sum())
    if not n:
        return {"observations": 0, "mean": None, "std": None, "icir": None,
                "positive_fraction": None, "hac_t": None, "hac_lags": 0}
    mean = float(values[good].mean())
    std = float(values[good].std(ddof=1)) if n > 1 else np.nan
    # Bartlett/Newey-West mean variance, retaining missing calendar locations.
    lags = min(len(values) - 1, max(horizon - 1, 5))
    centered = np.where(good, values - mean, 0.)
    long_variance = float(np.dot(centered, centered) / n)
    for lag in range(1, lags + 1):
        long_variance += 2 * (1 - lag / (lags + 1)) * float(np.dot(centered[lag:], centered[:-lag]) / n)
    se = np.sqrt(max(0., long_variance) / n)
    return {"observations": n, "mean": mean, "std": std if np.isfinite(std) else None,
            "icir": mean / std if std > 1e-15 else None,
            "positive_fraction": float((values[good] > 0).mean()),
            "hac_t": float(mean / se) if se > 1e-15 and n >= 20 else None, "hac_lags": lags}


def forward_labels(panel, i, horizon, cutoff):
    """Signal close t -> open t+1 -> open t+1+h; never read beyond cutoff."""
    n = len(panel.symbols)
    entry, exit_ = i + 1, i + 1 + horizon
    if exit_ >= len(panel.dates) or panel.dates[exit_] > pd.Timestamp(cutoff):
        return np.full(n, np.nan), None, None
    a = panel.arrays
    first, last = a["open"][entry] * a["cumadj"][entry], a["open"][exit_] * a["cumadj"][exit_]
    observable = (np.isfinite(first) & np.isfinite(last) & (first > 0) & (last > 0)
                  & (a["amt"][entry] > 0) & (a["amt"][exit_] > 0)
                  & (panel.states["tradestatus"][entry] == 1) & (panel.states["tradestatus"][exit_] == 1))
    labels = np.full(n, np.nan)
    labels[observable] = last[observable] / first[observable] - 1
    return labels, str(panel.dates[entry].date()), str(panel.dates[exit_].date())


def evaluate(panel, scores, start, end, pool="base", horizons=(1, 5, 10, 20), quantiles=5, min_names=30):
    if scores.shape != panel.adjusted.shape:
        raise ValueError("因子矩阵必须和行情日期、证券严格对齐")
    if not 2 <= quantiles <= 10 or min_names < quantiles * 2:
        raise ValueError("分组数量或最小横截面样本数无效")
    if not horizons or any(isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= 60 for h in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError("预测期限必须为1至60内的不重复整数")
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("起止日期顺序错误")
    locs = np.flatnonzero((panel.dates >= pd.Timestamp(start)) & (panel.dates <= pd.Timestamp(end)))
    if len(locs) < 2:
        raise ValueError("评价区间至少需要两个交易日")
    daily, coverage, previous_top, previous_scores = [], [], None, None
    for i in locs:
        date = str(panel.dates[i].date())
        eligible = eligible_mask(panel, i, pool)
        raw = scores[i].copy()
        raw[~eligible] = np.nan
        finite = np.isfinite(raw)
        clean = raw.copy()
        # Same-date only: no future-outcome filtering or full-sample scaling.
        if finite.any():
            lower, upper = np.quantile(raw[finite], [.01, .99])
            clean[finite] = np.clip(raw[finite], lower, upper)
        groups = quantile_groups(clean, quantiles) if finite.sum() >= min_names else np.zeros(len(raw), int)
        top = set(np.flatnonzero(groups == quantiles))
        turnover = 1 - len(top & previous_top) / len(previous_top) if previous_top and top else None
        persistence = correlation(clean, previous_scores, True) if previous_scores is not None else np.nan
        coverage.append({"date": date, "eligible": int(eligible.sum()), "factor_valid": int(finite.sum()),
                         "factor_coverage": float(finite.sum() / eligible.sum()) if eligible.any() else None,
                         "unique_values": int(np.unique(raw[finite]).size), "grouped": int((groups > 0).sum()),
                         "top_turnover": turnover, "rank_autocorrelation": persistence,
                         "unknown_st_active": int(((panel.arrays['amt'][i] > 0) & ~np.isin(panel.states['isST'][i], [0, 1])).sum())})
        previous_top, previous_scores = top, clean
        for h in horizons:
            labels, entry, exit_ = forward_labels(panel, i, h, end)
            paired = finite & np.isfinite(labels)
            can_ic = paired.sum() >= min_names
            means, counts, selected_counts = [], [], []
            for q in range(1, quantiles + 1):
                selected = groups == q
                observed = selected & np.isfinite(labels)
                means.append(float(labels[observed].mean()) if observed.any() else None)
                counts.append(int(observed.sum())); selected_counts.append(int(selected.sum()))
            spread = means[-1] - means[0] if means[-1] is not None and means[0] is not None else None
            mean_array = np.array([np.nan if x is None else x for x in means])
            daily.append({"date": date, "horizon": h, "entry_date": entry, "exit_date": exit_,
                          "eligible": int(eligible.sum()), "factor_valid": int(finite.sum()), "paired": int(paired.sum()),
                          "missing_labels": int(finite.sum() - paired.sum()), "endpoint_censored": entry is None,
                          "ic": correlation(clean[paired], labels[paired]) if can_ic else None,
                          "rank_ic": correlation(clean[paired], labels[paired], True) if can_ic else None,
                          "universe_return": float(labels[paired].mean()) if can_ic else None,
                          "group_returns": means, "group_observed": counts, "group_selected": selected_counts,
                          "spread": spread, "monotonicity": correlation(np.arange(1, quantiles + 1), mean_array, True),
                          "top_turnover": turnover})
    summaries, periods = [], []
    for h in horizons:
        block = [r for r in daily if r["horizon"] == h]
        rank_ic = ic_statistics([np.nan if r['rank_ic'] is None else r['rank_ic'] for r in block], h)
        means = [float(np.mean(v)) if (v := [r["group_returns"][q] for r in block if r["group_returns"][q] is not None]) else None for q in range(quantiles)]
        n_factor = sum(r["factor_valid"] for r in block if not r["endpoint_censored"])
        observed = sum(r["paired"] for r in block)
        spreads = [r['spread'] for r in block if r['spread'] is not None]
        summaries.append({"horizon": h, "rank_ic": rank_ic,
                          "pearson_ic": ic_statistics([np.nan if r['ic'] is None else r['ic'] for r in block], h),
                          "mean_group_returns": means, "mean_spread": float(np.mean(spreads)) if spreads else None,
                          "mean_monotonicity": float(np.nanmean([r['monotonicity'] for r in block])) if any(np.isfinite(r['monotonicity']) for r in block) else None,
                          "observed_labels": observed, "label_slots": n_factor,
                          "label_coverage": observed / n_factor if n_factor else None,
                          "endpoint_censored_dates": sum(r['endpoint_censored'] for r in block)})
        for frequency in (4, 7):
            for label in sorted({r["date"][:frequency] for r in block}):
                part = [r for r in block if r['date'].startswith(label)]
                periods.append({"period": label, "horizon": h, **ic_statistics([np.nan if r['rank_ic'] is None else r['rank_ic'] for r in part], h)})
    return {"pool": pool, "start": str(panel.dates[locs[0]].date()), "end": str(panel.dates[locs[-1]].date()),
            "signal_days": len(locs), "quantiles": quantiles, "min_names": min_names,
            "summary": summaries, "periods": periods, "coverage": coverage, "daily": daily}
