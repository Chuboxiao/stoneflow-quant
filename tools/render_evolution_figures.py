"""Render vector evidence figures for the saved lecture-six study (no market data)."""

import hashlib
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/evolution_runs/a4099ff45a9f/study.json"
INK, MUTED, GREEN, RUST = "#294137", "#647267", "#346a4b", "#a65c3e"


class Figure:
    def __init__(self, title, subtitle, height):
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img">',
            f"<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>",
            '<style>text{font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif} .num{font-variant-numeric:tabular-nums}</style>',
        ]
        self.rect(0, 0, 1200, height, "#f4f1e9")
        self.text(48, 48, "STONEFLOW / 穿石因子实验室", 17, MUTED)
        self.text(48, 101, title, 34)
        self.text(48, 139, subtitle, 20, MUTED)

    def rect(self, x, y, width, height, fill, stroke=None):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="4" fill="{fill}"' + (f' stroke="{stroke}"' if stroke else "") + "/>")

    def text(self, x, y, value, size=22, color=INK, anchor="start", weight=400):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}" class="num">{escape(str(value))}</text>')

    def line(self, y):
        self.parts.append(f'<path d="M48 {y}H1152" stroke="#d1d7ca"/>')

    def save(self, name, digest):
        self.line(self.height - 56)
        self.text(48, self.height - 24, f"数据图 · study a4099ff45a9f · SHA256 {digest[:12]} · 由完整实验记录生成", 16, MUTED)
        (ROOT / "docs" / name).write_text("\n".join(self.parts + ["</svg>"]), encoding="utf-8")


def main():
    raw = SOURCE.read_bytes()
    study = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    new = [c for c in study["candidates"].values() if c["round"] > 0]
    initial = study["baseline"]["metrics"]["validation"]
    final = study["pool_metrics"]["validation"]
    before = study["review"]["seed_pool"]["metrics"]
    after = study["review"]["selected_pool"]["metrics"]

    fig = Figure("三轮研究，留下一个有组合增量的新因子", "2024 搜索 → 2025 反复选择验证 → 冻结后回顾 2026 年 1—9 月", 960)
    stats = [("起始因子", len(study["candidates"]) - len(new)), ("研究轮次", study["rounds_completed"]), ("新候选", len(new)), ("新候选获保留", sum(c["accepted"] for c in new))]
    for i, (label, value) in enumerate(stats):
        x = 48 + i * 280
        fig.rect(x, 172, 264, 108, "#faf8f2", "#d1d7ca")
        fig.text(x + 20, 207, label, 20, MUTED)
        fig.text(x + 20, 257, value, 39, GREEN)

    fig.rect(48, 306, 1104, 125, "#e5ebdc")
    fig.text(72, 343, "初始因子池", 20, MUTED)
    fig.text(72, 392, "五日反转 ＋ 20日低波动", 27)
    fig.text(575, 388, "→", 34, RUST)
    fig.text(672, 343, "冻结因子池 · 两个家族，等权秩组合", 20, MUTED)
    fig.text(672, 392, "十日反转 ＋ 20日低波动", 27, GREEN)

    fig.text(48, 479, "同口径比较", 26)
    fig.text(805, 479, "初始因子池", 20, MUTED, "end")
    fig.text(1125, 479, "冻结因子池", 20, MUTED, "end")
    rows = [
        ("2025 选择验证 · 组合 Rank IC", f'{initial["rank_ic"]:.4f}', f'{final["rank_ic"]:.4f}'),
        ("2025 选择验证 · 正 IC 月份", f'{round(initial["positive_months"] * initial["months"])}/12', f'{round(final["positive_months"] * final["months"])}/12'),
        ("2026 冻结后回顾 · 组合 Rank IC", f'{before["rank_ic"]:.4f}', f'{after["rank_ic"]:.4f}'),
        ("2026 回顾 · Q5−Q1 平均未来5日报价收益", f'{before["spread"]:.4%}', f'{after["spread"]:.4%}'),
    ]
    for i, (label, a, b) in enumerate(rows):
        y = 532 + i * 57
        fig.text(48, y, label, 22)
        fig.text(805, y, a, 27, MUTED, "end")
        fig.text(1125, y, b, 27, RUST if i in (1, 3) else GREEN, "end")
        fig.line(y + 19)

    fig.text(48, 779, "为何只留一个？", 24, weight=600)
    fig.text(48, 816, "10日低波动的单因子 IC 更高，但替换后组合没有增量，仍然淘汰。", 23)
    fig.text(48, 858, "平均 IC 提高，验证正 IC 月份减少；回顾收益差仍为负，尚未证明更赚钱。", 21, RUST)
    fig.text(48, 886, "2026 历史此前已查看，属于回顾而非新盲测；报价收益未扣费，未完成净交易验证。", 18, MUTED)
    fig.save("stoneflow-evolution-results.svg", digest)

    fig = Figure("9 个新候选，每一次保留和淘汰都有依据", "接受条件：组合验证 IC 至少增加 0.0001，且搜索 IC 下降不超过 0.005（另需通过质量门槛）", 1040)
    columns = [(48, "轮次 / 来源", "start"), (214, "候选因子", "start"), (735, "单因子验证 IC", "end"), (980, "组合验证 IC 增量", "end"), (1145, "决定", "end")]
    for x, label, anchor in columns:
        fig.text(x, 198, label, 20, MUTED, anchor)
    fig.line(218)
    families = {"reversal": "反转", "risk": "风险", "price_location": "价格位置", "price_volume": "价量交互", "hybrid": "跨家族组合"}
    for i, candidate in enumerate(new):
        y = 254 + i * 69
        accepted = candidate["accepted"]
        if accepted:
            fig.rect(36, y - 26, 1128, 67, "#e0ead8")
        fig.text(48, y, f'第{candidate["round"]}轮', 22)
        fig.text(48, y + 24, "规则建议" if candidate["source"] == "rule-baseline" else "Agent 导入", 17, MUTED)
        fig.text(214, y, candidate["spec"]["key"], 22)
        family = candidate["spec"]["family"]
        fig.text(214, y + 24, families.get(family, family), 17, MUTED)
        fig.text(735, y + 8, f'{candidate["metrics"]["validation"]["rank_ic"]:.4f}', 24, INK, "end")
        gain = candidate["pool_validation_gain"]
        gain_label = f"{gain:+.2e}" if 0 < abs(gain) < 0.000001 else f"{gain:+.6f}"
        fig.text(980, y + 8, gain_label, 24, GREEN if accepted else RUST, "end")
        fig.text(1145, y + 8, "保留" if accepted else "淘汰", 22, GREEN if accepted else RUST, "end", 600)
        fig.line(y + 43)

    fig.text(48, 922, "第2轮：十日反转替换五日反转；第3轮没有候选通过，保留池不变。", 23)
    fig.text(48, 958, "增量均相对该候选提出时的当前因子池；全部原始指标、提出理由和失败记录可在实验报告核查。", 18, MUTED)
    fig.save("stoneflow-evolution-candidates.svg", digest)
    print("Generated two SVG figures from", SOURCE.relative_to(ROOT))


if __name__ == "__main__":
    main()
