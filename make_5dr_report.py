"""Generate the review memo and a self-contained HTML report from saved results."""
from __future__ import annotations
import html
import json
from pathlib import Path
import re
import pandas as pd

ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/"results/5dr_review"


def percent(x):return f"{x*100:.2f}%"
def number(x):return f"{x:,.2f}"


def md_table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","| "+" | ".join("---" for _ in headers)+" |",
                       *("| "+" | ".join(str(x) for x in row)+" |" for row in rows)])


def render_markdown(text):
    # Only the controlled subset used below; escape all source text first.
    def inline(line):
        line=html.escape(line)
        line=re.sub(r"\[([^\]]+)\]\((https://[^)]+)\)",r'<a href="\2">\1</a>',line)
        line=re.sub(r"\*\*([^*]+)\*\*",r"<strong>\1</strong>",line)
        line=re.sub(r"`([^`]+)`",r"<code>\1</code>",line)
        return line
    out=[];table=[];code=[];in_code=False
    def flush():
        nonlocal table
        if table:
            rows=[r.strip().strip('|').split('|') for r in table]
            out.append('<div class="table"><table><thead><tr>'+''.join('<th>'+inline(c.strip())+'</th>' for c in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in row)+'</tr>' for row in rows[2:])+'</tbody></table></div>');table=[]
    for line in text.splitlines():
        if line.startswith('```'):
            flush()
            if in_code:out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');code=[]
            in_code=not in_code;continue
        if in_code:code.append(line);continue
        if line.startswith('|'):table.append(line);continue
        flush()
        if not line.strip():continue
        match=re.match(r'^(#{1,3}) (.*)',line)
        if match:
            level=len(match[1]);out.append(f'<h{level}>'+inline(match[2])+f'</h{level}>')
        elif line.startswith('- '):out.append('<p class="item">• '+inline(line[2:])+'</p>')
        elif line.startswith('> '):out.append('<blockquote>'+inline(line[2:])+'</blockquote>')
        else:out.append('<p>'+inline(line)+'</p>')
    flush()
    return '\n'.join(out)


def main():
    s=json.loads((RESULTS/"summary.json").read_text())
    validation=json.loads((RESULTS/"validation.json").read_text())
    test_log=(RESULTS/"unit_tests.txt").read_text()
    test_match=re.search(r"Ran (\d+) tests",test_log)
    test_count=int(test_match[1]) if test_match else 0
    selection=json.loads((RESULTS/"selection.json").read_text())
    chosen=next(x for x in s["comparison"] if x["key"]==s["selected_key"])
    base=next(x for x in s["comparison"] if x["key"]=="base")
    improvement=chosen["total_return"]-base["total_return"]
    dd_improvement=chosen["max_drawdown"]-base["max_drawdown"]
    verdict=(f"累计收益提高 {improvement*100:.2f} 个百分点" if improvement>=0 else f"累计收益降低 {-improvement*100:.2f} 个百分点")
    verdict+=(f"，最大回撤缩小 {dd_improvement*100:.2f} 个百分点" if dd_improvement>=0 else f"，最大回撤扩大 {-dd_improvement*100:.2f} 个百分点")
    stress=[x for x in s["stress"] if x["key"]==s["selected_key"]]
    names={"double_cost":"全部交易税费与滑点双倍","tight_capacity":"成交额参与上限降至0.1%","gross_dividend":"现金股利税率改为0","carry_stale":"缺价保留旧估值"}
    audit=s["precision_audit"]
    periods={p["period"]:{x["key"]:x for x in s["periods"] if x["period"]==p["period"]} for p in s["periods"]}
    cost_case=next(x for x in stress if x["scenario"]=="double_cost")
    year2026=periods["2026年前三季度"][s["selected_key"]]
    actions=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"actions.csv")
    orders=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"orders.csv")
    pos=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"positions.csv")
    filled=orders[orders.notional>0]
    buy_st=int(((filled.side=="BUY")&((filled.signal_is_st!=0)|(filled.execution_is_st!=0))).sum())
    stock_assumptions=int(actions.stock_date_assumed.fillna(False).astype(bool).sum()) if "stock_date_assumed" in actions else 0
    held_st_days=pos.loc[pos.is_st==1,"date"].nunique()
    benchmarks=s.get("benchmark",[])
    benchmark_text=f"沪深300价格指数同区间参考涨幅为 **{percent(benchmarks[-1]['net_value']-1)}**（以前一交易日收盘归一、未扣费；不是可交易账户，也没有做风格风险调整）。" if benchmarks else "本次未取得完整指数参考，不虚构指数表现。"
    comparison=md_table(["预设方案","累计收益","最大回撤","平均仓位","单边换手","交易费用（元）"],
                        [[x["strategy"]+("【2024冻结】" if x["selected_on_2024"] else ""),percent(x["total_return"]),percent(x["max_drawdown"]),percent(x["average_exposure"]),f"{x['turnover_one_way']:.2f}倍",number(x["total_fees"])] for x in s["comparison"]])
    train_table=md_table(["候选","2024收益","2024最大回撤","选择分数"],[[x["strategy"],percent(x["total_return"]),percent(x["max_drawdown"]),f"{x['score']:.4f}"] for x in selection["training"]])
    period_table=md_table(["区间","基础5DR收益","冻结方案收益","冻结方案回撤"],[[title,percent(rows["base"]["total_return"]),percent(rows[s["selected_key"]]["total_return"]),percent(rows[s["selected_key"]]["max_drawdown"])] for title,rows in periods.items()])
    stress_table=md_table(["额外假设","冻结方案累计收益","最大回撤"],[[names[x["scenario"]],percent(x["total_return"]),percent(x["max_drawdown"])] for x in stress])
    focus_table=md_table(["股票","方案","累计收益","最大回撤"],[[x["symbol"],x["strategy"],percent(x["total_return"]),percent(x["max_drawdown"])] for x in s.get("focus_stocks",[])])
    report=f"""# 穿石 Stoneflow：5DR 反转策略研究报告


老师指定的评价区间为 **2025-01-02 至 2026-09-30，共 424 个交易日**。2024 年仅用于历史热身和候选方案选型；2026-10 月行情不进入这次评价。研究使用课程给定的 5,451 列证券，按当日可用信息构造股票池；不能据此证明包内名单覆盖了完整历史市场。

你提到的“sd 股票”，本稿按ST／*ST风险警示股票处理；5DR按过去5个交易日收益率从低到高选股处理。未指定的持仓数、资金与费用采用下文明确列出的教学设定。

## 先看结论

按 2024 年规则选出的方案是 **{chosen['strategy']}**。评价期累计收益 **{percent(chosen['total_return'])}**，最大回撤 **{percent(chosen['max_drawdown'])}**；基础 5DR 分别为 **{percent(base['total_return'])}**、**{percent(base['max_drawdown'])}**。冻结方案相对基础版{verdict}。

改进没有消除高回撤和成本敏感性：冻结方案2026年前三季度收益为 **{percent(year2026['total_return'])}**；交易税费与滑点加倍后，整个评价期收益仅 **{percent(cost_case['total_return'])}**。降低换手的缓冲版和每5日调仓版也没有超过冻结方案。作业可以说明流动性与低价过滤在本次样本中改善了5DR，同时仍不足以证明策略适合实盘。

这个结论仅针对下述账户、税费和成交代理。不能把评价期收益最高的候选重新命名为“最优策略”，也不能用一次历史比较证明以后有效。当前属于按时间隔离的回顾性研究，规则是在 2026 年整理，并非在 2024 年真实预注册的前瞻实验。

{benchmark_text}

## 作业要求对应

| 要求 | 这次实现 |
| --- | --- |
| 指定区间 | 2025-01-02 → 2026-09-30；424 日；首日可用上年末信号 |
| 去掉 ST | BaoStock 逐日 isST；信号日为0才入选，执行日再次检查；未知状态不新买 |
| 必须用 cumadj | 5DR = close[t]×cumadj[t] / (close[t-5]×cumadj[t-5]) − 1 |
| 涨停不能假定买到 | 开盘价或滑点后价格到涨停均拒买；跌停同样拒卖 |
| 改进 5DR | 同口径比较5个固定候选；只按2024选择；分年和压力情景一起查看 |
| 关注回测精度 | 固定前一日股数、原始股份与现金账、真实历史参考前收、板块数量单位、费用、应收、锁股、缺价处理、独立账本重放 |

ST 排除指不把风险警示证券纳入新买股票池。已经持有的股票后来被 ST，会尝试卖出；停牌、跌停等可能使它暂时留在账上，不能假装已卖出。冻结方案发生 {held_st_days} 个含 ST 持仓的交易日，已成交买单中信号日或执行日为 ST／未知的笔数为 **{buy_st}**。

## 基础策略和改进假设

每日收盘计算过去5个交易日的复权收益，按收益从低到高排序，选20只，目标各占总权益4.75%，合计95%，剩余留现金。收益相同按代码排序。入选要求已有至少60个有效报价日、最近20日收盘与因子有效、当日有成交、历史状态明确且非ST；不使用评价期末的名单回填早期股票池。不要求5DR必须小于0。

- 基础版：每日重新选最低20只。
- 流动性版：再要求近20日平均成交额≥2,000万元、收盘价≥3元；研究低流动性与低价风险是否影响结果。
- 排名缓冲版：加流动性过滤；已有持仓仍在最低60名内时保留，剩余名额按最低收益补齐，减少边界反复买卖。
- 每5日调仓版：在缓冲版上每5个交易日调仓；失去资格的持仓仍立即产生退出指令。
- 风险冷静期版：在缓冲版上要求过去60日风险标记均明确为非ST，避免刚摘帽或风险信息刚变化便买入。

缓冲版在调仓日仍按等权目标计算数量；它不等于完全不调整保留持仓。每个候选使用相同初始资金100万元与撮合模型，没有为了改善评价期结果继续扫描参数。

## 2024 年选型依据

固定选择分数为：2024年化收益 /（|2024最大回撤| + 0.05），取分数最高者，平分按key排序。该分数体现收益和回撤的折中，是研究设定，不是普适最优评价指标。选型、参数和规则摘要保存于 protocol.json 与 selection.json。

{train_table}

## 老师指定区间的比较

{comparison}

{period_table}

收益为实际模拟账户的净收益；年内分段以该段开始前的连续账户权益为基点，没有每年重置资金和持仓。回撤在各展示区间内重新计算。期末按收盘估值，不强制清仓、不扣假设清仓费。

## 把假设收紧之后

{stress_table}

各情景会同时改变现金、整手数量和拒单路径，收益不保证随税费或容量单调变化。因此不能将“不扣税”当作收益的严格上界，或从收紧容量后收益增加推出容量越小越好。0.1%容量使用上一日已知的近20日日均成交额；这是事前规模保护，不能证明开盘盘口一定容纳订单。缺价旧估值情景只用于揭示估值敏感性，不把它当作真实可退出金额。

## 两只关注股票的同区间对照

长源东谷603950.SH、科大讯飞002230.SZ分别使用50万元独立子账户、95%目标仓位，在2025-01-02至2026-09-30重跑原20/10突破、1.5倍成交额确认与买入持有。这6组采用新原始股份账户，仅作个股诊断，不参与全池5DR方案选型。

{focus_table}

## 账户和成交精度

订单数量在 t 日收盘用当时权益与原始收盘价计算，容量也用截至 t 日的成交额；t+1 日不按开盘后的资产重新做策略决策。执行按先卖后买顺序，只有已实现的卖出收入可供后续买单使用，买单可因资金不足缩量。此过程近似开盘附近的顺序成交，不是对同一集合竞价中所有订单同时成交的复现；固定代码顺序可能影响资金紧张时的分配。

普通主板与创业板按100股单位；科创板按至少200股、其后1股递增，余额不足最小数量时仅允许完整卖出。每只每天最多一笔计划，数量最多50,000股；买入股份遵守T+1。使用佣金万三、每笔至少5元，卖出印花税万五，双边过户费十万分之一，单边滑点5bps；金额按分四舍五入，佣金视为包含经手费等券商收取项。

涨跌停采用未复权历史 preclose 和对应板块比例重建，价格按 ROUND_HALF_UP 取到0.01元；保留参考前收的源精度至最后一步。普通非ST为10%，创业板／科创板20%；主板ST卖出订单在2026-07-06前按5%，此后按10%。该历史变化来自交易所规则，不能把最新规则套到整个历史区间。上市不足60个有效报价日不买；特殊复牌／重新上市等不保证被完整识别，越出规则边界的开盘记录拒单。

原始现金和股份账户没有把现金分红当作增加股份。按登记日持仓确认股利，派息日前列为应收；现金股利统一预扣20%作为保守教学假设。送转新增股份向下取整，并按数据提供的可交易日锁定；本次冻结方案有 {stock_assumptions} 条缺少股份上市日而按除权日处理的事件。送股相关个税、实际零股分配、配股选择权及所有特殊重整事件尚未完整建模。除权日取消前一日的旧数量计划，收盘后重新计划；持仓因子出现实质变化却没有可核对的公司行为时，正式运行停止。

另核对了4笔差异化分红送转：回购专户不参与分配时，普通持有人实际到账比例与交易所除权参考价的摊薄比例不同。账户使用实际分配比例，参考价校验使用公告披露的摊薄比例；来源和生效日期记录在 reference/corporate_reference_overrides.json。这些资料只用于公司行为核对，不参与选股或收益调参。

全天成交额／笔数为零或滑点价格超出当日高低价，仅作事后不可行成交的否决，不用于盘前选股、估计当日容量。连续20个交易日没有有效收盘价的持仓减记至零，股份仍保留、现金不增加；若报价恢复，再按报价估值。减记是研究估值假设，不能称为成功卖出。冻结方案期末减记残留 {chosen['ending_impaired_positions']} 只、含缺价持仓的日期 {chosen['stale_valuation_days']} 日。

## 数据与独立校验

辅助历史数据与课程未复权收盘共比较 **{s['data_audit']['raw_close_compared']:,}** 个有效格，发现 **{s['data_audit']['raw_close_mismatched']:,}** 格相差超过半分钱；这些记录的交易状态作未知处理。评价期有成交报价格中，历史状态覆盖率为 **{percent(audit['known_state_coverage'])}**，未知状态格 **{audit['unknown_active_state_cells']:,}**，ST报价格 **{audit['st_active_cells_excluded']:,}**。未知状态始终排除，不能把它们当作非ST。

历史 isST 是事后取得的生效日数据，假设生效日前盘前可知，没有逐条复原当时公告发布时间和数据修订版本。数据源的前收与板块规则不是交易所逐日官方涨跌停价文件；也未取得完整盘口和开盘量。因此精度较旧5%统一代理有改进，仍不能称为精确实盘复现。

独立校验脚本不调用撮合引擎，只读取已保存CSV，重放现金、股份、股利应收和每日权益，核对费用、整数股份、ST买单、上下限、信号先于成交等。**{validation['runs_checked']} 组运行、{validation['checks']:,} 个账本断言，{'全部通过' if validation['passed'] else '存在失败，见validation.json'}**。另有 **{test_count} 项单元测试通过**，覆盖因果性前缀不变、历史副本、首日信号、除权、锁股及缺价；完整日志保存在 unit_tests.txt。

代码和派生结果可公开；课程 Feather、辅助源数据缓存和本机配置不上传。每次正式运行记录输入哈希、源码哈希和软件版本；数据服务以后可能修订历史，复现时应对照 manifest。

## 复现与研究记录

网页：启动 web_server.py 后访问 `/5dr`，可切换基础与冻结方案指标，查看比较、分年、压力情景和最近订单。原 `/` 页面与旧突破实验保留。

核心文件：backtest/precision.py；research_5dr.py；validate_5dr.py；tools/fetch_reference.py；tools/fetch_actions.py。新精度引擎仍接受任意实现 on_close(context) 的 Python 策略，提供截止当日的 history 与 states 副本；可以保存状态和组合函数，并非只能修改预设策略参数。

新环境先安装 requirements-research.txt；下载辅助历史数据；用 --provisional 只发现所需公司行为，fetch_actions.py 补齐后再次发现，直到 needed_actions.json 为空；再运行不带该标志的正式回测和 validate_5dr.py。临时发现结果不作为提交成绩，正式结果不允许合成股份兜底。详见 docs/PRECISION_5DR.md。

## 来源

- [上交所2025年休市安排：1月2日起开市](https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml)
- [上交所2026年中秋国庆休市安排](https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml)
- [BaoStock 0.9.4 发布与历史行情字段](https://pypi.org/project/baostock/0.9.4/)
- [深交所涨跌幅价格计算及四舍五入](https://investor.szse.cn/knowledge/stock/deal/t20180801_553961.html)
- [上交所2026年交易规则及生效日期](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)
- [上交所修订说明：主板ST涨跌幅5%改10%](https://big5.sse.com.cn/site/cht/www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)
- [科创板数量与涨跌幅规则](https://edu.sse.com.cn/tib/qa/c/4866268.shtml)
- [仕净科技2024年实施公告：实际与摊薄比例](https://static.cninfo.com.cn/finalpage/2024-05-21/1220121664.PDF)
- [捷安高科2025年实施公告：差异化分红送转](https://static.cninfo.com.cn/finalpage/2025-05-20/1223609061.PDF)
- [开勒股份官网公告入口，2025-034](https://www.kalefans.com/investment/1.html)
- [鑫宏业2026年实施公告：实际与摊薄比例](https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-05-13/be86e959-b7d9-4a20-94cb-47d547845a91.PDF)

"""
    (ROOT/"REVIEW_5DR.md").write_text(report,encoding="utf-8")
    base_eq=pd.read_csv(RESULTS/"evaluation/base/equity.csv")
    chosen_eq=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"equity.csv")
    lines=[(base_eq.net_value.tolist(),'#8eaa87','基础5DR'),(chosen_eq.net_value.tolist(),'#b56b45','2024冻结方案')]
    if benchmarks:lines.append(([x["net_value"] for x in benchmarks],'#526e78','沪深300价格指数'))
    values=[v for seq,_,_ in lines for v in seq];lo=min(values)*.95;hi=max(values)*1.05
    chart='<svg viewBox="0 0 1000 300" role="img" aria-label="净值曲线">'
    for j in range(5):
        y=15+j*240/4;v=hi-(hi-lo)*j/4
        chart+=f'<line x1="50" y1="{y}" x2="980" y2="{y}" stroke="#dce1d2"/><text x="40" y="{y+4}" text-anchor="end" fill="#8b9580" font-size="11">{v:.2f}</text>'
    for seq,color,label in lines:
        points=' '.join(f'{50+i*930/(len(seq)-1):.2f},{15+(hi-v)*240/(hi-lo):.2f}' for i,v in enumerate(seq))
        chart+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2"><title>{label}</title></polyline>'
    chart+='<text x="50" y="287" font-size="11" fill="#8b9580">2025-01-02</text><text x="980" y="287" text-anchor="end" font-size="11" fill="#8b9580">2026-09-30</text></svg>'
    chart+='<p>'+''.join(f'<span style="color:{color};margin-right:25px">━ {label}</span>' for _,color,label in lines)+'</p>'
    css="body{max-width:1050px;margin:45px auto;padding:0 30px;background:#f4f1e9;color:#2f4438;font:14px/1.9 -apple-system,'PingFang SC',sans-serif}h1,h2,h3{font-family:'Songti SC',serif}h1{font-size:30px;border-bottom:1px solid #d1d8c6;padding-bottom:22px}h2{font-size:22px;margin-top:40px}p{margin:12px 0}a{color:#567c67}blockquote{background:#e8ecde;border-left:3px solid #b56b45;padding:10px 18px;margin:15px 0}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;background:#faf9f1;white-space:nowrap}td,th{border-bottom:1px solid #dce1d1;padding:9px 12px;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e9eddf}code{background:#e5e9dc;padding:2px 4px;border-radius:3px}.item{margin:5px 0 5px 15px}svg{width:100%;height:auto;margin:20px 0}"
    body=render_markdown(report)
    body=body.replace('<h2>老师指定区间的比较</h2>','<h2>老师指定区间的比较</h2>'+chart)
    (RESULTS/"report.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>穿石 · 5DR作业审核报告</title><style>'+css+'</style><body>'+body+'</body></html>',encoding="utf-8")
    comment=f"""第四讲研究记录：**穿石 Stoneflow — 5DR反转策略与回测精度研究**

仓库：https://github.com/Chuboxiao/stoneflow-quant

按老师要求评价 **2025-01-02 至 2026-09-30（424日）**；在课程股票池中按逐日历史ST状态筛选，未知状态不新买。用cumadj计算5日收益，在前一日收盘固定订单数量，下一交易日开盘附近执行代理；涨停拒买、跌停拒卖，纳入板块数量单位、费用、现金股利应收与股份锁定。

预设基础5DR及4种改进，仅用2024年选择 **{chosen['strategy']}**。评价期基础版累计收益{percent(base['total_return'])}、最大回撤{percent(base['max_drawdown'])}；冻结方案分别为{percent(chosen['total_return'])}、{percent(chosen['max_drawdown'])}。所有候选、分年表现、双倍成本和容量敏感性均保留，未按评价期重新选冠军。

冻结方案2026年前三季度收益{percent(year2026['total_return'])}；双倍税费与滑点下，整个评价期收益仅{percent(cost_case['total_return'])}。高回撤与成本敏感性仍然明显。

{test_count}项单元测试通过，{validation['runs_checked']}组运行完成独立现金／股份／权益账本重放。历史ST按生效日处理，未复原公告发布时间；规则重建限价与开盘成交仍为代理，现金股利个税、零股分配及特殊公司行为有简化，不声称精确实盘复现。原始课程和辅助源数据不上传。

[研究报告](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_5DR.md)

![穿石5DR研究工作台](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-5dr-review.jpg)
"""
    (ROOT/"SUBMISSION_5DR_DRAFT.md").write_text(comment,encoding="utf-8")


if __name__=="__main__":main()
