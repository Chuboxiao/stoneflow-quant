"""Reproducible saved factor reports; no publication or source-data upload."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from backtest.precision import Panel, PrecisionConfig, PrecisionEngine
from backtest.report import json_safe
from .core import REGISTRY, FactorSpec, compute_scores, evaluate, load_factor_csv, correlation, eligible_mask
from .portfolio import FactorPortfolio

ROOT = Path(__file__).resolve().parent.parent


def write_json(path, content):
    Path(path).write_text(json.dumps(json_safe(content), ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def strategy_score(metrics):
    annual = metrics['annualized_return']
    return {"value": annual / (abs(metrics['max_drawdown']) + .05) if annual > 0 else None,
            "eligible_for_ranking": annual > 0,
            "note": "自定义年化收益／(绝对最大回撤＋0.05)，不是IC或标准Calmar；非正收益不参与此评分排序。"}


def account_card(directory, key, period, source_note):
    metrics = json.loads((directory / 'metrics.json').read_text())
    equity = pd.read_csv(directory / 'equity.csv')
    total = float(equity.equity.iloc[-1] / metrics['initial_cash'] - 1)
    annual = float((1 + total) ** (252 / len(equity)) - 1)
    if not np.isclose(total, metrics['total_return'], atol=1e-10) or not np.isclose(annual, metrics['annualized_return'], atol=1e-10):
        raise ValueError("账户收益口径核对失败")
    return {"key": key, "period": period, "source_note": source_note, "metrics": metrics,
            "score": strategy_score(metrics),
            "curve": [{"date": r.date, "net_value": r.net_value} for r in equity.itertuples()],
            "metrics_sha256": hashlib.sha256((directory / 'metrics.json').read_bytes()).hexdigest(),
            "equity_sha256": hashlib.sha256((directory / 'equity.csv').read_bytes()).hexdigest()}


def existing_accounts(start, end):
    result = []
    source = ROOT / 'results/5dr_review'
    for phase in ('training', 'evaluation'):
        for key in ('base', 'liquid'):
            directory = source / phase / key
            if (directory / 'metrics.json').exists():
                result.append(account_card(directory, key, phase, "第四讲已保存的原始股份精度账户；按原参数与费用，非本次因子报价分组回测。"))
    if start != '2025-01-02' or end != '2026-09-30':
        for item in result:
            item['source_note'] += " 当前因子区间与该历史账户区间可能不同，不作同区间直接比较。"
    return result


def load_plugin(path):
    spec = importlib.util.spec_from_file_location("stoneflow_user_factor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factor = module.FACTOR
    if not isinstance(factor, FactorSpec) or factor.key in REGISTRY:
        raise ValueError("插件需导出不与内置key重复的FactorSpec对象FACTOR")
    return factor


def run(data_dir, reference_dir, output, start='2025-01-02', end='2026-09-30',
        factors=('reversal5', 'momentum20', 'breakout20', 'amount20', 'lowvol20'),
        horizons=(1, 5, 10, 20), pool='both', factor_csv=None, direction=1, plugin=None,
        trade=False, action_dir=None, progress=None, trade_factors=()):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    emit = progress or (lambda text: print(text, flush=True))
    if not Path(reference_dir).is_dir():
        raise ValueError("缺少历史ST／停牌参考目录；因子评价不把未知状态当作非ST")
    if pool not in ('base', 'liquid', 'both'):
        raise ValueError('未知股票池')
    specs = []
    for key in factors:
        if key not in REGISTRY:
            raise ValueError(f'未知内置因子：{key}')
        specs.append(REGISTRY[key])
    if plugin:
        plugin_factor=load_plugin(plugin)
        specs.append(plugin_factor)
    if factor_csv:
        specs.append(FactorSpec('custom', '导入因子', '用户CSV提供的时点分数，因果性与发布时间需自行核验。', 1, lambda ctx: None, direction))
    if not specs or len({s.key for s in specs}) != len(specs):
        raise ValueError('需至少一个不重复的因子')
    if set(trade_factors)-{s.key for s in specs}:
        raise ValueError('交易因子须属于本次评价的因子')
    need_trade=bool(trade or trade_factors)
    emit('读取行情并核对历史ST资料')
    panel = Panel.load(data_dir, reference_dir, action_dir if need_trade else None)
    if not panel.dates[0] <= pd.Timestamp(start) < pd.Timestamp(end) <= panel.dates[-1]:
        raise ValueError(f'因子评价需在历史状态覆盖范围 {panel.dates[0].date()} 至 {panel.dates[-1].date()} 内')
    if need_trade and (not action_dir or not Path(action_dir).is_dir()):
        raise ValueError('净交易回测需要公司行为资料；不以报价分组收益替代实际成交')
    analyses, scores_by_key, trade_cards = [], {}, []
    for spec in specs:
        emit('计算因子：' + spec.title)
        scores = (load_factor_csv(factor_csv, panel, direction) if spec.key == 'custom'
                  else compute_scores(panel, spec, start, end))
        scores_by_key[spec.key] = scores
        pools = ('base', 'liquid') if pool == 'both' else (pool,)
        for selected_pool in pools:
            # The complete 5DR filter comparison is retained; other factors use
            # the same base universe unless the caller explicitly selects liquid.
            if pool == 'both' and spec.key != 'reversal5' and selected_pool == 'liquid':
                continue
            emit(f'评价 {spec.title} / {selected_pool}：IC、分组、覆盖与稳定性')
            result = evaluate(panel, scores, start, end, selected_pool, tuple(horizons))
            result.update(key=f'{spec.key}_{selected_pool}', factor_key=spec.key, title=spec.title,
                          description=spec.description, direction=spec.direction,
                          imported_values=spec.key == 'custom', custom_code=bool(plugin and spec.key == plugin_factor.key))
            analyses.append(result)
            if trade or spec.key in trade_factors:
                from research_5dr import save_result
                for scenario in ('normal', 'double_cost'):
                    emit(f'精度账户：{spec.title} / {selected_pool} / {scenario}')
                    config = PrecisionConfig()
                    if scenario == 'double_cost':
                        config = replace(config, commission=config.commission*2, min_commission=config.min_commission*2,
                                         stamp=config.stamp*2, transfer=config.transfer*2, slippage_bps=config.slippage_bps*2)
                    strategy = FactorPortfolio(spec, selected_pool, scores=scores if spec.key == 'custom' else None)
                    result_trade = PrecisionEngine(panel, config).run(strategy, start, end)
                    directory = output / 'accounts' / f'{spec.key}_{selected_pool}' / scenario
                    save_result(result_trade, directory)
                    card = account_card(directory, f'{spec.key}_{selected_pool}_{scenario}', 'new', '本次通过原始股份PrecisionEngine重跑；次日执行、涨跌停拒单、费用和公司行为。')
                    card['label']=spec.title+(' · 基础池' if selected_pool=='base' else ' · 流动性池')+(' · 标准成本' if scenario=='normal' else ' · 双倍成本')
                    trade_cards.append(card)
    correlations = []
    keys = list(scores_by_key)
    for ai, left in enumerate(keys):
        for right in keys[ai+1:]:
            values = []
            for i, date in enumerate(panel.dates):
                if not pd.Timestamp(start) <= date <= pd.Timestamp(end):
                    continue
                mask = eligible_mask(panel, i, 'base')
                x, y = scores_by_key[left][i].copy(), scores_by_key[right][i].copy()
                x[~mask] = np.nan; y[~mask] = np.nan
                values.append(correlation(x, y, True))
            valid = np.asarray(values)[np.isfinite(values)]
            correlations.append({'left': left, 'right': right, 'mean_rank_correlation': float(valid.mean()) if len(valid) else None,
                                 'observations': int(len(valid))})
    methods = {
        'signal': 't日收盘时因子，分数高的预设为看好；方向事先固定，不按评价期IC翻转。',
        'forward_return': '复权open[t+1+h] / 复权open[t+1] − 1；h是交易日，至少下一日入场再隔一日退出。',
        'label_cutoff': '所有标签终点不晚于评价期末；末尾h+1个信号日删失，原始数据中的2026年10月不参与默认评价。',
        'universe': '信号日isST=0、tradestatus=1，至少60条有效历史，连续20日有效价格，当日amt和num_trades为正；未知状态排除。',
        'liquid_pool': '在基础池上增加近20日平均成交额≥2000万元、原始收盘价≥3元；与第四讲5DR相同。',
        'preprocessing': '仅在当日股票池内1%/99%分位缩尾，不用全样本统计量、不按未来收益筛股票。IC用Pearson，Rank IC用平均秩Spearman。',
        'groups': '按当日因子平均秩分5组，同分不强拆；独立取值不足5个时不分组；少于30个有效配对时不计算IC。Q5为高分。',
        'icir': '日度IC均值 / 日度IC样本标准差，未年化。HAC t为Bartlett/Newey-West均值诊断，lag=max(h−1,5)，保留缺失日期间隔；非多重检验校正后的有效性证明。',
        'group_returns': '先按全部当日可用分数分组，再计算观察到的未来报价收益。缺失不填0、不延后找价；每组保留selected和observed数量。',
        'curves': '仅1日标签的分组平均报价收益逐日复合展示；1日区间不重叠。高减低及多日均值不累乘。该曲线未扣费、不保证成交、非可做空账户。',
        'turnover': 'Q5名单退出比例=1−相邻日交集/前日Q5人数；不是交易账本的金额换手。',
        'stability': '分年与分月按信号日分桶；跨年标签可以使用次年区间内报价，因此年度桶为描述，不能用于无清洗的训练选型。',
        'selection': '不生成因子总分、不自动挑冠军、不自动换方向；第五讲方法为回顾性研究。',
        'limits': '报价标签不执行涨跌停撮合；真实净交易由PrecisionEngine单独处理。cumadj收益不能替代含股利税、到账与锁股的原始股份账本。',
        'missing_risk_data': '无历史行业、市值和完整退市账本，未声称做行业/市值中性化或完整消除存活偏差；缺失标签可能带来选择偏差。',
    }
    payload = {'format': 1, 'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
               'start': start, 'end': end, 'securities': len(panel.symbols), 'horizons': list(horizons),
               'analyses': analyses, 'factor_correlations': correlations,
               'accounts': existing_accounts(start, end) + trade_cards, 'methods': methods,
               'data_audit': panel.audit, 'research_type': 'retrospective, descriptive; not forward blind test'}
    emit('保存报告、明细和复现记录')
    write_json(output / 'summary.json', payload)
    daily, groups, coverage = [], [], []
    for a in analyses:
        for row in a['daily']:
            daily.append({'analysis': a['key'], **{k: v for k, v in row.items() if not isinstance(v, list)}})
            for j in range(a['quantiles']):
                groups.append({'analysis': a['key'], 'date': row['date'], 'horizon': row['horizon'], 'group': j+1,
                               'mean_quote_return': row['group_returns'][j], 'selected': row['group_selected'][j], 'observed': row['group_observed'][j]})
        coverage.extend({'analysis': a['key'], **r} for r in a['coverage'])
    for name, rows in [('daily', daily), ('groups', groups), ('coverage', coverage)]:
        pd.DataFrame(rows).to_csv(output / f'{name}.csv', index=False, encoding='utf-8-sig')
    source_files = ['factorlab/core.py', 'factorlab/portfolio.py', 'factorlab/runner.py', 'factorlab/presentation.py', 'backtest/precision.py']
    write_json(output / 'manifest.json', {
        'runtime': {'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__},
        'code_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files},
        'course_sha256': {name: hashlib.sha256((Path(data_dir) / f'{name}.feather').read_bytes()).hexdigest() for name in panel.frames},
        'reference_manifest_sha256': panel.audit.get('reference_manifest_sha256'),
        'custom_source_sha256': hashlib.sha256(Path(factor_csv or plugin).read_bytes()).hexdigest() if factor_csv or plugin else None,
        'custom_input_sha256': {kind: hashlib.sha256(Path(path).read_bytes()).hexdigest() for kind,path in [('csv',factor_csv),('plugin',plugin)] if path},
        'parameters': {'start': start, 'end': end, 'factors': list(factors), 'horizons': list(horizons), 'pool': pool, 'direction': direction, 'trade': trade, 'trade_factors': list(trade_factors)},
        'source_data_published': False,
    })
    from .presentation import render_report, markdown_report
    (output / 'report.html').write_text(render_report(json_safe(payload)), encoding='utf-8')
    (output / 'report.md').write_text(markdown_report(json_safe(payload)), encoding='utf-8')
    write_json(output / 'run_status.json', {'status': 'COMPLETE', 'analyses': len(analyses)})
    return json_safe(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--reference-dir', required=True)
    parser.add_argument('--action-dir')
    parser.add_argument('--output', default='results/factors')
    parser.add_argument('--start', default='2025-01-02'); parser.add_argument('--end', default='2026-09-30')
    parser.add_argument('--factors', default=','.join(REGISTRY))
    parser.add_argument('--horizons', default='1,5,10,20')
    parser.add_argument('--pool', choices=['base', 'liquid', 'both'], default='both')
    parser.add_argument('--factor-csv'); parser.add_argument('--direction', type=int, choices=[1, -1], default=1)
    parser.add_argument('--plugin', help='Explicitly load a trusted local Python file exporting FACTOR')
    parser.add_argument('--trade', action='store_true', help='Also rerun raw-share accounts and double-cost cases; needs actions')
    parser.add_argument('--trade-factors', default='', help='Only run net accounts for these comma-separated factor keys')
    args = parser.parse_args()
    run(args.data_dir, args.reference_dir, args.output, args.start, args.end,
        tuple(x for x in args.factors.split(',') if x), tuple(int(x) for x in args.horizons.split(',')),
        args.pool, args.factor_csv, args.direction, args.plugin, args.trade, args.action_dir,
        trade_factors=tuple(x for x in args.trade_factors.split(',') if x))


if __name__ == '__main__':
    main()
