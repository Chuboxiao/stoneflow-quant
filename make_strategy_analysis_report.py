"""Turn saved, validated mechanism/sub-universe experiments into review content."""
import html
import json
from pathlib import Path
import re
from make_5dr_report import md_table,render_markdown,percent,number

ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/'results/strategy_analysis'


def chart(rows):
    width=900;left=225;right=115;plot=width-left-right
    low=min(0,min(r['total_return'] for r in rows))-.04
    high=max(0,max(r['total_return'] for r in rows))+.04
    x=lambda v:left+(v-low)/(high-low)*plot
    svg=f'<svg class="analysis-chart" viewBox="0 0 {width} {len(rows)*45+45}" role="img" aria-label="2024固定分组的突破策略累计收益"><line x1="{x(0)}" y1="8" x2="{x(0)}" y2="{len(rows)*45+10}" stroke="#cbd2bf"/>'
    for i,r in enumerate(rows):
        y=12+i*45;v=r['total_return'];a,b=sorted([x(0),x(v)])
        svg+=f'<text x="{left-15}" y="{y+18}" text-anchor="end">{html.escape(r["title"])}</text><rect x="{a}" y="{y+2}" width="{max(b-a,1)}" height="24" rx="2" fill="{"#b56b45" if v>=0 else "#8b9d89"}"/><text x="{width-15}" y="{y+18}" text-anchor="end">{percent(v)}</text>'
    return svg+'</svg>'


def main():
    read=lambda name:json.loads((RESULTS/name).read_text())
    if read('run_status.json')['status']!='COMPLETE':raise ValueError('Research incomplete')
    s=read('summary.json');v=read('validation.json')
    if not v['passed']:raise ValueError('Unvalidated ledgers')
    f=s['attribution']['five_dr'];b=s['attribution']['breakout'];groups=s['comparison']
    selected=next(x for x in groups if x['key']==s['selected_key_2025']) if s['selected_key_2025']!='cash' else None
    high=next(x for x in groups if x['key']=='vol_high');control=next(x for x in groups if x['key']=='frozen_all')
    fresh=next(x for x in s['fresh_2026'] if x['case']=='selected')
    selected_title=selected['title'] if selected else '持币'
    years={(x['key'],x['period']):x for x in s['periods']}
    stress={x['key']:x for x in s['stress']}
    title={'five_dr':'5DR＋流动性','breakout':'最强20个突破信号','all_breakouts':'全部突破信号','universe':'共同股票池等权报价'}
    signals={(x['signal'],x['horizon']):x for x in s['signal_study']}
    ci=lambda x:f"[{percent(x['low'])}, {percent(x['high'])}]"
    pnl_table=md_table(['实际账户','累计净收益','税费／初始资金','滑点价差／初始资金','固定成交路径加回二者'],
        [[name,percent(r['metrics']['total_return']),percent(r['fees_initial_capital']),percent(r['slippage_on_actual_fills_initial']),percent(r['fixed_fill_path_addback_return'])] for name,r in [('5DR＋流动性',f),('普通20日突破',b)]])
    spells=md_table(['实际账户','完整平仓段','盈利比例','平均盈利段收益','平均亏损段收益','中位持仓日','盈利金额／亏损金额'],
        [[name,r['closed_spells'],percent(r['win_rate']),percent(r['mean_win_return']),percent(r['mean_loss_return']),f"{r['median_holding_sessions']:.0f}",f"{r['profit_factor']:.3f}"] for name,r in [('5DR＋流动性',f),('普通20日突破',b)]])
    event_table=md_table(['信号','持有日数','有效信号日','平均后续报价收益','相对同日股票池','日期区块95%区间','未能观察退出的记录'],
        [[title[x['signal']],x['horizon'],x['days'],percent(x['mean_forward_return']),percent(x['mean']),ci(x),x['unresolved_exits']] for x in s['signal_study'] if x['signal'] in {'five_dr','breakout','all_breakouts'}])
    group_table=md_table(['2024固定子集','股票数','全期收益','最大回撤','2025收益','2026连续账户收益','双倍成本全期'],
        [[x['title']+('【2025选组】' if x['key']==s['selected_key_2025'] else ''),x['pool_size_at_freeze'],percent(x['total_return']),percent(x['max_drawdown']),percent(years[(x['key'],'2025')]['total_return']),percent(years[(x['key'],'2026年前三季度')]['total_return']),percent(stress[x['key']]['total_return'])] for x in groups])
    fresh_table=md_table(['2026首个交易日重新建账','累计收益','最大回撤'],
        [[x['title']+(f"：{selected_title}" if x['case']=='selected' else ''),percent(x['total_return']),percent(x['max_drawdown'])] for x in s['fresh_2026']])
    contributions=md_table(['普通突破的实际交易股票','累计净贡献（元）','对初始100万元贡献','解释'],
        [[x['symbol'],number(x['net_pnl']),percent(x['contribution_initial_capital']),'事后归因，非事前推荐'] for x in b['top']+b['bottom']])
    regime=md_table(['按前一日指数定义状态','交易日数','5DR净损益贡献／初始资金','突破净损益贡献／初始资金'],
        [[x['regime'],x['days'],percent(x['pnl_contribution']),percent(b['regimes'][i]['pnl_contribution'])] for i,x in enumerate(f['regimes'])])
    h5=signals[('five_dr',5)];bh5=signals[('breakout',5)];spread5=signals[('five_dr_minus_breakout',5)]
    thresholds=s['protocol']['thresholds']
    log=(RESULTS/'unit_tests.txt').read_text();test_count=int(re.search(r'Ran (\d+) tests',log).group(1))
    report=f"""## 策略差异与适用股票：扩展研究

### 先修正“5DR有效”的说法

这里“有效”至少有三层含义：本次模拟净收益为正；超过合适的市场参照；在不同年份、股票组和费用下仍能延续。**目前仅能确认5DR流动性版在本区间净赚37.55%，不能从这一个数证明后两层。** 它2026年前三季度亏损20.71%，双倍费用滑点后全期仅0.73%，都是这句话的边界。

本节在已有2025—2026结果看过之后追加，属于解释性回顾研究。原始5DR、突破策略、账户和结果均保持不变。新增内容分开检验价格信号、真实账户损益、事前可定义股票子集，避免把不同问题混成一个结论。

### 一、为什么这段样本里5DR胜过普通突破

5DR买近期相对弱势股票，研究短期价格回补；突破买超过近期高点的股票，研究趋势延续。短期反转与流动性供给补偿是已有研究提出的机制解释，但本数据没有订单流、新闻或持有人交易资料，不能直接证明是该机制导致收益。[Nagel：Evaporating Liquidity](https://www.nber.org/papers/w17653)

趋势研究也不等于任何追涨规则都能赚钱。例如Moskowitz、Ooi、Pedersen研究的是跨市场期货／远期、较长回看期的时间序列动量；不能把其结论直接搬到A股单个股票的20日通道。[Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)

对我们自己的样本，证据更具体：

- **买入位置不同。** 真实已成交持仓段的首次买入，普通突破从信号收盘到次日开盘平均跳升{percent(b['mean_entry_gap'])}，5DR平均为{percent(f['mean_entry_gap'])}。这是实际成交样本的价格变化，不是费用；突破策略往往付出了更高的入场位置。这个差别也受股票池与成交筛选影响，不能当作单一因果效应。
- **盈利结构不同。** 普通突破{b['closed_spells']}个完整平仓段中，盈利比例仅{percent(b['win_rate'])}；平均盈利段{percent(b['mean_win_return'])}、平均亏损段{percent(b['mean_loss_return'])}。虽然大盈利幅度较大，但盈利金额／亏损金额只有{b['profit_factor']:.3f}，未覆盖亏损。5DR该比值为{f['profit_factor']:.3f}，优势较薄。
- **出现短期回落。** 在有完整后续5日报价的{b['fallback5_observations']}个实际入场段中，{percent(b['fallback5_fraction'])}曾在5日内收盘回到信号当时的原20日通道上沿或以下。这是“快速跌回突破线”的操作定义，不等于这些交易最终必亏，也不能解释全部损失。
- **并非只有费用拖累突破。** 对实际已成交路径加回税费与滑点价差，普通突破仍为{percent(b['fixed_fill_path_addback_return'])}。5DR的交易摩擦很重，但普通突破的负收益不能只归结于费用。
- **行情状态不同。** 以前一日沪深300是否在MA60之上划分状态，突破在指数较弱状态中的账户损失，超过较强状态中的收益；5DR表现出不同的损益分布。这里只描述已发生账本，没有据此补做或宣称择时策略已验证。

{spells}

“持仓段”指实际股数持续为正的一段，包含真实清仓日；净损益由每日市值变动、交易现金、股利权利与费用归集，晚到账股利归回登记日所属持仓段。期末仍持有的段不混入完整平仓胜率。段收益分母为该段实际买入现金（含买费），不是组合收益；盈利金额比与平均百分比不必直接相除。

{pnl_table}

最后一列只是**固定原已成交路径的损益加回核算**，不是“零费用重新回测”的收益。实际去掉费用会改变现金、整手数量、后续股票和拒单，因此不能用这个加回数字宣传5DR真实毛收益率。滑点价差按实际股数乘成交价与原开盘的差额统计，包含取整到分的影响；它与税费分开，股利税未加回。

{regime}

这里的贡献是相应日期净损益之和／初始资金，两个状态的贡献可相加为全期收益；不是分状态资金账户的复利收益，也不能推断所有下跌行情都适合5DR。

### 二、把信号放进共同股票池再检查

为隔离原两组股票池和持有期差别，取共同的当日非ST／状态明确、至少60日历史、近20日报价有效、原价≥3元、近20日均成交额≥2,000万元且当日有成交的股票。收盘选最低5DR20只、突破幅度最大的最多20只，并保留全部突破信号作排序对照；同日可用股票池的等权报价作为比较基准。

从下一交易日开盘报价，观察再过1、5、20个交易日的复权开盘报价变化。入场采用原引擎同类的ST、停牌、涨停、除权取消与价格范围否决；不补选被拒的候选。所有前瞻标签止于2026-09-30，完全不用十月数据。

{event_table}

5日持有下，5DR信号的平均后续报价收益为{percent(h5['mean_forward_return'])}，最强突破信号为{percent(bh5['mean_forward_return'])}；但5DR相对同日股票池的均值为{percent(h5['mean'])}，区间{ci(h5)}，**没有支持稳定正超额**。5DR减最强突破的同日5日信号差为{percent(spread5['mean'])}，区间{ci(spread5)}，只能说明本样本两种信号的相对差别。

这是价格事件研究，不是实际可成交账户：未计算整数股、现金、退出涨跌停、费用与个人股利税，不同信号的数量也可能不同。未观察到可交易退出报价的记录分别计数，另保存“未解决记录按零回收”敏感性，不能用未来可卖出这一条件倒过来筛股票。普通报价均值也不是可交易指数。

均值按有效信号日等权，信号股票数不影响日期权重；没有相应可观察信号的日期不计入该均值。区间做1,500次、每块20个有效信号日期的循环区块重采样，保留持有期重叠的部分相关性；无信号日期会造成日历间隔，并非严格20个连续市场交易日。不是把几百万证券日当成独立样本。区间未经多重比较校正，行情非平稳性也会影响解释，只作描述证据。逐日期统计保存于signal_cohorts.csv。

当前普通突破组合还有一个重要实现约定：同时出现很多信号时只取**突破幅度最强**的候选，再受已有持仓、现金和20只名额限制。因此这里失败的是这一具体组合规则，不能据此推断所有20日突破实现均无效。全部突破与最强突破的报价对照，用于检查排序是否带来额外的追高倾向，不据结果立即重新优化排序。

### 三、是否适用于部分股票：用2024资料固定子集

答案是：**本样本内，存在预先按历史特征定义、跑出正净收益的股票子集；还没有证据证明某张个股名单永久适用。**

在2024-12-31冻结分组，要求2024年至少180个有效收盘、特征可计算、年末状态明确非ST且有正常报价。共{control['pool_size_at_freeze']:,}只符合条件。不能用2026年末仍存在的股票反向筛2024名单；2025／2026新上市或2024历史不足的股票不在这些固定组里。所有组在评价期仍逐日排除ST和未知状态新买入。

- 趋势效率ER60 = |今日复权价−60日前复权价| ÷ 最近60日绝对价格变化之和，再取2024日值均值。中位数为{thresholds['efficiency60_2024']:.4f}。它衡量路径是否顺畅，不区分向上或向下，不能叫“上涨趋势股”。
- 波动 = 最近20日复权日收益标准差，再取2024日值均值；中位数为每日{percent(thresholds['volatility20_2024'])}。高／低波动按此分界固定，不看2025—2026收益。
- 流动性 = 2024年日成交额均值，中位数约{thresholds['mean_amount_2024']/1e8:.2f}亿元。它不是市值，不能把“成交额高”改称“大盘股”。本数据没有行业／市值字段，本次不编造行业适用性结论。

每组都运行同一普通20／10突破规则、100万元账户、最多20只、相同费用和成交限制。先看“2024可观察全组”作为匹配对照，再比较特征组；原5,451列全池的-23.19%另保留，名单可观察性的差异也会改变结果。

{group_table}

**2024高波动组**全期净收益为{percent(high['total_return'])}、最大回撤{percent(high['max_drawdown'])}；匹配全组收益{percent(control['total_return'])}。高波动组2025年{percent(years[('vol_high','2025')]['total_return'])}、2026连续账户{percent(years[('vol_high','2026年前三季度')]['total_return'])}，双倍成本全期{percent(stress['vol_high']['total_return'])}。这支持继续研究该类子集，却不支持“高波动一定适合突破”。高趋势效率、低波动等直觉分组并没有在这里普遍改善结果，失败组也全部展示。

这些组存在交集，7次比较增加了偶然找到赢家的机会；我们已经看过这段历史，不把最高的全期收益改称新样本外最优策略。双倍费用还会改变现金和路径，个别组加费后收益反而更高，不意味着交易费用有利。

### 四、只用2025选组，2026再开一个新账户

按固定规则，在2025年收益为正的候选里，选择“2025年化收益／(|回撤|+0.05)”最高者；同分按key，若均不正则持币。选出的是 **{selected_title}**。然后在2026首个交易日重新以100万元、无期初持仓启动，比较选中组、匹配全组、课程全池；信号可用前一交易日数据。

{fresh_table}

选中组2026重新建账收益仅{percent(fresh['total_return'])}，最大回撤{percent(fresh['max_drawdown'])}。它与2025开始连续持仓账户的2026分段不同，说明建仓时点、期初持仓与现金路径很重要。正的小收益和较大回撤不足以认定稳健优势；本步骤仍是回顾性滚动模拟，不是真正未看过的2026盲测。

### 五、具体股票：先做归因，再谈适用

普通突破实际交易涉及{b['traded_symbols']}只股票，其中{b['positive_symbols']}只净贡献为正、{b['negative_symbols']}只为负。下面展示前5和后5的实际组合贡献；股数、成交时点和公司行为都来自原账本。

{contributions}

这是事后归因，不是建议下一次就只买这些代码。它们的组合贡献不等于从期初独立跑该股票策略的收益，删除亏损股也会改变现金、排序与买卖时点。两只最初关注股票的独立账户仍在原报告：普通突破在长源东谷为-10.39%、科大讯飞为-7.95%，也说明不能只用一两只例子推断全池。

### 这次作业可以怎样下结论

在指定样本中，近期弱势股与最强突破股呈现不同后续价格路径；5DR实际持仓更短，盈利金额略覆盖亏损，而普通突破较低的胜率与较长亏损暴露使总账为负。5DR本次盈利不能直接等同于独立超额，突破本次亏损也不能等同于所有股票、所有阶段不适用。

用2024已知特征划定的高波动股票组，在同一突破规则下取得正净收益；2025选组后2026重新建账优势很弱。更可靠的后续研究应预先冻结分组与排序，在新的未查看区间检验，并比较同风险／同仓位的基准，不能继续用本评价段挑股票调参数。

### 新增校验、来源与复现

新增{v['runs_checked']}组真实账户通过独立现金／原始股数／应收／权益重放，{v['checks']:,}个记账断言。每日股票损益与原账户逐日权益变动的最大对账误差：5DR {f['account_reconciliation_error']:.10f}元，突破{b['account_reconciliation_error']:.10f}元。当前全仓库{test_count}项单元测试通过，包括未来数据不改变2024分组、组别分割、重采样可重复、迟到账股利归属和初始资金回撤。

原两项主研究39组与新增{v['runs_checked']}组分开保存。公司行为参考比例新增核对6条公司公告，见reference/analysis_corporate_reference_overrides.json；实际到账比例不变，不靠放宽容差跳过数据差异。

```bash
python strategy_analysis.py --data-dir /你的路径/feathers --output work/analysis_discovery --provisional
python tools/fetch_actions.py --requests work/analysis_discovery/needed_actions.json
# 核对缺失事件与参考价差异，再正式运行
python strategy_analysis.py --data-dir /你的路径/feathers
python validate_5dr.py --results results/strategy_analysis
python -m unittest discover -s tests -v > results/strategy_analysis/unit_tests.txt 2>&1
python make_strategy_analysis_report.py
python make_breakout_report.py
```

新增代码与派生输出保存于results/strategy_analysis，原始行情与辅助源缓存不上传。沿用原报告的ST公告时点、日线成交代理、个税和特殊公司行为限制。当前仍待审核，没有推送或更新课程评论。
"""
    (ROOT/'ANALYSIS_STRATEGIES.md').write_text('# 5DR与20日突破：收益来源及适用股票研究\n\n'+report)
    (RESULTS/'report_fragment.md').write_text(report)
    (RESULTS/'group_chart.svg').write_text(chart(groups))
    css="body{max-width:1250px;margin:40px auto;padding:0 30px;background:#f4f1e9;color:#2f4438;font:14px/1.9 -apple-system,'PingFang SC',sans-serif}h1,h2,h3{font-family:'Songti SC',serif}h1{font-size:32px}h2{font-size:27px}h3{font-size:22px;margin-top:35px}.table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}td,th{padding:11px;border-bottom:1px solid #d6ddcc;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e8edde}a{color:#b56b45}.item{margin-left:12px}pre{white-space:pre-wrap;background:#e8edde;padding:15px}.analysis-chart{width:100%;max-width:900px}.analysis-chart text{font:14px -apple-system,'PingFang SC',sans-serif;fill:#53664a}"
    body=render_markdown('# 5DR与20日突破：收益来源及适用股票研究\n\n'+report)
    body=body.replace('<h3>三、是否适用于部分股票：用2024资料固定子集</h3>','<h3>三、是否适用于部分股票：用2024资料固定子集</h3>'+chart(groups))
    (RESULTS/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>穿石 · 策略差异与适用股票</title><style>'+css+'</style><body>'+body+'</body></html>')
    # Native details work without a new API or third-party assets; the local server
    # reads this generated HTML on each request, including existing open ports.
    section='<section id="strategy-analysis" class="analysis-study"><p class="eyebrow">WHY IT WORKS / WHERE IT FAILS</p><h2>收益之外，再追问一步。</h2>'
    section+='<p class="analysis-lead">5DR样本盈利，不等于已证明独立超额；突破样本亏损，也不等于所有股票都不适用。</p>'
    section+=f'<div class="analysis-insights"><article><strong>{percent(b["win_rate"])}</strong><span>普通突破平仓段盈利比例</span><p>较大的盈利未覆盖多数亏损；持仓段盈利金额／亏损金额为{b["profit_factor"]:.3f}。</p></article><article><strong>{percent(high["total_return"])}</strong><span>2024高波动固定组 · 全期收益</span><p>最大回撤{percent(high["max_drawdown"])}，双倍成本后{percent(stress["vol_high"]["total_return"])}；其余失败分组同时保留。</p></article><article><strong>{percent(fresh["total_return"])}</strong><span>2025选组 → 2026重新建账</span><p>最大回撤{percent(fresh["max_drawdown"])}，跨期优势仍弱，不能直接当作稳定适用名单。</p></article></div>'
    section+='<details open><summary>哪些股票子集更适合？查看7组同规则实测</summary>'+chart(groups)+'<div class="table-wrap">'+render_markdown(group_table)+'</div><p class="caption">分组仅用2024信息；特征组互有交集。2025选组规则只看2025，追加研究整体仍属回顾分析。</p></details>'
    section+='<details><summary>为什么5DR好于突破？查看持仓段与成本归因</summary><div class="table-wrap">'+render_markdown(spells+'\n\n'+pnl_table)+'</div><p class="caption">费用加回保持原成交路径，只是损益核算，不能当作零成本重跑的收益。期末未平仓段不混入胜率。</p></details>'
    section+='<details><summary>信号本身有优势吗？查看共同股票池的后续报价</summary><div class="table-wrap">'+render_markdown(event_table)+'</div><p class="caption">下一开盘至未来开盘的价格事件研究；日期区块重采样区间未经多重比较校正，不等于可成交账户收益。</p></details>'
    section+=f'<p class="caption">新增{v["runs_checked"]}组账户账本校验通过；全仓库{test_count}项测试通过。主研究结果保留，补充分析仍待审核。</p>'
    section+='<p class="analysis-link"><a href="/breakout-files/report.html#strategy-analysis">阅读全文：归因、分组、跨期验证与具体股票贡献 ↗</a></p></section>'
    (RESULTS/'dashboard_fragment.html').write_text(section)
    page=ROOT/'web/dist/breakout.html';content=page.read_text();start='<!-- STRATEGY_ANALYSIS_START -->';end='<!-- STRATEGY_ANALYSIS_END -->'
    block=start+section+end
    if start in content:content=content[:content.index(start)]+block+content[content.index(end)+len(end):]
    else:content=content.replace('<section class="audit">',block+'<section class="audit">')
    page.write_text(content)


if __name__=='__main__':main()
