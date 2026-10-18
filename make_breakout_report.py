"""Build the combined homework review and the offline breakout report from ledgers."""
import json
from pathlib import Path
import re
import pandas as pd
from make_5dr_report import render_markdown, md_table, percent, number

ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/"results/breakout_review"


def load(name):return json.loads((RESULTS/name).read_text())


def main():
    if load("run_status.json")["status"]!="COMPLETE":raise ValueError("Formal research incomplete")
    s=load("summary.json");v=load("validation.json");selection=load("selection.json")
    if not v["passed"]:raise ValueError("Ledger validation failed")
    five=json.loads((ROOT/"results/5dr_review/summary.json").read_text())
    v5=json.loads((ROOT/"results/5dr_review/validation.json").read_text())
    chosen=next(x for x in s["comparison"] if x["key"]==s["selected_key"])
    base=next(x for x in s["comparison"] if x["key"]=="base")
    liquid5=next(x for x in five["comparison"] if x["key"]==five["selected_key"])
    base5=next(x for x in five["comparison"] if x["key"]=="base")
    control=s["exposure_control"]
    selected_stress=[x for x in s["stress"] if x["key"]==s["selected_key"]]
    stress_names={"double_cost":"税费与滑点均加倍","tight_capacity":"容量收紧至日均成交额0.1%"}
    selected_years=[x for x in s["periods"] if x["key"]==s["selected_key"]]
    testlog=(RESULTS/"unit_tests.txt").read_text()
    test_count=int(re.search(r"Ran (\d+) tests",testlog).group(1))
    evaluation=md_table(["预设方案","累计收益","最大回撤","平均仓位","单边换手","费用（元）"],
        [[r["strategy"]+("【2024冻结】" if r["selected_on_2024"] else ""),percent(r["total_return"]),percent(r["max_drawdown"]),percent(r["average_exposure"]),f"{r['turnover_one_way']:.2f}倍",number(r["total_fees"])] for r in s["comparison"]])
    training=md_table(["方案","2024收益","2024回撤","选择分数"],
        [[r["strategy"],percent(r["total_return"]),percent(r["max_drawdown"]),f"{r['score']:.4f}"] for r in selection["training"]])
    periods=md_table(["年份","普通突破收益","冻结方案收益","冻结方案回撤"],
        [[r["period"],percent(next(x for x in s["periods"] if x["key"]=="base" and x["period"]==r["period"])["total_return"]),percent(r["total_return"]),percent(r["max_drawdown"])] for r in selected_years])
    stress=md_table(["压力情景","冻结方案收益","最大回撤"],
        [[stress_names[r["scenario"]],percent(r["total_return"]),percent(r["max_drawdown"])] for r in selected_stress])
    control_table=md_table(["参照","累计收益","最大回撤","平均仓位"],
        [[r["strategy"],percent(r["total_return"]),percent(r["max_drawdown"]),percent(r["average_exposure"])] for r in (base,control,chosen)])
    overall=md_table(["策略家族","方案","累计收益","最大回撤"],
        [[family,r["strategy"],percent(r["total_return"]),percent(r["max_drawdown"])] for family,r in (("5DR",base5),("5DR",liquid5),("20日突破",base),("20日突破",chosen))])
    actions=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"actions.csv")
    orders=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"orders.csv")
    pos=pd.read_csv(RESULTS/"evaluation"/s["selected_key"]/"positions.csv")
    fills=orders[orders.notional>0]
    st_buys=int(((fills.side=="BUY")&((fills.signal_is_st!=0)|(fills.execution_is_st!=0))).sum())
    assumed=int(actions.stock_date_assumed.fillna(False).astype(bool).sum()) if "stock_date_assumed" in actions else 0
    still_st=pos.loc[pos.is_st==1,"date"].nunique()
    half_verdict=("冻结方案同时取得更低回撤和较高收益" if chosen["max_drawdown"]>control["max_drawdown"] and chosen["total_return"]>control["total_return"] else
                  "固定半仓参照反而同时取得更高收益和更低回撤，本次无法证明ATR组合优于简单减仓" if control["max_drawdown"]>chosen["max_drawdown"] and control["total_return"]>chosen["total_return"] else
                  "冻结方案没有同时在收益和回撤上胜过固定半仓参照")
    report=f"""# 穿石 Stoneflow：全股票池突破策略研究报告


## 研究问题与结论

在老师指定的 **2025-01-02至2026-09-30，424个交易日**，延续20日突破，研究成交额确认、流动性与趋势过滤、ATR仓位和退出能否改善表现。股票池使用课程5,451列证券，每日按历史状态和已有行情判断资格，排除ST／*ST和未知状态的新买入。它不是经证明完整的历史A股全市场名单。

2024年冻结的方案为 **{chosen['strategy']}**。评价期累计收益 **{percent(chosen['total_return'])}**、最大回撤 **{percent(chosen['max_drawdown'])}**；普通突破为 **{percent(base['total_return'])}**、**{percent(base['max_drawdown'])}**。减少回撤的同时，冻结方案仍然亏损，不能把风险下降写成已经找到盈利策略。

冻结方案平均仓位为 **{percent(chosen['average_exposure'])}**，普通突破为 **{percent(base['average_exposure'])}**。因此补做固定半仓参照：其收益 **{percent(control['total_return'])}**、回撤 **{percent(control['max_drawdown'])}**。**{half_verdict}**，不能把少持仓带来的风险下降全归功于更好的选股或止损。

本次是2026年10月整理的回顾性研究，已经看过此前5DR、个股及突破试跑结果。虽然正式候选仅用2024选型，2025—2026不再选冠军，仍不能称为真正盲测或2024年实际预注册。固定半仓诊断是在观察试跑后追加的，明确不参与选型。

## 从两只股票到全股票池

原研究让长源东谷603950.SH、科大讯飞002230.SZ各用独立子账户。本次用一个100万元组合账户研究同一规则在课程全池中的表现，补充组合容量、信号排序、退出重试和现金管理。原两股同区间对照继续保存在5DR研究报告，不用它们推断全池结论。

- 入场：今日复权收盘价严格高于此前20日最高复权high，窗口不含今天。
- 退出：今日复权收盘价严格低于此前10日最低复权low，窗口不含今天。
- high、low、close均乘对应日期cumadj；amt是成交额，不是成交股数。
- 最多20只实际持仓，新买入单只最多占信号日权益4.75%；买入预算最多为95%权益减去所有非现金权益。股利应收、缺价旧估值和未卖掉的仓位都不能当作可用现金。
- 机会超过名额时，按“复权收盘／此前20日最高价”从大到小排序，同分按代码。它是显式的组合构建约定，不保证最优。
- 维持已有实际股数，不做每日等权重置，不补齐部分成交。已有持仓上涨后仓位可自然超过初始95%。
- 卖出失败或部分成交后，退出意图持续保留，直至真实模拟股数归零；退出中的持仓仍占名额。未买到的信号只在新一天条件仍成立时再尝试，不假设已经建仓。
- 新买要求最近61日中至少60个有效收盘、已知非ST且可交易、当日成交额与笔数为正。持有后成为ST则尝试退出，停牌或跌停仍可能暂时留下。冻结方案含ST持仓的日期为{still_st}日，已成交ST／未知状态买单为{st_buys}笔。

## 五个固定候选

| 方案 | 相对上一版增加什么 | 研究假设 |
| --- | --- | --- |
| 普通20日突破 | 20日高点买入、10日低点退出 | 价格突破后趋势延续 |
| 成交额确认 | 今日amt > 此前20日平均amt × 1.5 | 交易活跃的突破更可靠 |
| 流动性过滤 | 此前20日均成交额≥2,000万元、原始收盘≥3元 | 过滤低流动性与低价信号 |
| 趋势过滤 | 复权close > MA60 且 MA20 > MA60 | 顺着较长趋势入场 |
| ATR仓位与退出 | 按波动缩小入场仓位，另加3ATR收盘退出 | 控制高波动仓位与回吐 |

流动性和趋势条件只限制新买，不因成交额暂时回落而单独强平。均线包含已知的当日收盘；成交额参考均值不包含当天。

ATR14为截至信号日的14个复权真实波幅的简单平均；单日真实波幅取high−low、|high−前收|、|low−前收|三者最大。防守版入场权重为min(4.75%, 0.1% ÷ (ATR14／复权close))。每只股票首次实际持有后开始记录最高已观察复权收盘；当收盘低于该峰值−3×当日ATR14时，也触发持续退出。

这里的0.1%是波动预算参数，不是最大亏损保证。所有退出都在收盘形成信号，下一交易日按统一开盘成交代理执行；跳空、跌停、锁股可能扩大损失，没有假设能按盘中止损价卖出。

## 2024选型

选择分数=2024年化收益／(|2024最大回撤|+0.05)，取最高者，同分按key。五个候选及规则先记录在protocol.json，正式评价期不重新选择。规则与数据修复、来源核对相互独立；数据修复不改策略阈值。

{training}

若所有候选在2024年均亏损，这个排序只能选出该规则下相对损失较小的候选，不能说明存在正收益证据。持币的无息名义收益为0，也必须作为解释结果的参照。

## 老师指定区间的实际结果

{evaluation}

{periods}

所有候选都保留，评价期表现相对较好的确认与流动性版也只作为描述，不能在看完这段结果后替换冻结方案，再把同一段称作样本外验证。年内收益使用连续账户该段开始前的权益为基点，回撤在展示区间重新计算；期末按收盘估值，没有强制清仓。

## 回撤改善是否只是因为减仓

{control_table}

固定半仓参照保留普通突破全部信号与排序，将组合新买预算由95%降至47.5%，单只上限由4.75%降至2.375%，实际逐笔撮合。它不是把原净值曲线简单乘0.5。该诊断是在试跑后追加的解释性比较，未参与2024选型；也没有把它的仓位调到与防守版平均仓位完全相同。

{half_verdict}。仓位和交易路径不同，只能说明本次观察，不能从这一次比较单独识别ATR仓位、趋势过滤、成交额过滤、退出规则各自的因果贡献。若继续研究，应在新的未查看区间预先固定消融实验，逐项替换，不能继续在本评价段扫描参数。

## 成交假设收紧

{stress}

双倍成本同时改变佣金比例、最低佣金、印花税、过户费、滑点；容量使用信号日已知的近20日均成交额，默认1%，压力情景为0.1%。现金、整手、拒单和持仓路径会随情景改变，收益不保证单调变化。

## 与5DR放在一起看

{overall}

两组使用同一评价区间、原始股份账户、初始100万元、ST与成交限制。5DR每日目标等权会产生较高换手；突破保留股数、退出后补新机会，不能仅凭最终收益把两种家族排序为普适优劣。5DR冻结方案2026年前三季度亏损20.71%，双倍费用滑点后全期只剩0.73%，原风险结论保持不变。

## 账户精度与来源

前一日收盘固定原始订单股数，次日先卖后买，按开盘价加不利滑点、取到分执行。涨停不能买，跌停不能卖；除权日取消旧数量计划。历史非ST主板通常10%，创业板／科创板20%；主板ST卖单的历史比例按2026-07-06的规则变更处理。主板／创业板按100股单位，科创板买入至少200股、其后1股；T+1、送转锁股、最低佣金均纳入。

现金分红按登记日持股确认，应收款在派息日到账；统一预扣20%是保守教学假设，不是逐笔持有期个税的精确复现。送转新增股份向下取整，冻结方案有{assumed}条缺股份上市日而以除权日代替的记录。连续缺价20日减记为零，保留股份与现金账；冻结方案缺价持仓日期{chosen['stale_valuation_days']}日、期末减记残留{chosen['ending_impaired_positions']}只。

新增核对贝仕达克2024、天山电子2026、嘉元科技2026三笔差异化分红送转：账户仍按普通持有人实际比例记现金和股份；仅参考价校验使用公告摊薄比例，不放宽误差阈值。摘要、公告日、生效日与原始文件链接保存在reference/breakout_corporate_reference_overrides.json。

- [贝仕达克实施公告：普通分配与摊薄比例](https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-31/81ad32a4-8371-4dfb-bdb2-4e66338e40af.PDF)
- [天山电子实施公告：普通分配与摊薄比例](https://static.cninfo.com.cn/finalpage/2026-05-28/1225333668.PDF)
- [嘉元科技实施公告原文：差异化分配参考价](https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2026/2026-6/2026-06-10/12382204.PDF)

辅助历史状态与课程有效收盘共核对{s['data_audit']['raw_close_compared']:,}格，超过0.005元差异为{s['data_audit']['raw_close_mismatched']:,}格。有成交报价的状态覆盖率为{percent(s['precision_audit']['known_state_coverage'])}；未知状态不当作非ST。

历史ST只有生效日资料，假设盘前可知，没有逐条复原公告发布时间与数据版本。前收与板块规则重建的限价不是官方逐日限价文件，日线开盘加滑点不能证明盘口排队成交。全天无成交、滑点价超当日高低价仅用于否决不可行成交。特殊无涨跌幅事件、配股／重整、真实个税与零股分配仍未完全覆盖，不能声称精确实盘复现。

## 校验与复现

**主研究当时保存的{test_count}项单元测试通过。** 本次突破{v['runs_checked']}组运行通过独立CSV账本重放，{v['checks']:,}个记账断言；与原5DR的{v5['runs_checked']}组共{v['runs_checked']+v5['runs_checked']}组。扩展研究的新增账户与当前测试数量另列在扩展章节。独立脚本不调用撮合引擎，检查现金、原始股数、股利应收、权益、费用、ST买单与成交边界。断言数量不是单元测试数量，也不等于真实市场成交已经得到证明。

完整重跑步骤见docs/PRECISION_BREAKOUT.md。结果保存在results/breakout_review，5DR结果保持原目录；两组均保存参数、来源哈希与实际逐日账本。课程Feather和辅助源缓存不上传，本次只有代码、报告与派生结果。

"""
    analysis_path=ROOT/'results/strategy_analysis/report_fragment.md'
    if analysis_path.exists():
        report=report.replace('## 账户精度与来源',analysis_path.read_text()+'\n\n## 账户精度与来源')
    (ROOT/"REVIEW_BREAKOUT.md").write_text(report)
    series=[]
    for key,color,title in (("base","#93a485","普通突破"),(s["selected_key"],"#b56b45","2024冻结方案")):
        series.append((pd.read_csv(RESULTS/"evaluation"/key/"equity.csv").net_value.tolist(),color,title))
    series.append((pd.read_csv(RESULTS/"diagnostic/half_exposure/equity.csv").net_value.tolist(),"#8f8a81","固定半仓参照"))
    if s.get("benchmark"):series.append(([x["net_value"] for x in s["benchmark"]],"#526e78","沪深300价格指数"))
    values=[x for seq,_,_ in series for x in seq]+[1];lo=min(values)*.95;hi=max(values)*1.05
    chart='<svg viewBox="0 0 1000 300" role="img" aria-label="突破策略净值比较">'
    for seq,color,title in series:
        points=' '.join(f'{45+i*935/(len(seq)-1):.2f},{15+(hi-x)*245/(hi-lo):.2f}' for i,x in enumerate(seq))
        chart+=f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{points}"><title>{title}</title></polyline>'
    chart+='<text x="45" y="285">2025-01-02</text><text x="980" y="285" text-anchor="end">2026-09-30</text></svg>'
    chart+='<p>'+''.join(f'<span style="color:{c};margin-right:20px">━ {t}</span>' for _,c,t in series)+'</p>'
    body=render_markdown(report).replace('<h2>老师指定区间的实际结果</h2>','<h2>老师指定区间的实际结果</h2>'+chart)
    body=body.replace('<h2>策略差异与适用股票：扩展研究</h2>','<h2 id="strategy-analysis">策略差异与适用股票：扩展研究</h2>')
    group_chart=ROOT/'results/strategy_analysis/group_chart.svg'
    if group_chart.exists():
        body=body.replace('<h3>三、是否适用于部分股票：用2024资料固定子集</h3>','<h3>三、是否适用于部分股票：用2024资料固定子集</h3>'+group_chart.read_text())
    css="body{max-width:1080px;margin:40px auto;padding:0 25px;background:#f4f1e9;color:#2f4438;font:14px/1.9 -apple-system,'PingFang SC',sans-serif}h1,h2{font-family:'Songti SC',serif}h1{font-size:30px}h2{margin-top:35px;font-size:23px}blockquote{border-left:3px solid #b56b45;background:#e8ecde;padding:12px 18px}a{color:#567c67}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}td,th{padding:10px 12px;border-bottom:1px solid #dce1d1;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e9eddf}svg{width:100%;height:auto}svg text{font:12px sans-serif;fill:#7a8575}.item{margin-left:15px}code{background:#e5e9dc;padding:2px 4px}"
    (RESULTS/"report.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>穿石 · 全池突破审核</title><style>'+css+'</style><body>'+body+'</body></html>')
    combined=f"""# 穿石 Stoneflow：全股票池策略研究总览

本次范围：**2025-01-02 → 2026-09-30（424个交易日）**；课程5,451列证券的逐日可用股票池，历史ST／*ST及未知状态不新买。所有价格信号使用cumadj，次日执行，涨停拒买、跌停拒卖，原始股份和现金分别记账。

## 主要结果

{overall}

5DR流动性版比基础版改善，但仍有47.17%的最大回撤；2026年前三季度亏损20.71%，成本加倍全期只剩0.73%。不能仅引用37.55%的累计收益。

突破防守版减少基础版的损失和回撤，但仍亏损。其平均仓位{percent(chosen['average_exposure'])}，固定半仓普通突破的收益{percent(control['total_return'])}、回撤{percent(control['max_drawdown'])}；{half_verdict}。本作业保留失败与限制，没有把评价期冠军重新包装成样本外方案。

## 报告入口

- [5DR完整报告](REVIEW_5DR.md)
- [全池20日突破完整报告](REVIEW_BREAKOUT.md)
- [5DR复现与精度说明](docs/PRECISION_5DR.md)
- [突破复现与精度说明](docs/PRECISION_BREAKOUT.md)
- [拟提交课程评论](SUBMISSION_LECTURE4_DRAFT.md)

网页运行后访问`/5dr`与`/breakout`；不依赖原始数据阅读的离线页面为`results/5dr_review/report.html`与`results/breakout_review/report.html`。

## 完成度与限制

回测系统支持任意Python状态型策略、模拟时钟与券商、订单／持仓／现金记录；新突破实现用退出意图和实际持仓展示了可扩展性。当前是日频多头目标仓位系统，未包含盘中委托撤改、保证金或真实券商接入。

{test_count}项单元测试通过，{v['runs_checked']+v5['runs_checked']}组运行通过独立账本重放。新突破{v['checks']:,}个、5DR{v5['checks']:,}个记账断言；原始数据不上传。

ST公告时点、真实盘口、官方逐日限价、个税和特殊公司行为仍有数据与模型限制。规则在2026年回顾整理，2024选型只是时间隔离，不能称为真实前瞻预注册。原始个股旧实验保持可读，不与新账户结果拼接。

"""
    if analysis_path.exists():
        combined=combined.replace('## 报告入口','## 新增：策略差异与适用股票\n\n已补充实际账户损益归因、共同股票池信号检验、2024固定特征分组、2025选组后2026重新建账，以及正负贡献股票。\n\n[扩展研究全文](ANALYSIS_STRATEGIES.md)；原主研究39组与新增17组账户分开校验。新增分析为回顾研究，不包装成盲测。\n\n## 报告入口')
        combined=combined.replace(f'{test_count}项单元测试通过，',f'主研究当时保存的{test_count}项单元测试通过，')
        analysis_tests=(ROOT/'results/strategy_analysis/unit_tests.txt').read_text()
        current_tests=int(re.search(r'Ran (\d+) tests',analysis_tests).group(1))
        combined=combined.replace('原始数据不上传。',f'原始数据不上传。扩展研究后，全仓库{current_tests}项测试通过，新增17组账户账本重放另行保存。')
    (ROOT/"REVIEW_LECTURE4.md").write_text(combined)
    comment=f"""第四讲作业更新：**穿石 Stoneflow — 全股票池5DR与趋势突破研究**

仓库：https://github.com/Chuboxiao/stoneflow-quant

按老师指定区间 **2025-01-02至2026-09-30（424日）**，对课程5,451列证券动态筛选，排除历史ST／*ST和未知状态新买入。cumadj统一信号口径，收盘固定股数、次日执行，涨停拒买、跌停拒卖；原始股份、现金、分红应收、送转锁股分别记账。

5DR比较基础与4个改进，仅用2024选出流动性版：评价期收益37.55%、最大回撤-47.17%；基础版2.76%、-56.50%。冻结方案2026年前三季度亏损20.71%，双倍税费滑点后全期仅0.73%。

延续20日突破，比较成交额确认、流动性、趋势与ATR控制。2024冻结的**{chosen['strategy']}**评价期收益{percent(chosen['total_return'])}、回撤{percent(chosen['max_drawdown'])}；普通突破为{percent(base['total_return'])}、{percent(base['max_drawdown'])}。同时提供固定半仓参照，避免把减仓效果误认为选股优势；保留全部候选、分年与压力结果。

{test_count}项单元测试、{v['runs_checked']+v5['runs_checked']}组独立账本重放通过。研究属于回顾性的时间隔离，日线成交、ST生效时点、个税与特殊公司行为有明确限制，不声称精确实盘复现。课程和辅助源数据不上传。

[总审核报告](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_LECTURE4.md) · [突破报告](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_BREAKOUT.md) · [5DR报告](https://github.com/Chuboxiao/stoneflow-quant/blob/main/REVIEW_5DR.md)

![穿石全池突破研究工作台](https://raw.githubusercontent.com/Chuboxiao/stoneflow-quant/main/docs/stoneflow-breakout-review.jpg)
"""
    # The user may edit their submission draft between report builds.
    comment_path=ROOT/"SUBMISSION_LECTURE4_DRAFT.md"
    if not comment_path.exists():comment_path.write_text(comment)


if __name__=="__main__":main()
