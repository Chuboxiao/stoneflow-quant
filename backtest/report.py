from __future__ import annotations

import html
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

NAMES = {"603950.SH": "长源东谷", "002230.SZ": "科大讯飞"}
REASONS = {
    "ZERO_OR_MISSING_DAILY_AMOUNT": "全天成交额为零或缺失，否决成交",
    "LIMIT_UP_OR_CONSERVATIVE_GUARD": "涨停或触发保守买入保护",
    "LIMIT_DOWN_OR_CONSERVATIVE_GUARD": "跌停或触发保守卖出保护",
    "MISSING_PRICE_LIMITS": "缺少精确涨跌停价或参考价",
    "UNAVAILABLE_OPEN_OR_FACTOR": "缺少开盘价或复权因子",
    "SUSPENDED": "外部资料标记停牌",
    "INSUFFICIENT_CASH": "可用现金不足",
    "BELOW_MINIMUM_LOT": "数量不足一手",
    "BELOW_MINIMUM_LOT_OR_T_PLUS_ONE": "不足一手或受到 T+1 限制",
    "SLIPPAGE_OUTSIDE_LIMIT_RANGE": "滑点后价格超过保护边界",
    "OPEN_OUTSIDE_LIMIT_RANGE": "开盘价与外部涨跌停资料不一致",
    "T_PLUS_ONE_OR_NO_POSITION": "无可卖持仓或受到 T+1 限制",
}


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def line_chart(series, dates, title, percent=False):
    colors = ["#2563eb", "#b45309", "#0f766e", "#7c3aed"]
    width, height = 1020, 310
    left, top, right, bottom = 72, 28, 22, 48
    plotw, ploth = width - left - right, height - top - bottom
    clean = [float(v) for _, values in series for v in values if pd.notna(v) and math.isfinite(v)]
    lo, hi = (min(clean), max(clean)) if clean else (0, 1)
    spread = hi - lo
    pad = spread * 0.08 if spread > 1e-10 else max(0.01, abs(lo) * 0.03)
    lo, hi = lo - pad, hi + pad
    chunks = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
              f'<title>{html.escape(title)}</title>']
    for i in range(5):
        value = lo + (hi - lo) * i / 4
        y = top + ploth - ploth * i / 4
        label = f"{value:.1%}" if percent else f"{value:.2f}"
        chunks.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        chunks.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end">{label}</text>')
    n = max(1, len(dates) - 1)
    for i in sorted(set([0, len(dates)//3, 2*len(dates)//3, len(dates)-1])):
        x = left + plotw * i / n
        anchor = "start" if i == 0 else ("end" if i == len(dates)-1 else "middle")
        chunks.append(f'<text x="{x:.1f}" y="{height-17}" text-anchor="{anchor}">{dates[i]}</text>')
    for j, (label, values) in enumerate(series):
        segments, current = [], []
        for i, v in enumerate(values):
            if pd.isna(v) or not math.isfinite(v):
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append(f"{left+plotw*i/n:.2f},{top+ploth*(hi-v)/(hi-lo):.2f}")
        if current:
            segments.append(current)
        for segment in segments:
            chunks.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{colors[j%len(colors)]}" stroke-width="2"/>')
    chunks.append('</svg><div class="legend">')
    for j, (label, _) in enumerate(series):
        chunks.append(f'<span><i style="background:{colors[j%len(colors)]}"></i>{html.escape(label)}</span>')
    chunks.append('</div>')
    return ''.join(chunks)


def export_result(result, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("equity", "orders", "positions", "signals"):
        getattr(result, name).to_csv(directory / f"{name}.csv", index=False, encoding="utf-8-sig")
    for name in ("metrics", "metadata"):
        (directory / f"{name}.json").write_text(
            json.dumps(json_safe(getattr(result, name)), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    m, meta, eq = result.metrics, result.metadata, result.equity
    symbols = meta["data_audit"]["symbols"]
    mode = meta["limit_mode"]
    if mode == "conservative":
        status = "教学演示：保守涨跌停代理过滤"
        context = "尚未提供精确历史涨跌停价。此结果用于验证系统流程，不代表已精确复现真实交易。"
    elif m["rejection_reasons"].get("MISSING_PRICE_LIMITS", 0):
        status = "严格模式：涨跌停资料不足，相关订单已拒绝"
        context = "没有用缺失资料假定成交。补充 daily_limits.csv 后可重新运行。"
    else:
        status = "使用外部涨跌停资料；成交仍采用日频教学模型"
        context = "外部资料的完整性和准确性由使用者提供；日线无法还原实际盘口排队。"
    def pct(x):
        return "不适用" if x is None else f"{x:.2%}"
    stats = [("期末总资产", f'{m["final_equity"]:,.2f} 元'),
             ("累计收益", pct(m["total_return"])), ("年化收益（252 日）", pct(m["annualized_return"])),
             ("最大回撤", pct(m["max_drawdown"])), ("成交订单", str(m["filled_orders"])),
             ("拒绝订单", str(m["rejected_orders"])), ("费用合计", f'{m["total_fees"]:,.2f} 元'),
             ("使用旧估值的交易日", str(m["stale_valuation_days"]))]
    stat_html = ''.join(f'<div class="stat"><small>{a}</small><strong>{b}</strong></div>' for a,b in stats)
    lines = [("普通突破组合（扣费）" if meta.get("comparison") else "账户净值（扣费）", eq["net_value"].tolist())]
    if meta.get("comparison"):
        for key,label in [("comparison_confirmed","成交额确认组合（扣费）"),("comparison_hold","买入持有组合（扣费）")]:
            lines.append((label,eq[key].tolist()))
    else:
        for s in symbols:
            lines.append((f'{NAMES.get(s,s)} 单股持有参考（未扣费）', eq[f"reference_{s}"].tolist()))
    chart = line_chart(lines, eq["date"].tolist(), "净值及单股持有参考")
    drawdown = line_chart([("账户回撤", eq["drawdown"].tolist())], eq["date"].tolist(), "账户回撤", True)
    orders = result.orders.copy()
    if not orders.empty:
        orders["reason"] = orders["reason"].map(lambda x: REASONS.get(x,x))
    filled = orders[orders["notional"] > 0]
    rejected = orders[orders["status"] == "REJECTED"]
    def table(frame, columns):
        if frame.empty:
            return '<p class="muted">没有相关记录。</p>'
        return frame.loc[:, list(columns)].tail(30).rename(columns=columns).to_html(
            index=False, border=0, classes="records", float_format=lambda x:f"{x:,.4f}", na_rep="—", escape=True)
    trade_table = table(filled, {"execution_date":"执行日期", "symbol":"证券代码", "side":"方向",
                               "filled_raw_equivalent_qty":"成交等价股数", "raw_execution_price":"原始成交价",
                               "notional":"成交额", "commission":"佣金", "stamp_tax":"印花税"})
    reject_table = table(rejected, {"execution_date":"执行日期", "symbol":"证券代码", "side":"方向", "reason":"未成交原因"})
    reason_html = ''.join(f'<li>{html.escape(REASONS.get(k,k))}：{v} 笔</li>' for k,v in m["rejection_reasons"].items()) or '<li>没有拒单。</li>'
    note_html = ''.join(f'<li>{html.escape(x)}</li>' for x in meta["notes"])
    names = '、'.join(f'{NAMES.get(s,s)} {s}' for s in symbols)
    research_section = ""
    if meta.get("comparison"):
        comp = pd.DataFrame(meta["comparison"])[["strategy","symbol","total_return","max_drawdown","filled_orders"]].copy()
        for key in ("total_return","max_drawdown"): comp[key]=comp[key].map(pct)
        comp.columns=["方案","证券","累计收益","最大回撤","成交订单"]
        research_section='<section class="panel"><h2>分股与组合研究结果</h2><div class="scroll">'+comp.to_html(index=False,border=0,classes="records",escape=True)+'</div></section>'
    params = meta.get("strategy_parameters", {})
    if meta["strategy"] == "PeriodicEqualWeight":
        strategy_text = (f'示例每 {params.get("rebalance_every", "N")} 个交易日等权调仓，'
                         f'目标投资比例 {params.get("invested_weight", 0.98):.0%}；这是系统流程验证，不是任务二策略研究。')
    else:
        strategy_text = f'策略类：{html.escape(meta["strategy"])}。'
    content = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>第四讲回测系统：运行报告</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f9;color:#172b42;font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:1180px;margin:36px auto;padding:0 24px}}h1{{font-size:30px;letter-spacing:-.5px;line-height:1.3;margin-bottom:12px}}h2{{font-size:20px;margin:0 0 16px}}p{{margin:8px 0}}.muted,small{{color:#5a6f86}}.notice{{border-left:4px solid #b45309;background:#fff7ed;padding:16px 20px;margin:24px 0}}.notice strong{{color:#92400e}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.stat,.panel{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:20px}}.stat small,.stat strong{{display:block}}.stat strong{{font-size:23px;margin-top:6px}}.panel{{margin-top:20px}}svg{{width:100%;height:auto;display:block}}svg text{{fill:#64748b;font:12px sans-serif}}.legend{{display:flex;flex-wrap:wrap;gap:12px 24px;font-size:13px}}.legend i{{display:inline-block;width:20px;height:3px;vertical-align:middle;margin-right:8px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th{{text-align:left;background:#eff4f9;white-space:nowrap}}td,th{{padding:10px 12px;border-bottom:1px solid #e2e8f0}}td{{white-space:nowrap}}li{{margin:7px 0}}code{{background:#eef2f6;padding:2px 5px;border-radius:4px}}.links{{display:flex;gap:18px;flex-wrap:wrap}}a{{color:#1d4ed8}}@media(max-width:700px){{main{{margin:22px auto;padding:0 14px}}h1{{font-size:25px}}.stats{{grid-template-columns:repeat(2,1fr)}}.stat,.panel{{padding:15px}}.stat strong{{font-size:20px}}}}
</style></head><body><main>
<p class="muted">量化交易系统课程 · 第四讲 · 任务一</p>
<h1>日频回测系统运行报告</h1><p>{html.escape(names)}</p>
<p class="muted">{m['start']} 至 {m['end']}，{m['trading_days']} 个交易日。{strategy_text}</p>
<div class="notice"><strong>{status}</strong><p>{context}</p><p>账户采用复权单位记账；成交等价股数不能当作真实券商登记股数。</p></div>
<div class="stats">{stat_html}</div>
{research_section}
<section class="panel"><h2>净值及单股持有参考</h2>{chart}<p class="muted">参考线只用于观察两只股票的复权走势，未扣费，未模拟其交易限制。</p></section>
<section class="panel"><h2>账户回撤</h2>{drawdown}</section>
<section class="panel"><h2>最近成交（最多 30 条）</h2><div class="scroll">{trade_table}</div></section>
<section class="panel"><h2>拒单原因</h2><ul>{reason_html}</ul><div class="scroll">{reject_table}</div></section>
<section class="panel"><h2>执行顺序</h2><p>收盘估值 → 策略读取截至当日的数据 → 生成目标持仓 → 下一交易日开盘检查限制、先卖后买 → 收盘记账。</p><p>最后一天不虚构下一次开盘，不强制清仓。完整信号、成交与持仓均可查阅原始记录。</p></section>
<section class="panel"><h2>完整运行记录</h2><div class="links"><a href="equity.csv">每日账户</a><a href="orders.csv">订单与成交</a><a href="positions.csv">每日持仓</a><a href="signals.csv">策略信号</a><a href="metrics.json">统计指标</a><a href="metadata.json">配置与数据说明</a></div></section>
<section class="panel"><h2>模型边界与数据假设</h2><ul>{note_html}</ul></section>
</main></body></html>'''
    (directory / "report.html").write_text(content, encoding="utf-8")
    return directory / "report.html"
