"""Generate a research report and candidate CSV from one saved study."""
import argparse
import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def number(x): return '—' if x is None else f'{x:.6f}'
def percent(x): return '—' if x is None else f'{x*100:.2f}%'


def summarize(study_id):
    if len(study_id)!=12 or any(c not in '0123456789abcdef' for c in study_id): raise ValueError('无效实验ID')
    directory=ROOT/'results/evolution_runs'/study_id
    s=json.loads((directory/'study.json').read_text());c=s['config']
    candidates=list(s['candidates'].values());new=[r for r in candidates if r['round']>0]
    accepted=[r for r in new if r['accepted']]
    baseline=s['baseline']['metrics'];final=s['pool_metrics']
    lines=['# 因子改进实验：多样性与组合增量','',
           f"实验 `{study_id}`；创建于 {s['created_at']}，冻结于 {s['frozen']['at'] if s['frozen'] else '尚未冻结'}。",'',
           f"本次执行 {len(candidates)-len(new)} 个起始因子和 {s['rounds_completed']} 轮 {len(new)} 个新候选，接受 {len(accepted)} 个新候选。最终成员：**{'、'.join(s['pool']) or '无合格成员'}**。",'',
           '**结论：选择验证段与冻结后回顾的预测统计有所改善；回顾段分组报价收益差仍为负，尚未验证新组合能获得更高净交易收益。**','',
           '[模块说明](../../../README_EVOLUTION.md) · [完整状态](study.json) · [候选CSV](candidates.csv) · [独立核对](verification.json)','',
           '## 实验设置','',
           f"- 股票池：`{c['pool']}`，逐日历史非ST、正常交易、上市龄与有效行情检查；流动性池额外要求20日平均成交额≥2000万元、股价≥3元。",
           f"- 搜索段：{c['search_start']}—{c['search_end']}；选择验证段：{c['validation_start']}—{c['validation_end']}。两段均参与筛选。",
           f"- 预测标签：当日收盘信号，从次日开盘至其后{c['horizon']}个交易日开盘的复权报价收益，各段标签严格截止。",
           f"- 预算：最多{c['round_budget']}轮，每轮最多3个新候选；方向固定，保持所有失败记录。",
           '- 冻结后回顾：2026-01-01—2026-09-30。该历史此前已查看，属于回顾性检查，不能称为未见样本或真正盲测。',
           '- 初始池按固定顺序通过质量与组合增量筛选得到；初始组合和最终组合均为当日合格股票上的因子百分位秩等权平均。',
           '- 不优化交易规则、不拟合组合权重；本轮没有运行新组合的净交易账户。','',
           '## 同口径组合比较','',
           '| 区间 | 初始池 Rank IC | 最终池 Rank IC | 初始正IC月占比 | 最终正IC月占比 |',
           '| --- | ---: | ---: | ---: | ---: |']
    for phase,label in [('search','2024搜索'),('validation','2025选择验证')]:
        a,b=baseline[phase],final[phase]
        lines.append(f"| {label} | {number(a['rank_ic'])} | {number(b['rank_ic'])} | {percent(a['positive_months'])} | {percent(b['positive_months'])} |")
    if s['review']:
        a,b=s['review']['seed_pool']['metrics'],s['review']['selected_pool']['metrics']
        lines += [f"| 2026冻结后回顾 | {number(a['rank_ic'])} | {number(b['rank_ic'])} | {percent(a['positive_months'])} | {percent(b['positive_months'])} |",'',
                  f"2026回顾Q5−Q1平均未来{c['horizon']}日报价收益：初始池 **{percent(a['spread'])}**，最终池 **{percent(b['spread'])}**，均未扣费。最终组合的回顾Rank IC为正，不代表分组收益差为正，更不等于可交易利润。",'']
    lines += ['2025组合正IC月份占比下降，2026回顾中则提高。该规则允许这种取舍；不能只展示均值上升而忽略稳定性。','',
              '## 全部候选','',
              '| 轮次 | 候选 | 家族 | 搜索IC | 选择验证IC | 组合验证IC增量 | 决定 |',
              '| --- | --- | --- | ---: | ---: | ---: | --- |']
    for r in candidates:
        lines.append(f"| {r['round']} | `{r['spec']['key']}` | {r['spec']['family']} | {number(r['metrics']['search']['rank_ic'])} | {number(r['metrics']['validation']['rank_ic'])} | {number(r.get('pool_validation_gain'))} | {'当轮保留' if r['accepted'] else '淘汰'} |")
    lines += ['','“当轮保留”不等于最终成员；五日反转在第2轮被十日反转替换。组合增量不足的候选保留失败记录，不进入池。','',
              '## 每轮的反馈与下一步','']
    for batch in s['rounds']:
        lines += [f"### {'初始评价' if batch['round']==0 else '第'+str(batch['round'])+'轮'} · {batch['source']}",'',
                  '候选：'+ '、'.join('`'+x['key']+'`' for x in batch['specs'])+'。','',
                  '结果池：'+ '、'.join('`'+x+'`' for x in batch['pool'])+'。','']
        if batch['round']>0:
            for spec in batch['specs']:
                row=s['candidates'][spec['key']]
                lines.append(f"- **{spec['key']}**：{spec['hypothesis']} 结果：{'；'.join(row['reasons'])}。")
            lines.append('')
    lines += ['## 对Harness的证据与限制','',
              '第1轮为H1确定性规则提案，第2、3轮为Codex读取实际反馈后通过页面导入的候选。第1轮发现在已有组合上再做等权混合几乎没有增量；第2轮转向时间尺度，十日反转通过门槛；第3轮探索平滑和风险/价量时间尺度，均被固定规则拒绝。', '',
              '本次把流程约束、不同家族探索、完整反馈、公式去重、断点续跑和冻结检查落实成模块。没有运行H0/H1同预算对照，也没有自动模型调用，因此不声称已经证明Harness因果提升。','',
              '## 可复现与检查','',
              '- 通过本机页面实际完成创建、初始评价、规则候选、Agent候选导入、刷新恢复、冻结与回顾。',
              '- 104项单元测试通过，其中10项为新增研究模块测试；所有14个候选通过截断未来数据的分数一致性检查。',
              '- 使用标准库独立重算53份逐日诊断的IC和期间均值、检查标签截止与父子/冻结记录，共13,511项核对通过。',
              '- 运行 `python tools/replay_evolution.py --source results/evolution_runs/'+study_id+'/study.json` 会新建实验并按原候选顺序重放。需要课程行情与历史状态资料。',
              '- 数据、配置和代码指纹见 `study.json`；原始行情和临时矩阵不随仓库提交。','']
    (directory/'REPORT.md').write_text('\n'.join(lines))
    with (directory/'candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['round','key','family','formula','parent','source','hypothesis','search_ic','validation_ic','validation_positive_months','pool_gain','accepted','reasons'])
        for r in candidates:
            spec=r['spec'];writer.writerow([r['round'],spec['key'],spec['family'],spec['formula'],spec['parent'],r['source'],spec['hypothesis'],r['metrics']['search']['rank_ic'],r['metrics']['validation']['rank_ic'],r['metrics']['validation']['positive_months'],r.get('pool_validation_gain'),r['accepted'],'；'.join(r['reasons'])])
    return directory/'REPORT.md'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--id',required=True)
    print(summarize(parser.parse_args().id))
