"""Retrospective mechanism diagnostics and pre-period stock-cohort experiments.

Original studies/engine are never overwritten. Price event studies are explicitly
separate from integer-share account simulations. No automatic publication.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time
import numpy as np
import pandas as pd
from backtest.precision import Panel, PrecisionConfig, PrecisionEngine, bounds
from backtest.breakout_pool import PoolBreakout, SPECS
from research_5dr import START, END, write_json, save_result

GROUPS=(('frozen_all','2024可观察全组'),('trend_high','2024趋势效率较高'),('trend_low','2024趋势效率较低'),
        ('vol_low','2024波动较低'),('vol_high','2024波动较高'),
        ('trend_calm','2024高趋势效率＋低波动'),('liquid_high','2024成交额较高'))


def frozen_groups(panel):
    """Only data <=2024-12-31 are materialized before feature calculations."""
    end=panel.locations[pd.Timestamp('2024-12-31')]
    price=pd.DataFrame(panel.adjusted[:end+1],index=panel.dates[:end+1],columns=panel.symbols).where(lambda x:x>0)
    ret=price/price.shift(1)-1
    efficiency=(price-price.shift(60)).abs()/price.diff().abs().rolling(60,min_periods=60).sum().replace(0,np.nan)
    volatility=ret.rolling(20,min_periods=20).std()
    year=price.index.year==2024
    frame=pd.DataFrame({'symbol':panel.symbols,'valid_days_2024':price[year].notna().sum().to_numpy(),
        'efficiency60_2024':efficiency[year].mean().to_numpy(),'volatility20_2024':volatility[year].mean().to_numpy(),
        'mean_amount_2024':panel.frames['amt'].iloc[:end+1].loc[year].mean().to_numpy()})
    eligible=(frame.valid_days_2024>=180)&np.isfinite(frame.efficiency60_2024)&np.isfinite(frame.volatility20_2024)&(frame.mean_amount_2024>0)
    eligible &= (panel.states['isST'][end]==0)&(panel.states['tradestatus'][end]==1)&(panel.arrays['close'][end]>0)
    frame['eligible_at_freeze']=eligible
    qualified=frame[eligible]
    thresholds={name:float(qualified[name].median()) for name in ('efficiency60_2024','volatility20_2024','mean_amount_2024')}
    high=frame.efficiency60_2024>=thresholds['efficiency60_2024']
    calm=frame.volatility20_2024<=thresholds['volatility20_2024']
    liquid=frame.mean_amount_2024>=thresholds['mean_amount_2024']
    masks={'frozen_all':eligible,'trend_high':eligible&high,'trend_low':eligible&~high,'vol_low':eligible&calm,
           'vol_high':eligible&~calm,'trend_calm':eligible&high&calm,'liquid_high':eligible&liquid}
    members={key:frame.loc[mask,'symbol'].tolist() for key,mask in masks.items()}
    return frame,thresholds,members


class RestrictedBreakout:
    """Compose an existing arbitrary Python strategy with an immutable universe."""
    def __init__(self,key,title,symbols):
        self.spec=replace(SPECS[0],key=key,title=title)
        self.symbols=tuple(symbols)
        self.inner=PoolBreakout(self.spec)

    def on_close(self,context):
        names=list(self.symbols)
        def history(field='close',lookback=None,adjusted=True):return context.history(field,lookback,adjusted).loc[:,names]
        def states(field='isST',lookback=1):return context.states(field,lookback).loc[:,names]
        return self.inner.on_close(SimpleNamespace(date=context.date,symbols=self.symbols,cash=context.cash,equity=context.equity,
            positions={s:context.positions[s] for s in names},history=history,states=states))


class CashOnly:
    def on_close(self,context):return {}


def block_period(eq,begin,end,cash):
    mask=(eq.date>=begin)&(eq.date<=end);block=eq[mask]
    idx=np.flatnonzero(mask.to_numpy())[0];initial=cash if idx==0 else float(eq.equity.iloc[idx-1])
    vals=block.equity.to_numpy();peak=np.maximum.accumulate(np.r_[initial,vals])[1:]
    total=float(vals[-1]/initial-1)
    return {'total_return':total,'max_drawdown':float((vals/peak-1).min()),'trading_days':len(block),
            'annualized_return':float((1+total)**(252/len(block))-1)}


def bootstrap_mean(values,seed=20261017,block=20,repetitions=1500):
    """Circular moving-block bootstrap over signal dates, not individual stocks."""
    values=np.asarray(values,float);values=values[np.isfinite(values)]
    if not len(values):return {'mean':None,'low':None,'high':None,'days':0}
    rng=np.random.default_rng(seed);n=len(values)
    starts=rng.integers(0,n,size=(repetitions,(n+block-1)//block))
    idx=(starts[:,:,None]+np.arange(block))%n
    samples=values[idx.reshape(repetitions,-1)[:,:n]].mean(axis=1)
    return {'mean':float(values.mean()),'low':float(np.quantile(samples,.025)),
            'high':float(np.quantile(samples,.975)),'days':n,'block':block,'repetitions':repetitions}


def signal_study(panel,root):
    p=panel;a=p.arrays
    high=pd.DataFrame(a['high']*a['cumadj']).where(lambda x:x>0).shift(1).rolling(20,min_periods=20).max().to_numpy()
    adjusted_open=a['open']*a['cumadj']
    first=p.locations[pd.Timestamp(START)];last=p.locations[pd.Timestamp(END)]
    rows=[];gaps=[]
    for i in range(first-1,last-1):
        # Shared quality pool isolates signal direction from universe differences.
        eligible=(p.states['isST'][i]==0)&(p.states['tradestatus'][i]==1)&(p.age[i]>=60)&p.valid20[i]
        eligible &= np.isfinite(high[i])&np.isfinite(p.ret5[i])&(a['close'][i]>=3)&(p.mean_amt[i]>=20_000_000)
        eligible &= (a['amt'][i]>0)&(a['num_trades'][i]>0)
        candidates=np.flatnonzero(eligible)
        ranked_low=sorted(candidates,key=lambda j:(p.ret5[i,j],p.symbols[j]))[:20]
        ranked_break=sorted((j for j in candidates if p.adjusted[i,j]>high[i,j]),
                            key=lambda j:(-p.adjusted[i,j]/high[i,j],p.symbols[j]))[:20]
        signal_sets={'five_dr':ranked_low,'breakout':ranked_break,
                     'all_breakouts':[j for j in candidates if p.adjusted[i,j]>high[i,j]],'universe':candidates.tolist()}
        k=i+1;gate=np.zeros(len(p.symbols),bool)
        factor_change=a['cumadj'][k]/a['cumadj'][i]-1
        for j in candidates:
            raw,ref=a['open'][k,j],p.states['preclose'][k,j]
            if not (p.states['isST'][k,j]==0 and p.states['tradestatus'][k,j]==1 and np.isfinite(raw) and raw>0 and np.isfinite(ref) and ref>0):continue
            if not (a['amt'][k,j]>0 and a['num_trades'][k,j]>0):continue
            if np.isfinite(factor_change[j]) and abs(factor_change[j])>1e-5:continue
            rate=.2 if p.symbols[j].startswith(('300','301','302','688','689')) else .1
            lower,upper=bounds(ref,rate)
            price=np.ceil(raw*1.0005*100-1e-8)/100
            gate[j]=(lower-.005<=raw<upper-1e-6 and lower-1e-8<=price<upper-1e-8 and a['low'][k,j]-.005<=price<=a['high'][k,j]+.005)
        for h in (1,5,20):
            if k+h>last:continue
            # No October2026 observations, including for forward labels.
            future=adjusted_open[k+h]/adjusted_open[k]-1
            future_valid=np.isfinite(future)&(adjusted_open[k+h]>0)&(p.states['tradestatus'][k+h]==1)&(a['amt'][k+h]>0)&(a['num_trades'][k+h]>0)
            record={}
            for name,indices in signal_sets.items():
                ids=np.asarray(indices,int);passed=ids[gate[ids]];observed=passed[future_valid[passed]]
                censored=len(passed)-len(observed)
                mean=float(future[observed].mean()) if len(observed) else np.nan
                # Report unresolved exits, plus extreme zero-recovery sensitivity.
                zero=float((future[observed].sum()-censored)/len(passed)) if len(passed) else np.nan
                record[name]={'date':str(p.dates[i].date()),'entry_date':str(p.dates[k].date()),'horizon':h,'signal':name,
                    'selected':len(ids),'entry_passed':len(passed),'entry_blocked':len(ids)-len(passed),
                    'observed_exits':len(observed),'unresolved_exits':censored,'mean_forward_return':mean,
                    'zero_recovery_sensitivity':zero,'mean_entry_gap':float((adjusted_open[k,observed]/p.adjusted[i,observed]-1).mean()) if len(observed) else np.nan}
            benchmark=record['universe']['mean_forward_return']
            for item in record.values():
                item['excess_vs_same_day_universe']=item['mean_forward_return']-benchmark
                rows.append(item)
    frame=pd.DataFrame(rows);frame.to_csv(root/'signal_cohorts.csv',index=False,encoding='utf-8-sig')
    summary=[]
    for (name,h),block in frame.groupby(['signal','horizon']):
        item={'signal':name,'horizon':int(h),**bootstrap_mean(block.excess_vs_same_day_universe)}
        item.update(mean_forward_return=float(block.mean_forward_return.mean()),mean_entry_gap=float(block.mean_entry_gap.mean()),
                    selected=int(block.selected.sum()),entry_passed=int(block.entry_passed.sum()),unresolved_exits=int(block.unresolved_exits.sum()))
        item['mean_zero_recovery_return']=float(block.zero_recovery_sensitivity.mean())
        summary.append(item)
    for h in (1,5,20):
        paired=frame[frame.horizon==h].pivot(index='date',columns='signal',values='mean_forward_return')
        item={'signal':'five_dr_minus_breakout','horizon':h,**bootstrap_mean(paired.five_dr-paired.breakout)}
        item.update(mean_forward_return=item['mean'],mean_entry_gap=None,selected=None,entry_passed=None,unresolved_exits=None,
                    mean_zero_recovery_return=None)
        summary.append(item)
    return summary


def attribution(directory,panel,output,benchmark=None):
    """Daily cash+receivable+mark attribution sums to actual account P&L."""
    output.mkdir(parents=True,exist_ok=True)
    eq=pd.read_csv(directory/'equity.csv');orders=pd.read_csv(directory/'orders.csv');pos=pd.read_csv(directory/'positions.csv');actions=pd.read_csv(directory/'actions.csv')
    m=json.loads((directory/'metrics.json').read_text());initial=m['initial_cash']
    fills=orders[orders.notional>0].copy();fills['fees']=fills.commission+fills.stamp_tax+fills.transfer_fee
    fills['cashflow']=np.where(fills.side=='SELL',fills.notional,-fills.notional)-fills.fees
    fills['slippage_cash']=np.where(fills.side=='BUY',fills.raw_execution_price-fills.raw_open,fills.raw_open-fills.raw_execution_price)*fills.filled_qty
    dates=eq.date.tolist();names=sorted(set(fills.symbol)|set(pos.symbol)|set(actions.symbol))
    def grid(frame,date,value):
        if not len(frame):return pd.DataFrame(0.,index=dates,columns=names)
        return frame.pivot_table(index=date,columns='symbol',values=value,aggfunc='sum').reindex(index=dates,columns=names).fillna(0)
    marks=grid(pos,'date','market_value');qty=grid(pos,'date','shares')
    cashflow=grid(fills,'execution_date','cashflow')+grid(actions,'date','cash_delta')
    recv=grid(actions,'date','receivable_delta')
    pnl=marks.diff().fillna(marks.iloc[0])+cashflow+recv
    actual=eq.equity.diff().fillna(eq.equity.iloc[0]-initial).to_numpy()
    error=float(np.max(np.abs(pnl.sum(axis=1).to_numpy()-actual)))
    if error>1e-5:raise ArithmeticError('Attribution does not reconcile: '+str(error))
    fees=fills.groupby('symbol').fees.sum();slip=fills.groupby('symbol').slippage_cash.sum()
    bysymbol=pd.DataFrame({'symbol':names,'net_pnl':pnl.sum().reindex(names).to_numpy(),
        'fees':fees.reindex(names).fillna(0).to_numpy(),'slippage_on_actual_fills':slip.reindex(names).fillna(0).to_numpy(),
        'ending_market_value':marks.iloc[-1].to_numpy()})
    bysymbol['contribution_initial_capital']=bysymbol.net_pnl/initial
    bysymbol=bysymbol.sort_values('net_pnl',ascending=False);bysymbol.to_csv(output/'symbol_attribution.csv',index=False,encoding='utf-8-sig')
    pnl.rename_axis('date').to_csv(output/'daily_symbol_pnl.csv',encoding='utf-8-sig')
    # Contiguous end-of-day position spells, including the actual liquidation day.
    episodes=[]
    for name in names:
        held=qty[name].to_numpy()>1e-8;indices=np.flatnonzero(held)
        segments=np.split(indices,np.flatnonzero(np.diff(indices)>1)+1) if len(indices) else []
        stock=fills[fills.symbol==name]
        local=[]
        for segment in segments:
            begin,last=int(segment[0]),int(segment[-1]);finish=min(last+1,len(dates)-1);closed=last<len(dates)-1
            trades=stock[(stock.execution_date>=dates[begin])&(stock.execution_date<=dates[finish])]
            capital=float((trades.loc[trades.side=='BUY','notional']+trades.loc[trades.side=='BUY','fees']).sum())
            row={'symbol':name,'entry_date':dates[begin],'last_held_date':dates[last],'exit_date':dates[finish] if closed else None,
                'closed':closed,'holding_sessions':last-begin+1,'invested_buy_cash':capital,'net_pnl':float(pnl[name].iloc[begin:finish+1].sum()),
                'entry_gap':None,'fell_back_below_channel_in5':None}
            buy=trades[trades.side=='BUY']
            if len(buy):
                signal=buy.iloc[0].signal_date;j=panel.index[name];si=panel.locations[pd.Timestamp(signal)];ei=panel.locations[pd.Timestamp(dates[begin])]
                row['entry_gap']=float(panel.arrays['open'][ei,j]*panel.arrays['cumadj'][ei,j]/panel.adjusted[si,j]-1)
                if ei+4<=panel.locations[pd.Timestamp(END)]:
                    channel=panel.arrays['high'][si-20:si,j]*panel.arrays['cumadj'][si-20:si,j]
                    prices=panel.adjusted[ei:ei+5,j]
                    if np.isfinite(channel).all() and np.isfinite(prices).all():row['fell_back_below_channel_in5']=bool((prices<=channel.max()).any())
            local.append(row)
        # Move late dividend recognition to the owner at the registration close.
        for event in actions[(actions.symbol==name)&(actions.type=='EX_DIVIDEND_OR_BONUS')].itertuples():
            detail=next((e for e in panel.events.get((name,int(event.date[:4])),[]) if e.get('dividOperateDate')==event.date),None)
            if detail:
                reg=detail.get('dividRegistDate','');owner=next((x for x in local if x['entry_date']<=reg<=x['last_held_date']),None)
                recognized=next((x for x in local if x['entry_date']<=event.date<=(x['exit_date'] or END)),None)
                if owner is not None and owner is not recognized:
                    amount=event.cash_delta+event.receivable_delta
                    owner['net_pnl']+=amount
                    if recognized is not None:recognized['net_pnl']-=amount
        for row in local:
            row['net_return_on_buy_cash']=row['net_pnl']/row['invested_buy_cash'] if row['invested_buy_cash']>0 else None
        episodes.extend(local)
    spells=pd.DataFrame(episodes);spells.to_csv(output/'holding_spells.csv',index=False,encoding='utf-8-sig')
    closed=spells[spells.closed & spells.net_return_on_buy_cash.notna()]
    wins=closed[closed.net_pnl>0];losses=closed[closed.net_pnl<0]
    # Do not present spell summaries as account metrics if any P&L is unassigned.
    spell_error=float(spells.net_pnl.sum()-bysymbol.net_pnl.sum())
    if abs(spell_error)>.01:raise ArithmeticError('Holding-spell P&L is unassigned: '+str(spell_error))
    regime_rows=[]
    benchmark_path=Path('data/reference/csi300.csv')
    if benchmark is None and benchmark_path.exists():benchmark=pd.read_csv(benchmark_path,parse_dates=['date']).set_index('date').close
    if benchmark is not None:
        regime=(benchmark.shift(1)>benchmark.rolling(60,min_periods=60).mean().shift(1)).reindex(pd.to_datetime(dates))
        for strong,title in ((True,'前日指数在MA60之上'),(False,'前日指数不高于MA60')):
            mask=regime.to_numpy()==strong
            regime_rows.append({'regime':title,'days':int(mask.sum()),'pnl_contribution':float(actual[mask].sum()/initial),
                                'mean_daily_return':float(eq.daily_return.to_numpy()[mask].mean()) if mask.any() else None})
    return {'metrics':m,'account_reconciliation_error':error,'spell_reconciliation_error':spell_error,
        'positive_symbols':int((bysymbol.net_pnl>0).sum()),'negative_symbols':int((bysymbol.net_pnl<0).sum()),'traded_symbols':len(names),
        'fees_initial_capital':float(fills.fees.sum()/initial),'slippage_on_actual_fills_initial':float(fills.slippage_cash.sum()/initial),
        'fixed_fill_path_addback_return':float((eq.equity.iloc[-1]-initial+fills.fees.sum()+fills.slippage_cash.sum())/initial),
        'top5_contribution':float(bysymbol.head(5).net_pnl.sum()/initial),'top':bysymbol.head(5).to_dict('records'),'bottom':bysymbol.tail(5).to_dict('records'),
        'closed_spells':len(closed),'open_spells':int((~spells.closed).sum()),'win_rate':float((closed.net_pnl>0).mean()),
        'mean_win_return':float(wins.net_return_on_buy_cash.mean()),'mean_loss_return':float(losses.net_return_on_buy_cash.mean()),
        'profit_factor':float(wins.net_pnl.sum()/abs(losses.net_pnl.sum())) if len(losses) else None,
        'median_holding_sessions':float(closed.holding_sessions.median()),
        'short_losing_spell_fraction':float(((closed.net_pnl<0)&(closed.holding_sessions<=10)).mean()),
        'fallback5_fraction':float(spells.fell_back_below_channel_in5.dropna().astype(bool).mean()),
        'fallback5_observations':int(spells.fell_back_below_channel_in5.notna().sum()),
        'mean_entry_gap':float(spells.entry_gap.mean()),'regimes':regime_rows}


def run(args):
    root=Path(args.output);root.mkdir(parents=True,exist_ok=True)
    write_json(root/'run_status.json',{'status':'RUNNING'})
    panel=Panel.load(args.data_dir,args.reference_dir,args.action_dir)
    for filename in ('breakout_corporate_reference_overrides.json','analysis_corporate_reference_overrides.json'):
        path=Path('reference')/filename
        if path.exists():
            for item in json.loads(path.read_text()):
                if item['announced_at']>item['ex_date']:raise ValueError('Late override')
                panel.reference_overrides[(item['symbol'],item['ex_date'])]=item
    features,thresholds,members=frozen_groups(panel)
    features.to_csv(root/'features_2024.csv',index=False,encoding='utf-8-sig');write_json(root/'frozen_universes.json',members)
    protocol={'created_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'retrospective':True,
        'disclosure':'All prior 2025/2026 study results have been seen. New analyses are retrospective explanations, not blind confirmations.',
        'freeze_date':'2024-12-31','feature_period':'2024 only, warm-up before2024','minimum_valid_days_2024':180,
        'thresholds':thresholds,'groups':[{'key':k,'title':t,'members':len(members[k])} for k,t in GROUPS],
        'selection_2025':'Among predefined groups with positive2025return, maximize annualized_return/(abs(drawdown)+0.05); ties by key; else cash.',
        'evaluation':'2025-01-02..2026-09-30; all7 groups plus double-cost; separate fresh2026 accounts for selected group, frozen all and full course pool.',
        'signals':'Common liquid non-ST pool; lowest5DR20 vs strongest20-day breakouts20 vs all breakouts vs same-day pool; next open to open after1/5/20 sessions, gross quote study, not account returns. Paired fiveDR-minus-breakout is a descriptive signal spread, not a shortable portfolio.',
        'bootstrap':'1500 circular20-session blocks over dates; seed20261017; overlapping horizons, descriptive unadjusted intervals, no multiple-testing correction.',
        'group_membership_sha256':hashlib.sha256((root/'frozen_universes.json').read_bytes()).hexdigest(),
        'execution':asdict(PrecisionConfig())}
    registration=root/'protocol.json'
    if not registration.exists():write_json(registration,protocol)
    original=json.loads(registration.read_text())
    if original['group_membership_sha256']!=protocol['group_membership_sha256'] or original['thresholds']!=thresholds:raise ValueError('Frozen membership changed')
    if args.register_only:return
    cfg=replace(PrecisionConfig(),allow_missing_actions=args.provisional)
    missing=set();discrepancies=[];comparison=[];stresses=[];periods=[];outputs={}
    def execute(strategy,begin,end,dest,config):
        print(dest,flush=True);result=PrecisionEngine(panel,config).run(strategy,begin,end);save_result(result,root/dest)
        missing.update(tuple(x) for x in result['metrics']['missing_actions'])
        discrepancies.extend({'run':dest,**x} for x in result['metrics']['event_reference_discrepancies'])
        return result
    def strategy(key):return RestrictedBreakout(key,dict(GROUPS)[key],members[key])
    for key,title in GROUPS:
        result=execute(strategy(key),START,END,'cohorts/'+key,cfg);outputs[key]=result
        comparison.append({'key':key,'title':title,'pool_size_at_freeze':len(members[key]),**result['metrics']})
        for label,begin,end in (('2025',START,'2025-12-31'),('2026年前三季度','2026-01-01',END)):
            periods.append({'key':key,'period':label,**block_period(result['equity'],begin,end,cfg.cash)})
    training=[]
    for row in periods:
        if row['period']=='2025':training.append({**row,'score':row['annualized_return']/(abs(row['max_drawdown'])+.05)})
    positive=sorted((x for x in training if x['total_return']>0),key=lambda x:(-x['score'],x['key']))
    selected=positive[0]['key'] if positive else 'cash'
    write_json(root/'selection_2025.json',{'selected_key':selected,'training':training,'rule':original['selection_2025'],'retrospective':True})
    stress_cfg=replace(cfg,commission=cfg.commission*2,min_commission=cfg.min_commission*2,stamp=cfg.stamp*2,transfer=cfg.transfer*2,slippage_bps=cfg.slippage_bps*2)
    for key,title in GROUPS:
        result=execute(strategy(key),START,END,'stress/double_cost/'+key,stress_cfg)
        stresses.append({'key':key,'title':title,**result['metrics']})
    fresh=[]
    for key,title,obj in [('selected','2025选组后2026重新建账',strategy(selected) if selected!='cash' else CashOnly()),
                          ('frozen_all','2024可观察全组重新建账',strategy('frozen_all')),
                          ('course_all','课程全池重新建账',PoolBreakout(SPECS[0]))]:
        result=execute(obj,'2026-01-01',END,'fresh_2026/'+key,cfg)
        fresh.append({'case':key,'title':title,'selected_universe':selected if key=='selected' else key,**result['metrics']})
    write_json(root/'needed_actions.json',[list(x) for x in sorted(missing)]);write_json(root/'event_discrepancies.json',discrepancies)
    if args.provisional:
        write_json(root/'run_status.json',{'status':'PROVISIONAL','missing_actions':len(missing),'event_discrepancies':len(discrepancies)})
        print(json.dumps({'missing_actions':len(missing),'event_discrepancies':len(discrepancies),'selected':selected}),flush=True);return
    explanations={}
    for key,directory in [('five_dr',Path('results/5dr_review/evaluation/liquid')),('breakout',Path('results/breakout_review/evaluation/base'))]:
        explanations[key]=attribution(directory,panel,root/'attribution'/key)
    signals=signal_study(panel,root)
    summary={'status':'REVIEW_ONLY','protocol':original,'comparison':comparison,'stress':stresses,'periods':periods,
             'selected_key_2025':selected,'fresh_2026':fresh,'attribution':explanations,'signal_study':signals,
             'performance_start':START,'performance_end':END,'data_audit':panel.audit}
    write_json(root/'summary.json',summary)
    pd.DataFrame(comparison).drop(columns=['missing_actions','event_reference_discrepancies','rejection_reasons']).to_csv(root/'comparison.csv',index=False,encoding='utf-8-sig')
    files=['strategy_analysis.py','backtest/precision.py','backtest/breakout_pool.py','validate_5dr.py']
    files.extend(str(p) for p in Path('reference').glob('*corporate_reference_overrides.json'))
    write_json(root/'source_manifest.json',{'completed_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'code_sha256':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files},
        'protocol_sha256':hashlib.sha256(registration.read_bytes()).hexdigest(),
        'course_sha256':json.loads(Path('results/breakout_review/source_manifest.json').read_text())['course_sha256'],
        'reference_manifest_sha256':panel.audit['reference_manifest_sha256'],
        'action_cache_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(args.action_dir).glob('*.json'))}})
    write_json(root/'run_status.json',{'status':'COMPLETE'})
    print(json.dumps({'selected_2025':selected,'cohorts':[{k:r[k] for k in ('key','total_return','max_drawdown')} for r in comparison]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True)
    p.add_argument('--reference-dir',default='data/reference/baostock-20230901-20260930');p.add_argument('--action-dir',default='data/reference/actions')
    p.add_argument('--output',default='results/strategy_analysis');p.add_argument('--provisional',action='store_true');p.add_argument('--register-only',action='store_true')
    args=p.parse_args()
    try:run(args)
    except Exception as exc:
        Path(args.output).mkdir(parents=True,exist_ok=True);write_json(Path(args.output)/'run_status.json',{'status':'FAILED','error':str(exc)});raise
