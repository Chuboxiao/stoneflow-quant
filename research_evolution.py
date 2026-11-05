"""Small, agent-guided factor evolution study; no external model API or publication.

Commands: init, search REQUEST.json, freeze, final. Candidate decisions use only
2024-2025. The 2026 review is retrospective, not a previously unseen blind test.
"""
from pathlib import Path
from dataclasses import replace, asdict
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse, hashlib, json, pickle, time
import numpy as np
import pandas as pd
from backtest.precision import Panel, PrecisionConfig, PrecisionEngine, MissingActions
from backtest.report import json_safe
from factorlab.core import evaluate, eligible_mask, correlation, FactorSpec, FactorContext, REGISTRY
from factorlab.portfolio import FactorPortfolio
from research_5dr import save_result

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/evolution_20261030'
CACHE=Path('/tmp/stoneflow-evolution-20261030')
START,END='2024-01-02','2025-12-31'
REVIEW_START,REVIEW_END='2026-01-01','2026-09-30'
def now(): return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def write(path,x):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(json_safe(x),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def read(path): return json.loads(path.read_text())
def emit(x): print(json.dumps(json_safe(x),ensure_ascii=False),flush=True)

def score(frames,s):
    c=frames['close'].where(lambda v:v>0)*frames['cumadj'].where(lambda v:v>0)
    n=s.get('window',5); kind=s['kind']
    r=c.div(c.shift(n))-1
    if kind=='reversal': result=-r
    elif kind=='momentum': result=r
    elif kind=='breakout': result=c/(frames['high']*frames['cumadj']).shift(1).rolling(n,min_periods=n).max()-1
    elif kind=='amount': result=frames['amt']/frames['amt'].shift(1).rolling(n,min_periods=n).mean()-1
    elif kind=='lowvol': result=-c.pct_change(fill_method=None).rolling(n,min_periods=n).std(ddof=1)
    elif kind=='risk_reversal':
        vol=c.pct_change(fill_method=None).rolling(s.get('vol_window',20),min_periods=s.get('vol_window',20)).std(ddof=1)
        result=-r/vol.where(vol>1e-12)
    elif kind=='smooth_reversal': result=(-r).rolling(s.get('smooth',3),min_periods=s.get('smooth',3)).mean()
    elif kind=='rank_mix':
        a=(-r).rank(axis=1,pct=True)
        vol=c.pct_change(fill_method=None).rolling(20,min_periods=20).std(ddof=1)
        b=(-vol).rank(axis=1,pct=True)
        result=s.get('alpha',.5)*a+(1-s.get('alpha',.5))*b
    elif kind=='amount_reversal':
        ratio=frames['amt']/frames['amt'].shift(1).rolling(20,min_periods=20).mean()
        result=(-r)*ratio.clip(.25,4)
    else: raise ValueError(kind)
    return result.replace([np.inf,-np.inf],np.nan).to_numpy(float)

def brief(result):
    h=result['summary'][0];months=[x['mean'] for x in result['periods'] if len(x['period'])==7 and x['mean'] is not None]
    return {'rank_ic':h['rank_ic']['mean'],'positive_months':sum(x>0 for x in months)/len(months),
            'months':len(months),'coverage':float(np.mean([x['factor_coverage'] for x in result['coverage'] if x['factor_coverage'] is not None])),
            'spread':h['mean_spread'],'label_coverage':h['label_coverage'],'days':h['rank_ic']['observations']}

def load_panel():
    with (CACHE/'panel.pkl').open('rb') as f:p=pickle.load(f)
    overlays={}
    for path in sorted((ROOT/'data/evolution_actions').glob('*.json')):
        item=read(path)
        if item.get('error') is None:
            p.events[(item['symbol'],int(item['year']))]=item['events']
            overlays[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if overlays:write(OUT/'action_supplement_manifest.json',{'source':'BaoStock query_dividend_data(yearType=operate)','loaded_at':now(),'sha256':overlays,'purpose':'补齐冻结方案所需公司行为；不改变候选、股票池或选型'})
    return p

def pair_corr(panel,x,y):
    values=[]
    for i in np.flatnonzero((panel.dates>=pd.Timestamp(START))&(panel.dates<=pd.Timestamp(END))):
        mask=eligible_mask(panel,i,'base')
        values.append(abs(correlation(x[i,mask],y[i,mask],True)))
    return float(np.nanmean(values))

def process(panel,specs,round_no,harness,feedback):
    state=read(OUT/'state.json');write(OUT/f'round_{round_no}_request.json',{'created_at':now(),'harness':harness,'feedback':feedback,'candidates':specs})
    for s in specs:
        started=time.monotonic();key=s['key']
        if key in state['candidates']:raise ValueError('Duplicate candidate key')
        values=score(panel.frames,s)
        # Actual prefix execution: removing future rows must preserve earlier scores.
        cut=panel.locations[pd.Timestamp('2024-12-31')]
        prefix=score({k:v.iloc[:cut+1] for k,v in panel.frames.items()},s)
        np.testing.assert_allclose(values[:cut+1],prefix,rtol=1e-10,atol=1e-12,equal_nan=True)
        # Independently check vectorized seed formulas against the existing builders.
        if key in REGISTRY:
            for i in [100,300,500]:
                expected=REGISTRY[key].builder(FactorContext(panel,i)).reindex(panel.symbols).to_numpy(float)
                np.testing.assert_allclose(values[i],expected,rtol=1e-8,atol=1e-10,equal_nan=True)
        np.save(CACHE/f'{key}.npy',values)
        result=evaluate(panel,values,START,END,'base',(5,))
        summary=brief(result);parent=s.get('parent');accepted=True;reasons=[];similar=[];correlations={}
        if parent:
            p=state['candidates'][parent]['search']
            if summary['rank_ic']<=p['rank_ic']: reasons.append('平均有符号Rank IC未超过父因子')
            if summary['positive_months']+1e-12<p['positive_months']: reasons.append('正IC月份比例下降')
            if summary['coverage']+0.005<p['coverage']: reasons.append('覆盖率下降超过0.5个百分点')
            for peer in list(state['pool']):
                rho=pair_corr(panel,values,np.load(CACHE/f'{peer}.npy',mmap_mode='r'))
                correlations[peer]=rho
                if rho>.8:
                    similar.append(peer)
                    if summary['rank_ic']<=state['candidates'][peer]['search']['rank_ic']:reasons.append('与更强池内因子高度相关:'+peer)
            accepted=not reasons
        if accepted:
            for peer in similar:
                if peer in state['pool']:state['pool'].remove(peer)
            state['pool'].append(key)
        row={'spec':s,'round':round_no,'harness':harness,'created_at':now(),'search':summary,'accepted':accepted,
             'reasons':reasons or ['初始基线入库' if not parent else '预测与稳定性门槛通过；高相关者择优替换'],
             'replaced':similar if accepted else [],'correlations':correlations,'prefix_check':True,'seconds':time.monotonic()-started}
        state['candidates'][key]=row
        write(OUT/'search'/f'{key}.json',result);write(OUT/'state.json',state)
        emit({'candidate':key,**summary,'accepted':accepted,'reasons':row['reasons'],'seconds':row['seconds']})

def init():
    OUT.mkdir(parents=True,exist_ok=True);CACHE.mkdir(exist_ok=True)
    if (OUT/'protocol.json').exists():raise ValueError('Existing study: refuse overwrite')
    write(OUT/'protocol.json',{'created_at':now(),'search':[START,END],'review':[REVIEW_START,REVIEW_END],
        'horizon':5,'pool':'base','direction':'预先固定，使用有符号IC，不按结果翻转',
        'acceptance':'mean Rank IC > parent; positive-month fraction >= parent; coverage >= parent - .005; high mean absolute daily rank correlation > .8 replaces weaker pool member only',
        'diversity':'最终组合至少两个不同家族；每家族最多一个，按搜索IC排序，再以平均绝对每日秩相关<=.8筛选，最多5个；正IC、正IC月份比例>=.5；不足两个家族则不构造新组合',
        'ensemble':'对每日合格股票作因子横截面百分位排名，等权平均；必须所有成员都有数值；不拟合权重',
        'final_selection':'最高搜索IC的合格池内单因子及多样化池等权组合，另保留初始五因子等权组合和5DR；2026不用于选型',
        'budget':'最多5轮，每轮最多3新候选；本轮优先在10分钟内完成，可减少轮数，不改评分标准',
        'execution':asdict(PrecisionConfig()),'portfolio':{'top_n':20,'weight':.95,'every':1},
        'research_type':'Agent在当前聊天中读实测反馈再提出候选；不是独立API自动Agent，也不训练模型；2026是已见历史的回顾性检查',
        'harness_evidence':'流程版本及其原因属于过程记录，小样本前后比较不证明因果提升'})
    local=read(ROOT/'local_config.json');emit({'stage':'load_panel'})
    p=Panel.load(local['data_dir'],local['reference_dir'],local['action_dir'])
    with (CACHE/'panel.pkl').open('wb') as f:pickle.dump(p,f,protocol=5)
    write(OUT/'manifest.json',{'created_at':now(),'securities':len(p.symbols),'audit':p.audit,
        'data_sha256':{k:hashlib.sha256((Path(local['data_dir'])/(k+'.feather')).read_bytes()).hexdigest() for k in p.frames},
        'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['research_evolution.py','factorlab/core.py','factorlab/portfolio.py','backtest/precision.py']}})
    write(OUT/'state.json',{'candidates':{},'pool':[]})
    seeds=[{'key':k,'kind':kind,'window':n,'family':fam,'formula':formula} for k,kind,n,fam,formula in [
        ('reversal5','reversal',5,'reversal','-(C_t/C_t-5 - 1)'),('momentum20','momentum',20,'trend','C_t/C_t-20 - 1'),
        ('breakout20','breakout',20,'trend','C_t/max(H_t-20:t-1)-1'),('amount20','amount',20,'activity','A_t/mean(A_t-20:t-1)-1'),
        ('lowvol20','lowvol',20,'risk','-std(daily_return,20)')]]
    process(p,seeds,0,'H0','五个已有家族起点；趋势内含动量与突破，组合时每家族最多一个。')

def freeze(p):
    state=read(OUT/'state.json');eligible=[k for k in state['pool'] if state['candidates'][k]['search']['rank_ic']>0 and state['candidates'][k]['search']['positive_months']>=.5]
    eligible.sort(key=lambda k:(-state['candidates'][k]['search']['rank_ic'],k));chosen=[];families=set();rho={}
    for k in eligible:
        fam=state['candidates'][k]['spec']['family']
        if fam in families:continue
        correlations={j:pair_corr(p,np.load(CACHE/f'{k}.npy',mmap_mode='r'),np.load(CACHE/f'{j}.npy',mmap_mode='r')) for j in chosen}
        rho[k]=correlations
        if any(v>.8 for v in correlations.values()):continue
        chosen.append(k);families.add(fam)
        if len(chosen)==5:break
    write(OUT/'frozen.json',{'frozen_at':now(),'primary_single':eligible[0] if eligible else 'reversal5','members':chosen if len(chosen)>=2 else [],'correlations':rho,'no_reselection_on_review':True})
    emit(read(OUT/'frozen.json'))

def ensemble(p,members):
    matrices=[]
    eligibility=np.asarray([eligible_mask(p,i,'base') for i in range(len(p.dates))])
    for k in members:
        v=np.load(CACHE/f'{k}.npy').copy();v[~eligibility]=np.nan
        matrices.append(pd.DataFrame(v).rank(axis=1,pct=True,method='average').to_numpy())
    return np.mean(matrices,axis=0)

def final(p):
    frozen=read(OUT/'frozen.json');state=read(OUT/'state.json');accounts=[];diagnostics={}
    targets={'reversal5':np.load(CACHE/'reversal5.npy'),frozen['primary_single']:np.load(CACHE/(frozen['primary_single']+'.npy')),
             'seed_ensemble':ensemble(p,['reversal5','momentum20','breakout20','amount20','lowvol20'])}
    if frozen['members']:targets['evolved_ensemble']=ensemble(p,frozen['members'])
    # All pool-member review results are descriptive, never used to reselect members.
    for k in frozen['members']:
        if k not in targets:targets[k]=np.load(CACHE/f'{k}.npy')
    for key,values in targets.items():
        result=evaluate(p,values,REVIEW_START,REVIEW_END,'base',(5,));write(OUT/'review'/f'{key}.json',result)
        diagnostics[key]=brief(result);emit({'review':key,**diagnostics[key]})
    write(OUT/'final.json',{'completed_at':None,'status':'RUNNING_ACCOUNTS','diagnostics':diagnostics,'accounts':accounts,'frozen':frozen})
    trade_keys=list(dict.fromkeys(['reversal5',frozen['primary_single'],'seed_ensemble']+(['evolved_ensemble'] if frozen['members'] else [])))
    for key in trade_keys:
        for cost in ['normal','double_cost']:
            config=PrecisionConfig()
            if cost=='double_cost':config=replace(config,commission=config.commission*2,min_commission=config.min_commission*2,stamp=config.stamp*2,transfer=config.transfer*2,slippage_bps=config.slippage_bps*2)
            spec=FactorSpec(key,key,'frozen cached causal score',61,lambda ctx:None)
            try:
                result=PrecisionEngine(p,config).run(FactorPortfolio(spec,'base',scores=targets[key]),REVIEW_START,REVIEW_END)
            except MissingActions as exc:
                row={'key':key,'cost':cost,'status':'BLOCKED_MISSING_CORPORATE_ACTIONS','error':str(exc)}
                accounts.append(row);write(OUT/'accounts'/key/cost/'error.json',row)
                write(OUT/'accounts_summary.json',accounts);emit(row)
                continue
            save_result(result,OUT/'accounts'/key/cost)
            m=result['metrics'];e=result['equity']
            np.testing.assert_allclose(e.equity,e.cash+e.market_value+e.dividend_receivable,rtol=1e-11,atol=1e-6)
            np.testing.assert_allclose(m['total_return'],e.equity.iloc[-1]/config.cash-1,rtol=1e-10,atol=1e-10)
            row={'key':key,'cost':cost,'status':'COMPLETE','metrics':m};accounts.append(row);write(OUT/'accounts_summary.json',accounts)
            emit({'account':key,'cost':cost,'return':m['total_return'],'drawdown':m['max_drawdown']})
    write(OUT/'final.json',{'completed_at':now(),'status':'FACTOR_STUDY_COMPLETE_ACCOUNT_DATA_GAPS' if any('metrics' not in a for a in accounts) else 'COMPLETE','diagnostics':diagnostics,'accounts':accounts,'frozen':frozen})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init','search','freeze','final']);parser.add_argument('request',nargs='?');args=parser.parse_args()
    if args.command=='init':init()
    else:
        p=load_panel()
        if args.command=='search':
            req=read(Path(args.request));process(p,req['candidates'],req['round'],req['harness'],req['feedback'])
        elif args.command=='freeze':freeze(p)
        else:final(p)
