"""Persistent, bounded factor research. Proposals are data, never executable code.

The built-in proposer is a deterministic rule baseline. Agent-authored JSON can
use the same evaluation loop. Validation is part of selection, not a blind test.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import numpy as np
import pandas as pd

from backtest.precision import Panel
from backtest.report import json_safe
from .core import eligible_mask, evaluate, correlation

ROOT = Path(__file__).resolve().parent.parent
KINDS = {
    'reversal': 'reversal', 'momentum': 'trend', 'breakout': 'trend',
    'amount': 'activity', 'lowvol': 'risk', 'smooth_reversal': 'reversal',
    'risk_reversal': 'reversal', 'amount_reversal': 'price_volume',
    'range_position': 'price_location', 'rank_mix': 'hybrid',
}
POLICY = {
    'version': 'diverse-pool-v1', 'min_ic': 0., 'min_positive_months': .5,
    'min_coverage': .95, 'max_correlation': .8, 'max_members': 5,
    'min_validation_gain': .0001, 'max_search_ic_loss': .005,
    'note': '搜索与选择验证均需正IC、至少半数月份正IC、覆盖95%；同家族或相关>0.8先替换；等权组合验证IC至少增加0.0001，搜索IC最多下降0.005。规则不在实验中修改。',
}


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_spec(raw):
    if not isinstance(raw, dict) or set(raw) - {'key', 'kind', 'window', 'smooth', 'vol_window', 'alpha', 'parent', 'hypothesis'}:
        raise ValueError('候选只接受 key/kind/window/smooth/vol_window/alpha/parent/hypothesis 字段')
    kind = raw.get('kind')
    if kind not in KINDS:
        raise ValueError('不支持的因子类型；不接受可执行代码')
    key = raw.get('key', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', key):
        raise ValueError('因子key须为48字符以内的小写字母、数字、下划线')
    result = {'key': key, 'kind': kind}
    for field, default in [('window', 5), ('smooth', 3), ('vol_window', 20)]:
        if field != 'window' and not (field == 'smooth' and kind == 'smooth_reversal' or field == 'vol_window' and kind == 'risk_reversal'):
            if field in raw:
                raise ValueError(f'{kind}不使用{field}')
            continue
        value = raw.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 120:
            raise ValueError(f'{field}须为2至120的整数')
        result[field] = value
    if kind == 'rank_mix':
        alpha = raw.get('alpha', .5)
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not .1 <= alpha <= .9:
            raise ValueError('alpha须在0.1至0.9之间')
        result['alpha'] = float(alpha)
    elif 'alpha' in raw:
        raise ValueError('只有rank_mix使用alpha')
    parent = raw.get('parent')
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', parent)):
        raise ValueError('无效父因子key')
    hypothesis = raw.get('hypothesis', '')
    if not isinstance(hypothesis, str) or not 3 <= len(hypothesis) <= 1200:
        raise ValueError('请用3至1200字说明候选假设')
    result.update(parent=parent, hypothesis=hypothesis, family=KINDS[kind])
    n = result['window']
    result['formula'] = {
        'reversal': f'-ret({n})', 'momentum': f'ret({n})',
        'breakout': f'C / max(previous_high, {n}) - 1',
        'amount': f'amount / mean(previous_amount, {n}) - 1',
        'lowvol': f'-std(daily_return, {n})',
        'smooth_reversal': f'mean(-ret({n}), {result.get("smooth", 3)})',
        'risk_reversal': f'-ret({n}) / std(daily_return, {result.get("vol_window", 20)})',
        'amount_reversal': f'-ret({n}) * clip(amount / mean(previous_amount, 20), .25, 4)',
        'range_position': f'-(C - rolling_low({n})) / (rolling_high({n}) - rolling_low({n}))',
        'rank_mix': f'{result.get("alpha", .5)} * eligible_rank(-ret({n})) + {1-result.get("alpha", .5):g} * eligible_rank(-std(return,20))',
    }[kind]
    result['fingerprint'] = digest({k: v for k, v in result.items() if k in {'kind', 'window', 'smooth', 'vol_window', 'alpha'}})
    return result


def seeds():
    return [validate_spec(dict(key=key, kind=kind, window=n, hypothesis='预设方向的已有因子，作为同条件研究起点'))
            for key, kind, n in [('reversal5', 'reversal', 5), ('momentum20', 'momentum', 20),
                                 ('breakout20', 'breakout', 20), ('amount20', 'amount', 20), ('lowvol20', 'lowvol', 20)]]


def score(frames, spec, eligibility=None):
    c = frames['close'].where(lambda x: x > 0) * frames['cumadj'].where(lambda x: x > 0)
    n, kind = spec['window'], spec['kind']
    ret = c.div(c.shift(n)) - 1
    if kind == 'reversal': value = -ret
    elif kind == 'momentum': value = ret
    elif kind == 'lowvol': value = -c.pct_change(fill_method=None).rolling(n, min_periods=n).std(ddof=1)
    elif kind == 'breakout': value = c / (frames['high'] * frames['cumadj']).shift(1).rolling(n, min_periods=n).max() - 1
    elif kind == 'amount': value = frames['amt'] / frames['amt'].shift(1).rolling(n, min_periods=n).mean() - 1
    elif kind == 'smooth_reversal': value = (-ret).rolling(spec['smooth'], min_periods=spec['smooth']).mean()
    elif kind == 'risk_reversal':
        vol = c.pct_change(fill_method=None).rolling(spec['vol_window'], min_periods=spec['vol_window']).std(ddof=1)
        value = -ret / vol.where(vol > 1e-12)
    elif kind == 'amount_reversal':
        ratio = frames['amt'] / frames['amt'].shift(1).rolling(20, min_periods=20).mean()
        value = -ret * ratio.clip(.25, 4)
    elif kind == 'range_position':
        low = (frames['low'] * frames['cumadj']).rolling(n, min_periods=n).min()
        high = (frames['high'] * frames['cumadj']).rolling(n, min_periods=n).max()
        value = -(c-low) / (high-low).where(high-low > 1e-12)
    elif kind == 'rank_mix':
        if eligibility is None:
            raise ValueError('秩组合需要当日股票池')
        vol = c.pct_change(fill_method=None).rolling(20, min_periods=20).std(ddof=1)
        value = spec['alpha'] * (-ret).where(eligibility).rank(axis=1, pct=True) + (1-spec['alpha']) * (-vol).where(eligibility).rank(axis=1, pct=True)
    else: raise ValueError(kind)
    return value.replace([np.inf, -np.inf], np.nan).to_numpy(float)


def brief(result):
    summary = result['summary'][0]
    months = [x['mean'] for x in result['periods'] if len(x['period']) == 7 and x['mean'] is not None]
    coverage = [x['factor_coverage'] for x in result['coverage'] if x['factor_coverage'] is not None]
    return {'rank_ic': summary['rank_ic']['mean'], 'positive_months': sum(x > 0 for x in months)/len(months) if months else None,
            'months': len(months), 'coverage': float(np.mean(coverage)) if coverage else None,
            'spread': summary['mean_spread'], 'days': summary['rank_ic']['observations']}


def quality_reasons(metrics):
    reasons = []
    for phase, title in [('search', '搜索段'), ('validation', '选择验证段')]:
        m = metrics[phase]
        if m['rank_ic'] is None or m['rank_ic'] <= POLICY['min_ic']: reasons.append(title+'IC不为正')
        if m['positive_months'] is None or m['positive_months'] < POLICY['min_positive_months']: reasons.append(title+'正IC月份不足半数')
        if m['coverage'] is None or m['coverage'] < POLICY['min_coverage']: reasons.append(title+'覆盖率不足95%')
    return reasons


def configuration(raw):
    allowed = {'name', 'pool', 'horizon', 'search_start', 'search_end', 'validation_start', 'validation_end', 'round_budget', 'harness'}
    if not isinstance(raw, dict) or set(raw)-allowed:
        raise ValueError('未知实验参数')
    c = dict(name='多样性因子改进', pool='liquid', horizon=5, search_start='2024-01-02', search_end='2024-12-31',
             validation_start='2025-01-02', validation_end='2025-12-31', round_budget=3, harness='H1-diversity')
    c.update(raw)
    if not isinstance(c['name'], str) or not 1 <= len(c['name'].strip()) <= 100: raise ValueError('实验名称须为1至100字')
    if c['pool'] not in ('base', 'liquid') or c['harness'] not in ('H0-baseline', 'H1-diversity'): raise ValueError('未知股票池或研究流程')
    if isinstance(c['horizon'], bool) or not isinstance(c['horizon'], int) or c['horizon'] not in (1, 5, 10, 20): raise ValueError('期限须为1/5/10/20日')
    if isinstance(c['round_budget'], bool) or not isinstance(c['round_budget'], int) or not 1 <= c['round_budget'] <= 5: raise ValueError('预算须为1至5轮')
    for k in ('search_start', 'search_end', 'validation_start', 'validation_end'):
        value = c[k]
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or pd.Timestamp(value).strftime('%Y-%m-%d') != value:
            raise ValueError('日期格式必须为YYYY-MM-DD')
    if not '2023-09-01' <= c['search_start'] < c['search_end'] < c['validation_start'] < c['validation_end'] <= '2025-12-31':
        raise ValueError('搜索段、选择验证段须先后分开，最晚至2025-12-31；2026保留冻结后回顾')
    if any((pd.Timestamp(c[b])-pd.Timestamp(c[a])).days < 90 for a, b in [('search_start','search_end'), ('validation_start','validation_end')]):
        raise ValueError('每个研究区间至少90个日历日')
    c['max_candidates_per_round'] = 3
    c['policy'] = POLICY.copy()
    c['review'] = ['2026-01-01', '2026-09-30']
    c['review_note'] = '2026历史已在此前研究中查看；冻结后回顾，不称新盲测，不用于本次候选选择。'
    c['execution_note'] = '本模块评价预测能力；报价分组收益未扣交易成本，不是净交易账户。'
    return c


class EvolutionLab:
    def __init__(self, directory=None, panel_loader=None, cache_dir=None):
        self.directory = Path(directory or ROOT/'results/evolution_runs')
        self.cache_dir = Path(cache_dir or ROOT/'data/evolution_cache')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.panel_loader = panel_loader
        self._panel = None
        self._fingerprint = None

    def path(self, study_id):
        if not isinstance(study_id, str) or not re.fullmatch(r'[0-9a-f]{12}', study_id): raise ValueError('无效实验编号')
        return self.directory/study_id

    @contextmanager
    def lock(self, study_id):
        directory = self.path(study_id)
        if not (directory/'study.json').is_file(): raise FileNotFoundError('实验不存在')
        with (directory/'study.lock').open('a') as f:
            try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('该实验正在运行')
            try: yield
            finally: fcntl.flock(f, fcntl.LOCK_UN)

    def read(self, study_id):
        return read_json(self.path(study_id)/'study.json')

    def save(self, study):
        study['updated_at'] = now()
        write_json(self.path(study['id'])/'study.json', study)

    def list(self):
        result = []
        for p in self.directory.glob('*/study.json'):
            s = read_json(p)
            result.append({k: s[k] for k in ('id', 'created_at', 'updated_at', 'status', 'config', 'rounds_completed', 'pool')})
        return sorted(result, key=lambda x: x['created_at'], reverse=True)

    def recover(self):
        for s in self.list():
            if s['status'] != 'running': continue
            try:
                with self.lock(s['id']):
                    current = self.read(s['id'])
                    current.update(status='interrupted', stage='上次运行中断，可从已保存候选继续')
                    self.save(current)
            except RuntimeError: pass

    def create(self, raw):
        c = configuration(raw)
        study = dict(id=uuid.uuid4().hex[:12], created_at=now(), updated_at=now(), status='ready', stage='等待评价初始因子',
                     config=c, config_hash=digest(c), rounds_completed=0, candidates={}, pool=[], rounds=[], pending=None,
                     pool_metrics=None, baseline=None, frozen=None, review=None,
                     generation='规则基线自动提案；也可导入Agent候选。没有后台模型调用。')
        self.save(study)
        return study

    def panel(self):
        if self._panel is None:
            if self.panel_loader: self._panel = self.panel_loader()
            else:
                c = read_json(ROOT/'local_config.json')
                self._panel = Panel.load(c['data_dir'], c['reference_dir'])
            p = self._panel
            h = hashlib.sha256()
            h.update(json.dumps([str(d) for d in p.dates]).encode())
            h.update(json.dumps(p.symbols).encode())
            for k, v in sorted({**p.arrays, **p.states}.items()):
                h.update(k.encode()); h.update(np.ascontiguousarray(v).tobytes())
            self._fingerprint = h.hexdigest()
        return self._panel

    def code_hash(self):
        return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('factorlab/evolution.py', 'factorlab/core.py', 'backtest/precision.py')}

    def context(self, study):
        p = self.panel()
        if digest(study['config']) != study['config_hash']: raise ValueError('实验配置被修改，请创建新实验')
        provenance = {'data_sha256': self._fingerprint, 'code_sha256': self.code_hash(), 'securities': len(p.symbols),
                      'first_date': str(p.dates[0].date()), 'last_date': str(p.dates[-1].date())}
        if study.get('provenance') and study['provenance'] != provenance:
            raise ValueError('数据或评测代码版本发生变化，请创建新实验，不能混用结果')
        study['provenance'] = provenance
        eligibility = np.array([eligible_mask(p, i, study['config']['pool']) for i in range(len(p.dates))])
        return p, eligibility

    def matrix(self, study, spec, p, eligibility):
        directory = self.cache_dir/study['id']; directory.mkdir(parents=True, exist_ok=True)
        path = directory/(spec['fingerprint']+'.npy')
        if path.exists(): return np.load(path, mmap_mode='r')
        values = score(p.frames, spec, eligibility)
        cut = int(np.searchsorted(p.dates, pd.Timestamp(study['config']['search_end']), side='right'))
        prefix = score({k: v.iloc[:cut] for k, v in p.frames.items()}, spec, eligibility[:cut])
        np.testing.assert_allclose(values[:cut], prefix, equal_nan=True, rtol=1e-10, atol=1e-12)
        np.save(path, values)
        return values

    def assess(self, study, values, key, phases=('search', 'validation')):
        p = self.panel(); c = study['config']; result = {}
        for phase in phases:
            start, end = c['review'] if phase == 'review' else (c[phase+'_start'], c[phase+'_end'])
            full = evaluate(p, values, start, end, c['pool'], (c['horizon'],))
            write_json(self.path(study['id'])/'diagnostics'/f'{key}_{phase}.json', full)
            result[phase] = brief(full)
        return result

    def composite(self, study, members, p, eligibility):
        values = []
        for key in members:
            matrix = np.array(self.matrix(study, study['candidates'][key]['spec'], p, eligibility), copy=True)
            matrix[~eligibility] = np.nan
            values.append(pd.DataFrame(matrix).rank(axis=1, pct=True).to_numpy())
        if not values: raise ValueError('候选池为空')
        return np.mean(values, axis=0)

    def correlations(self, study, values, p, eligibility):
        c = study['config']; locs = np.flatnonzero((p.dates >= c['search_start']) & (p.dates <= c['validation_end']))
        result = {}
        for key in study['pool']:
            peer = self.matrix(study, study['candidates'][key]['spec'], p, eligibility)
            observations = [abs(correlation(values[i, eligibility[i]], peer[i, eligibility[i]], True)) for i in locs]
            valid = [x for x in observations if np.isfinite(x)]
            result[key] = float(np.mean(valid)) if valid else None
        return result

    def feedback(self, study):
        recent = [x for x in study['candidates'].values() if x['round'] == study['rounds_completed']]
        return {'round': study['rounds_completed'], 'pool': study['pool'], 'pool_metrics': study['pool_metrics'],
                'observations': [{'key': r['spec']['key'], 'family': r['spec']['family'], 'accepted': r['accepted'], 'reasons': r['reasons'], 'metrics': r['metrics']} for r in recent],
                'instruction': '依据失败原因提出最多3个不同机制候选；至少考虑一个池外家族；预先说明机制与方向。不得使用2026回顾结果，不得修改股票池、期限或接受规则。'}

    def propose(self, study_id):
        study = self.read(study_id)
        if not study['candidates']: return {'candidates': [], 'feedback': '先运行初始因子评价', 'source': 'seed'}
        options = [
            dict(key='reversal10', kind='reversal', window=10, parent='reversal5', hypothesis='延长反转窗口，检查短期噪声能否减弱'),
            dict(key='reversal5_smooth3', kind='smooth_reversal', window=5, smooth=3, parent='reversal5', hypothesis='平滑短期反转，检查月度稳定性与组合增量'),
            dict(key='lowvol60', kind='lowvol', window=60, parent='lowvol20', hypothesis='延长风险估计，检查低波动信号稳定性'),
            dict(key='amount_reversal5', kind='amount_reversal', window=5, parent='reversal5', hypothesis='按成交额异常调整反转，探索价量交互提供的信息'),
            dict(key='range_position20', kind='range_position', window=20, hypothesis='以价格区间位置衡量回撤，探索不同于单一收益窗口的信号'),
            dict(key='reversal_lowvol_half', kind='rank_mix', window=5, alpha=.5, parent='reversal5', hypothesis='反转和低风险等权秩组合，避免量纲差异'),
            dict(key='lowvol10', kind='lowvol', window=10, parent='lowvol20', hypothesis='更短风险窗口可能更及时地反映状态变化'),
            dict(key='reversal3', kind='reversal', window=3, parent='reversal5', hypothesis='更短反转窗口检查是否主要来自最近交易日'),
            dict(key='amount60', kind='amount', window=60, parent='amount20', hypothesis='更长成交额基准检查活动信号的稳定性'),
            dict(key='momentum60', kind='momentum', window=60, parent='momentum20', hypothesis='较长趋势窗口检查短期反转干扰'),
            dict(key='breakout60', kind='breakout', window=60, parent='breakout20', hypothesis='较长突破窗口检查趋势信息是否更稳健'),
            dict(key='range_position60', kind='range_position', window=60, hypothesis='长价格区间位置检查跨周期稳定性'),
            dict(key='reversal20', kind='reversal', window=20, parent='reversal5', hypothesis='月度反转窗口检查预测期限匹配'),
            dict(key='lowvol40', kind='lowvol', window=40, parent='lowvol20', hypothesis='中期风险窗口检查估计噪声与及时性的取舍'),
            dict(key='reversal5_vol20', kind='risk_reversal', window=5, vol_window=20, parent='reversal5', hypothesis='风险标准化检查极端反转信号的贡献'),
        ]
        seen = {r['spec']['fingerprint'] for r in study['candidates'].values()}
        options = [x for x in options if validate_spec(x)['fingerprint'] not in seen]
        if study['config']['harness'] == 'H1-diversity':
            families = {study['candidates'][k]['spec']['family'] for k in study['pool']}
            failed = {}
            for r in study['candidates'].values():
                if not r['accepted']: failed[r['spec']['kind']] = failed.get(r['spec']['kind'], 0) + 1
            options.sort(key=lambda x: (KINDS[x['kind']] in families, failed.get(x['kind'], 0)))
            chosen, used = [], set()
            for x in options:
                if KINDS[x['kind']] not in used:
                    chosen.append(x); used.add(KINDS[x['kind']])
                if len(chosen) == 3: break
            options = chosen + [x for x in options if x not in chosen]
        return {'candidates': options[:3], 'feedback': json.dumps(self.feedback(study), ensure_ascii=False),
                'source': 'rule-baseline', 'harness': study['config']['harness']}

    def run_round(self, study_id, proposals=None, feedback='', source='rule-baseline', progress=None):
        emit = progress or (lambda x: None)
        with self.lock(study_id):
            s = self.read(study_id)
            if s['frozen']: raise ValueError('已冻结，后续研究请创建新实验')
            if s['pending']:
                if proposals is not None: raise ValueError('请先继续未完成批次，不得覆盖候选')
                pending = s['pending']
            else:
                seed = not s['candidates']
                if not seed and s['rounds_completed'] >= s['config']['round_budget']: raise ValueError('研究预算已用完，可冻结结果')
                if seed:
                    specs, source, feedback = seeds(), 'seed', '同一股票池与区间评价5个起始因子，含4个家族'
                else:
                    if proposals is None:
                        generated = self.propose(study_id)
                        proposals, feedback, source = generated['candidates'], generated['feedback'], generated['source']
                    if not isinstance(proposals, list) or not 1 <= len(proposals) <= 3: raise ValueError('每轮须提供1至3个候选')
                    specs = [validate_spec(x) for x in proposals]
                if not isinstance(feedback, str) or len(feedback) > 20000 or source not in ('rule-baseline', 'agent-import', 'seed'): raise ValueError('无效提案来源或反馈')
                known = {r['spec']['fingerprint'] for r in s['candidates'].values()}
                keys = set(s['candidates'])
                for spec in specs:
                    if spec['key'] in keys or spec['fingerprint'] in known: raise ValueError('重复名称或重复公式，不重复消耗研究预算')
                    if spec['parent'] and spec['parent'] not in s['candidates']: raise ValueError('父因子必须来自已完成的尝试')
                    known.add(spec['fingerprint']); keys.add(spec['key'])
                pending = {'round': 0 if seed else s['rounds_completed']+1, 'source': source, 'feedback': feedback,
                           'harness': s['config']['harness'], 'specs': specs, 'created_at': now()}
                s['pending'] = pending
            s.update(status='running', error=None, stage='加载行情与历史状态')
            self.save(s); emit(s['stage'])
            try:
                p, eligibility = self.context(s); self.save(s)
                for spec in pending['specs']:
                    key = spec['key']
                    if key in s['candidates']: continue
                    started = time.monotonic(); s['stage'] = '评价 '+key; self.save(s); emit(s['stage'])
                    values = self.matrix(s, spec, p, eligibility)
                    metrics = self.assess(s, values, key)
                    rho = self.correlations(s, values, p, eligibility)
                    reasons = quality_reasons(metrics)
                    if any(v is None for v in rho.values()): reasons.append('相关性有效观察不足')
                    row = {'spec': spec, 'round': pending['round'], 'source': pending['source'], 'harness': pending['harness'],
                           'metrics': metrics, 'correlations': rho, 'accepted': False, 'reasons': [], 'prefix_check': True,
                           'created_at': now(), 'seconds': 0, 'completed': False, 'pool_before': list(s['pool']), 'pool_after': list(s['pool'])}
                    s['candidates'][key] = row
                    proposal = [peer for peer in s['pool'] if s['candidates'][peer]['spec']['family'] != spec['family'] and (rho[peer] is not None and rho[peer] <= POLICY['max_correlation'])] + [key]
                    if len(proposal) > POLICY['max_members']: reasons.append('候选池已达容量上限')
                    if not reasons:
                        combo = self.assess(s, self.composite(s, proposal, p, eligibility), 'pool_trial_'+key)
                        row['proposed_pool_metrics'] = combo
                        if s['pool_metrics']:
                            gain = combo['validation']['rank_ic'] - s['pool_metrics']['validation']['rank_ic']
                            row['pool_validation_gain'] = gain
                            if gain < POLICY['min_validation_gain']: reasons.append('等权组合选择验证IC增量不足0.0001')
                            if combo['search']['rank_ic'] < s['pool_metrics']['search']['rank_ic'] - POLICY['max_search_ic_loss']: reasons.append('组合搜索IC下降超过0.005')
                        if not reasons:
                            s['pool'], s['pool_metrics'] = proposal, combo
                            row['accepted'] = True
                    row['reasons'] = reasons or ['通过质量与组合增量门槛']
                    row['pool_after'] = list(s['pool']); row['seconds'] = round(time.monotonic()-started, 3); row['completed'] = True
                    self.save(s); emit(key+'：'+('保留' if row['accepted'] else '淘汰')+'；'+'；'.join(row['reasons']))
                s['rounds_completed'] = pending['round']
                if pending['round'] == 0:
                    s['baseline'] = {'pool': list(s['pool']), 'metrics': s['pool_metrics']}
                s['rounds'].append({**pending, 'finished_at': now(), 'pool': list(s['pool']), 'pool_metrics': s['pool_metrics']})
                s.update(pending=None, status='ready', stage='本轮完成；可继续研究或冻结')
                self.save(s)
            except Exception as exc:
                s['candidates'] = {k: r for k, r in s['candidates'].items() if r.get('completed')}
                s.update(status='interrupted', stage='本轮中断，已保存完成的候选', error=str(exc)); self.save(s)
                raise
        return self.read(study_id)

    def freeze(self, study_id):
        with self.lock(study_id):
            s = self.read(study_id)
            if s['pending']: raise ValueError('请先完成未结束的批次')
            if s['frozen']: return s
            if not s['baseline']: raise ValueError('请先评价初始因子')
            s['frozen'] = {'at': now(), 'members': list(s['pool']), 'config_hash': s['config_hash'],
                           'selection_metrics': s['pool_metrics'], 'no_reselection': True}
            s.update(status='frozen', stage='选型已冻结；可运行2026回顾检查')
            self.save(s)
            return s

    def review(self, study_id, progress=None):
        emit = progress or (lambda x: None)
        with self.lock(study_id):
            s = self.read(study_id)
            if not s['frozen']: raise ValueError('先冻结再进行回顾检查')
            if s['review']: return s
            s.update(status='running', stage='冻结后回顾检查'); self.save(s)
            try:
                p, eligibility = self.context(s)
                groups = {'seed_pool': s['baseline']['pool'], 'selected_pool': s['frozen']['members'], 'reversal5': ['reversal5']}
                result = {}
                for key, members in groups.items():
                    if not members:
                        result[key] = {'members': [], 'status': 'empty_pool'}; continue
                    emit('回顾检查 '+key)
                    values = self.composite(s, members, p, eligibility)
                    result[key] = {'members': members, 'metrics': self.assess(s, values, key, ('review',))['review']}
                s.update(review=result, status='frozen', stage='冻结后回顾完成；交易账户尚未验证')
                self.save(s)
            except Exception as exc:
                s.update(status='interrupted', stage='回顾检查中断，可重试', error=str(exc)); self.save(s)
                raise
            return s


def main():
    parser = argparse.ArgumentParser(description='穿石因子改进：持久化研究与规则候选基线')
    parser.add_argument('command', choices=['create', 'list', 'show', 'propose', 'run', 'freeze', 'review'])
    parser.add_argument('--id'); parser.add_argument('--request', type=Path)
    args = parser.parse_args(); lab = EvolutionLab()
    request = read_json(args.request) if args.request else {}
    if args.command == 'create': result = lab.create(request)
    elif args.command == 'list': result = lab.list()
    elif args.command == 'show': result = lab.read(args.id)
    elif args.command == 'propose': result = lab.propose(args.id)
    elif args.command == 'run': result = lab.run_round(args.id, request.get('candidates'), request.get('feedback',''), request.get('source','agent-import'), progress=lambda x: print(x, flush=True))
    elif args.command == 'freeze': result = lab.freeze(args.id)
    else: result = lab.review(args.id, progress=lambda x: print(x, flush=True))
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
