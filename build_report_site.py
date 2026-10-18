"""Package saved reports as a portable, read-only site (standard library only).

No market data, web API, or backtest is required. The same directory works
offline, under a local HTTP server, and at a GitHub Pages project subpath.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "report_site"
REPO = "https://github.com/Chuboxiao/stoneflow-quant"
INPUTS = {
    "5dr": "results/5dr_review/report.html",
    "breakout": "results/breakout_review/report.html",
    "analysis": "results/strategy_analysis/report.html",
    "overview": "REVIEW_LECTURE4.md",
}
LABELS = {
    "index": "报告首页", "5dr": "5DR 报告", "breakout": "突破报告",
    "full": "完整报告", "analysis": "机制与股票子集",
}

CSS = """
:root{--paper:#f4f1e9;--ink:#2f4438;--muted:#6d796b;--line:#d5dccb;--leaf:#e8ecde;--rust:#a55f3f}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.9 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}
a{color:inherit;text-underline-offset:4px}a:focus-visible{outline:2px solid var(--rust);outline-offset:5px}h1,h2,h3,.serif{font-family:'Songti SC','STSong',Georgia,serif}h1,h2,h3{line-height:1.45}h1{font-size:34px}h2{font-size:26px;margin-top:42px}h3{font-size:21px;margin-top:30px}p{margin:14px 0}strong{font-weight:650}code{background:var(--leaf);padding:2px 5px;border-radius:3px}pre{overflow:auto;white-space:pre-wrap;background:var(--leaf);padding:18px}blockquote{background:var(--leaf);border-left:3px solid var(--rust);padding:12px 20px;margin:20px 0}.table{overflow:auto;margin:22px 0}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}th{background:var(--leaf)}svg{max-width:100%;height:auto}.item{margin:6px 0 6px 14px}.analysis-chart{width:100%;max-width:900px}.analysis-chart text{font:14px -apple-system,'PingFang SC',sans-serif;fill:#53664a}
.site-nav{max-width:1180px;margin:0 auto;padding:22px 28px;display:flex;justify-content:space-between;align-items:center;gap:20px;border-bottom:1px solid var(--line);font:13px/1.7 -apple-system,'PingFang SC',sans-serif}.site-nav a{text-decoration:none}.brand{font-size:20px;font-family:'Songti SC',Georgia,serif;font-weight:700;white-space:nowrap}.brand span{font:10px/1 sans-serif;letter-spacing:2px;margin-left:12px}.nav-links{display:flex;flex-wrap:wrap;gap:12px 22px}.nav-links [aria-current=page]{color:var(--rust);border-bottom:1px solid var(--rust)}
.page{max-width:1124px;margin:0 auto;padding:40px 28px 70px}.eyebrow{font-size:10px;letter-spacing:3px;color:var(--rust);text-transform:uppercase}.hero{padding:28px 0 38px;display:grid;grid-template-columns:minmax(0,1.7fr) minmax(220px,1fr);gap:50px;align-items:center}.hero h1{font-size:49px;font-weight:500;line-height:1.5;margin:15px 0 20px}.hero p{max-width:640px;color:var(--muted)}.river{width:100%;max-width:285px;justify-self:center}.hero-meta{display:flex;gap:34px;flex-wrap:wrap;margin-top:27px}.hero-meta b{display:block;font-family:Georgia,serif;font-size:25px;font-weight:400}.hero-meta small{color:var(--muted);font-size:11px}.section-head{display:flex;justify-content:space-between;align-items:baseline;gap:15px;margin:12px 0 20px}.section-head h2{margin:0;font-size:28px}.section-head span{font-size:11px;color:var(--muted);letter-spacing:2px}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.card{padding:24px 24px 20px;border:1px solid var(--line);background:rgba(255,255,255,.22);display:flex;flex-direction:column;min-width:0}.card.featured{background:var(--leaf)}.card .n{font:italic 25px/1.4 Georgia,serif;color:var(--rust)}.card h3{font-size:25px;margin:18px 0 8px}.card p{font-size:13px;color:var(--muted);margin:0 0 18px}.metric{font:30px/1.5 Georgia,serif;letter-spacing:-1px}.metric-note{font-size:11px;color:var(--muted);margin-bottom:24px}.card a{margin-top:auto;font-size:13px;align-self:flex-start}.research-note{margin-top:32px;padding:24px 28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);display:grid;grid-template-columns:220px 1fr;gap:30px}.research-note h3{margin:3px 0;font-size:22px}.research-note p{margin:0;font-size:13px}.research-note a{display:inline-block;margin-top:12px;color:var(--rust)}.reading-note{font-size:12px;color:var(--muted);margin-top:24px}.site-footer{max-width:1124px;margin:0 auto;padding:22px 28px 35px;border-top:1px solid var(--line);color:var(--muted);font:11px/1.9 -apple-system,'PingFang SC',sans-serif;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.report-body{max-width:1080px;margin:36px auto 70px;padding:0 28px;font-size:14px;overflow-wrap:anywhere}.report-body svg{width:100%;height:auto;margin:20px 0}.report-label{margin-bottom:28px;font-size:11px;letter-spacing:1px;color:var(--muted)}.report-body>h1{font-size:32px}.report-part{border-top:2px solid var(--ink);padding-top:26px;margin-top:65px;scroll-margin-top:25px}.report-part>.part-heading{font-size:32px}.contents{display:flex;gap:12px 25px;flex-wrap:wrap;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:13px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media(max-width:760px){.site-nav{align-items:flex-start;flex-direction:column;padding:18px 22px}.nav-links{gap:10px 18px}.page{padding:24px 22px 45px}.hero{grid-template-columns:1fr;gap:12px;padding-top:12px}.hero h1{font-size:36px}.river{display:none}.hero-meta{gap:22px}.hero-meta b{font-size:22px}.cards{grid-template-columns:1fr}.card{padding:22px}.card h3{margin-top:9px}.research-note{grid-template-columns:1fr;gap:12px;padding:22px 0}.section-head span{display:none}.report-body{padding:0 20px}.report-body>h1{font-size:27px}.report-part>.part-heading{font-size:27px}.site-footer{padding:20px 22px}}
@media print{.site-nav,.site-footer{display:none}body{background:white}.report-body{max-width:none;padding:0}.report-part{break-before:page}.table{overflow:visible}a{color:inherit}}
"""


def nav(current: str) -> str:
    links = "".join(
        f'<a href="{key}.html"' + (' aria-current="page"' if key == current else '')
        + f'>{LABELS[key]}</a>'
        for key in ("index", "5dr", "breakout", "full")
    )
    return (f'<nav class="site-nav" aria-label="报告导航"><a class="brand" href="index.html">'
            f'穿石 <span>STONEFLOW</span></a><div class="nav-links">{links}'
            f'<a href="{REPO}">GitHub ↗</a></div></nav>')


def page(title: str, current: str, body: str, extra_css: str = "") -> str:
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)} · 穿石 Stoneflow</title>'
            f'<style>{extra_css}\n{CSS}</style></head><body>{nav(current)}{body}'
            '<footer class="site-footer"><span>穿石 Stoneflow · 量化交易系统第四讲</span>'
            '<span>静态研究报告 · 2025-01-02 — 2026-09-30 · 原始行情不随网页发布</span>'
            '</footer></body></html>\n')


def saved_report(key: str) -> tuple[str, str]:
    source = (ROOT / INPUTS[key]).read_text(encoding="utf-8")
    body = re.search(r'<body[^>]*>(.*?)</body>', source, re.S).group(1)
    style = re.search(r'<style[^>]*>(.*?)</style>', source, re.S).group(1)
    # Keep research assumptions and numbers; remove conversational review status
    # from these reader-facing copies. The original review files are untouched.
    body = re.sub(r'<blockquote>(?:本机审核版；尚未推送.*?|当前为本机审核版本.*?)</blockquote>', '', body)
    body = body.replace('5DR 反转策略作业审核稿', '5DR 反转策略研究报告')
    body = body.replace('全股票池突破策略审核稿', '全股票池突破策略研究报告')
    body = body.replace('你提到的“sd 股票”，本稿按ST／*ST风险警示股票处理；', '风险警示股票按ST／*ST处理；')
    # Scope the saved report's body rule so it cannot override site navigation.
    style = re.sub(r'\bbody\s*\{[^}]*\}', '', style)
    return body, style


def overview() -> str:
    """Render the small, controlled Markdown subset in the combined overview."""
    text = (ROOT / INPUTS["overview"]).read_text(encoding="utf-8")
    text = re.sub(r'^\*\*状态：.*$', '', text, flags=re.M)
    text = text.replace('第四讲作业总审核', '第四讲完整研究报告')
    text = text.replace('全股票池策略研究总览', '完整研究报告')
    text = text.replace('## 审核入口', '## 相关入口')
    text = re.sub(r'^- \[拟提交课程评论\].*\n', '', text, flags=re.M)
    text = re.sub(r'^网页运行后访问.*$', '本页下方包含5DR与突破的报告全文；顶部导航可分别阅读。可编程回测与参数修改见仓库本机运行指南。', text, flags=re.M)
    targets = {
        'REVIEW_5DR.md': '5dr.html', 'REVIEW_BREAKOUT.md': 'breakout.html',
        'ANALYSIS_STRATEGIES.md': 'analysis.html',
    }

    def inline(value: str) -> str:
        value = html.escape(value)

        def link(match):
            label, target = match.groups()
            target = targets.get(target, f'{REPO}/blob/main/{target}')
            return f'<a href="{target}">{label}</a>'

        value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
        value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
        return re.sub(r'`([^`]+)`', r'<code>\1</code>', value)

    out, table = [], []

    def flush():
        if not table:
            return
        rows = [[inline(c.strip()) for c in row.strip('|').split('|')] for row in table]
        out.append('<div class="table"><table><thead><tr>' + ''.join(f'<th>{c}</th>' for c in rows[0])
                   + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row)
                   + '</tr>' for row in rows[2:]) + '</tbody></table></div>')
        table.clear()

    for line in text.splitlines():
        if line.startswith('|'):
            table.append(line)
            continue
        flush()
        if not line.strip():
            continue
        match = re.match(r'^(#{1,3}) (.*)', line)
        if match:
            n = len(match[1])
            out.append(f'<h{n}>{inline(match[2])}</h{n}>')
        elif line.startswith('- '):
            out.append(f'<p class="item">• {inline(line[2:])}</p>')
        else:
            out.append(f'<p>{inline(line)}</p>')
    flush()
    return '\n'.join(out)


def homepage() -> str:
    return '''<main class="page">
<section class="hero"><div><div class="eyebrow">Lecture IV / A study of time &amp; price</div>
<h1>回望价格的来路，<br>辨认策略的边界。</h1>
<p>从短期反转到趋势突破，沿同一段行情回放交易。研究收益如何产生，也核对费用、成交限制与账本，让每一个结论都有据可查。</p>
<div class="hero-meta"><div><b>424</b><small>评价期交易日</small></div><div><b>5,451</b><small>课程证券列 · 逐日筛选ST</small></div><div><b>2025—2026</b><small>01.02 → 次年09.30</small></div></div></div>
<svg class="river" viewBox="0 0 285 300" aria-hidden="true"><circle cx="145" cy="144" r="114" fill="none" stroke="#d5dccb"/><circle cx="145" cy="144" r="97" fill="none" stroke="#e2e5da"/><path d="M114 18 C222 86 58 118 151 164 S201 242 131 286" fill="none" stroke="#78917a" stroke-width="2"/><path d="M130 22 C236 90 77 123 166 165 S215 249 145 289" fill="none" stroke="#b2bda5"/><ellipse cx="151" cy="165" rx="42" ry="27" transform="rotate(-24 151 165)" fill="#e0e5d6" stroke="#a9b59e"/><path d="M114 163 Q148 143 183 152" fill="none" stroke="#a9b59e"/><circle cx="201" cy="63" r="5" fill="#a55f3f"/><text x="224" y="273" fill="#6d796b" font-size="13" font-family="serif">穿石</text></svg></section>
<div class="section-head"><h2>从这里开始阅读</h2><span>THREE ENTRANCES / ONE RESEARCH</span></div>
<section class="cards" aria-label="三份研究报告">
<article class="card"><div class="n">01</div><h3>5DR 反转</h3><p>过去5日跌得更多的股票，之后会反弹吗？比较流动性、换手与风险过滤。</p><div class="metric">+37.55%</div><div class="metric-note">冻结流动性版累计收益 · 最大回撤 −47.17%</div><a href="5dr.html">阅读 5DR 报告 →</a></article>
<article class="card"><div class="n">02</div><h3>20 日突破</h3><p>突破近期高点能否延续？从全股票池的亏损，追问策略适用于哪些股票。</p><div class="metric">−11.71%</div><div class="metric-note">冻结趋势＋ATR版累计收益 · 最大回撤 −22.75%</div><a href="breakout.html">阅读突破报告 →</a></article>
<article class="card featured"><div class="n">03</div><h3>完整研究</h3><p>总览、两份报告全文与机制分析，放在一起核对收益、风险和回测精度。</p><div class="metric">同口径 · 可追溯</div><div class="metric-note">账户与成交约束 · 分年检验 · 费用压力测试</div><a href="full.html">阅读完整报告 →</a></article></section>
<aside class="research-note"><div><div class="eyebrow">A closer look</div><h3>盈利，不等于普遍有效。</h3></div><div><p>5DR流动性版在2026年前三季度亏损20.71%。按2024资料固定的较高波动组，普通突破全期盈利19.38%、最大回撤31.06%；仅用2025选组、2026重新建账后只获利0.36%、最大回撤30.23%。这些差异是需要解释的证据，也划定了结论的边界。</p><a href="analysis.html">查看收益来源与股票子集研究 →</a></div></aside>
<p class="reading-note">评价区间：2025-01-02 至 2026-09-30。报告属于回顾性研究；2024选型是时间隔离，不能称为真实前瞻盲测。网页可直接阅读图表和表格；策略代码、逐笔记录与本机重跑指南见 <a href="https://github.com/Chuboxiao/stoneflow-quant">GitHub 仓库</a>。</p></main>'''


def build() -> dict[str, bytes]:
    reports = {key: saved_report(key) for key in ('5dr', 'breakout', 'analysis')}
    files = {'index.html': page('研究报告首页', 'index', homepage())}
    label = '<div class="report-label">研究区间 2025-01-02 — 2026-09-30 · 只读报告 · 无需课程原始数据</div>'
    for key, (body, style) in reports.items():
        files[f'{key}.html'] = page(LABELS[key], key,
                                   f'<main class="report-body">{label}{body}</main>', style)
    contents = ('<div class="contents" aria-label="完整报告目录"><a href="#overview">总览</a>'
                '<a href="#five-dr">一 · 5DR 全文</a><a href="#breakout">二 · 突破全文</a>'
                '<a href="#strategy-analysis">收益来源与适用股票</a></div>')
    parts = [f'<main class="report-body">{label}{contents}<section id="overview">{overview()}</section>']
    for key, anchor, title in [('5dr', 'five-dr', '一 · 5DR反转研究全文'),
                               ('breakout', 'breakout', '二 · 20日突破研究全文')]:
        body = re.sub(r'<h1>.*?</h1>', '', reports[key][0], count=1)
        body = re.sub(r'<(/?)h([23])>', lambda m: f'<{m[1]}h{int(m[2])+1}>', body)
        parts.append(f'<section class="report-part" id="{anchor}"><h2 class="part-heading">{title}</h2>{body}</section>')
    parts.append('</main>')
    files['full.html'] = page('完整研究报告', 'full', ''.join(parts))
    manifest = {'format': 1, 'kind': 'read-only-saved-reports', 'sources': {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS.values()}}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    files['.nojekyll'] = ''
    return {name: value.encode('utf-8') for name, value in files.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if packaged reports are out of date.')
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = [name for name, data in files.items()
                 if not (OUT / name).exists() or (OUT / name).read_bytes() != data]
        if stale:
            raise SystemExit('Reports need rebuilding: ' + ', '.join(stale))
        print(f'OK: {len(files)} packaged files match their saved report sources.')
        return
    OUT.mkdir(exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    print(f'Built {len(files)} files in {OUT.name}/ ({sum(map(len, files.values())):,} bytes).')


if __name__ == '__main__':
    main()
