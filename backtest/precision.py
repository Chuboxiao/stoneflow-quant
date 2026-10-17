"""Daily research engine with historical states and orders fixed at prior close.

The legacy adjusted-unit engine remains available for the original breakout study.
This engine keeps raw shares, dividend receivables and share-delivery locks.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import math
from types import MappingProxyType
import numpy as np
import pandas as pd


def tick_price(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money_product(value, rate):
    return float((Decimal(str(value))*Decimal(str(rate))).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP))


def bounds(preclose, rate):
    """ROUND_HALF_UP, retaining source reference precision until the final tick."""
    ref,r=Decimal(str(preclose)),Decimal(str(rate))
    lower,upper=((ref*x).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) for x in (1-r,1+r))
    if ref-lower<Decimal('.01'):lower=max(Decimal('.01'),(ref-Decimal('.01')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    if upper-ref<Decimal('.01'):upper=(ref+Decimal('.01')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    return float(lower),float(upper)


class Panel:
    def __init__(self, frames, states, events=None, audit=None, reference_overrides=None):
        self.dates = pd.DatetimeIndex(frames["close"].index)
        self.symbols = tuple(frames["close"].columns)
        if not self.dates.is_monotonic_increasing or self.dates.has_duplicates:
            raise ValueError("Dates must be sorted and unique")
        for frame in frames.values():
            if not frame.index.equals(self.dates) or tuple(frame.columns) != self.symbols:
                raise ValueError("Market matrices are not aligned")
        self.frames = frames
        self.arrays = {k: v.to_numpy(float) for k,v in frames.items()}
        self.states = {k: v.reindex(index=self.dates, columns=self.symbols).to_numpy(float)
                       for k,v in states.items()}
        for key in ("isST", "tradestatus", "preclose"):
            if key not in self.states:
                raise ValueError(f"Missing historical state: {key}")
        self.index = {s: i for i,s in enumerate(self.symbols)}
        self.locations = {d: i for i,d in enumerate(self.dates)}
        self.events = events or {}
        self.reference_overrides=reference_overrides or {}
        self.audit = audit or {}
        c, a = self.arrays["close"], self.arrays["cumadj"]
        self.adjusted = c*a
        valid = np.isfinite(c)&(c>0)&np.isfinite(a)&(a>0)
        self.age = np.cumsum(valid, axis=0)
        self.ret5 = pd.DataFrame(self.adjusted).div(pd.DataFrame(self.adjusted).shift(5)).to_numpy()-1
        self.mean_amt = frames["amt"].rolling(20, min_periods=20).mean().to_numpy()
        self.valid20 = pd.DataFrame(valid).rolling(20,min_periods=20).sum().to_numpy()==20
        self.ma60 = pd.DataFrame(self.adjusted).rolling(60,min_periods=60).mean().to_numpy()
        self.trend20 = pd.DataFrame(self.adjusted).div(pd.DataFrame(self.adjusted).shift(20)).to_numpy()-1
        self.last_risk60 = pd.DataFrame(self.states["isST"]!=0).rolling(60,min_periods=60).max().to_numpy()

    @classmethod
    def load(cls, data_dir, reference_dir, action_dir=None):
        frames = {k: pd.read_feather(Path(data_dir)/f"{k}.feather").set_index("date").loc["2023-09-01":"2026-09-30"].copy()
                  for k in ("open","high","low","close","amt","num_trades","cumadj")}
        dates, symbols = frames["close"].index, frames["close"].columns
        states = {k: pd.DataFrame(np.nan, index=dates, columns=symbols)
                  for k in ("isST","tradestatus","preclose")}
        compared = mismatched = 0
        missing_files, failures = [], []
        for symbol in symbols:
            path = Path(reference_dir)/f"{symbol}.csv.gz"
            if not path.exists():
                missing_files.append(symbol)
                continue
            try:
                frame = pd.read_csv(path,parse_dates=["date"]).set_index("date")
                if frame.index.has_duplicates:
                    raise ValueError("Duplicate state dates")
                for k in states:
                    states[k][symbol] = pd.to_numeric(frame[k],errors="coerce").reindex(dates)
                price = pd.to_numeric(frame["close"],errors="coerce").reindex(dates)
                course = frames["close"][symbol]
                both = price.gt(0)&course.gt(0)
                bad = both & ((price-course).abs()>.005)
                compared += int(both.sum()); mismatched += int(bad.sum())
                # State from an unaligned price record cannot silently pass the gate.
                for k in states:
                    states[k].loc[bad,symbol] = np.nan
            except Exception as exc:
                failures.append({"symbol":symbol,"error":str(exc)})
        events = {}
        if action_dir and Path(action_dir).exists():
            for path in Path(action_dir).glob("*.json"):
                content = json.loads(path.read_text())
                if content.get("error") is None:
                    events[(content["symbol"],int(content["year"]))] = content["events"]
        source = Path(reference_dir)/"manifest.json"
        manifest = json.loads(source.read_text()) if source.exists() else {}
        overrides_path=Path(__file__).resolve().parent.parent/"reference/corporate_reference_overrides.json"
        overrides={}
        if overrides_path.exists():
            for item in json.loads(overrides_path.read_text()):
                if item["announced_at"]>item["ex_date"]:raise ValueError("Reference disclosure after ex-date")
                overrides[(item["symbol"],item["ex_date"])]=item
        return cls(frames, states, events, {
            "provider":"BaoStock 0.9.4", "fields":["isST","tradestatus","preclose"],
            "raw_close_compared":compared,"raw_close_mismatched":mismatched,
            "missing_files":missing_files,"read_failures":failures,
            "reference_downloaded_at":manifest.get("downloaded_at"),
            "reference_manifest_sha256":__import__("hashlib").sha256(source.read_bytes()).hexdigest() if source.exists() else None,
        },overrides)


@dataclass(frozen=True)
class ReversalSpec:
    key: str
    title: str
    top_n: int = 20
    every: int = 1
    min_amount: float = 0
    min_price: float = 0
    keep_rank: int = 20
    recent_risk_days: bool = False
    trend_filter: bool = False
    weight: float = .95


SPECS = (
    ReversalSpec("base", "基础 5DR · 每日最低20只"),
    ReversalSpec("liquid", "5DR + 流动性", min_amount=20_000_000, min_price=3),
    ReversalSpec("buffer", "5DR + 流动性 + 排名缓冲", min_amount=20_000_000, min_price=3, keep_rank=60),
    ReversalSpec("weekly", "5DR + 缓冲 + 每5日调仓", every=5, min_amount=20_000_000, min_price=3, keep_rank=60),
    ReversalSpec("risk", "5DR + 缓冲 + 60日风险冷静期", min_amount=20_000_000, min_price=3, keep_rank=60, recent_risk_days=True),
)


class Reversal5DR:
    """Only read rows <= i; universe and ranks are recomputed point in time."""
    def __init__(self, spec):
        self.spec = spec

    def weights(self, panel, i, holdings, day_number):
        s, a = self.spec, panel.arrays
        eligible = (panel.states["isST"][i]==0)&(panel.states["tradestatus"][i]==1)
        eligible &= (panel.age[i]>=60)&panel.valid20[i]&np.isfinite(panel.ret5[i])
        eligible &= (a["amt"][i]>0)&(a["num_trades"][i]>0)&(a["close"][i]>=s.min_price)
        eligible &= np.isfinite(panel.mean_amt[i])&(panel.mean_amt[i]>=s.min_amount)
        if s.recent_risk_days:
            eligible &= panel.last_risk60[i]==0
        if s.trend_filter:
            eligible &= panel.adjusted[i]>panel.ma60[i]
        eligible_indices = np.flatnonzero(eligible)
        # Stable code tie-break; never rely on physical input column ordering.
        ranked = sorted(eligible_indices, key=lambda j:(panel.ret5[i,j],panel.symbols[j]))
        ranks = {j:k+1 for k,j in enumerate(ranked)}
        emergency = {j for j in holdings if not eligible[j]}
        if day_number % s.every and not emergency:
            return None, {"eligible":len(ranked),"rebalance":False}
        if day_number % s.every:
            # Exit newly ineligible positions immediately, without adding new names.
            selected = sorted((j for j in holdings if eligible[j]),key=lambda j:ranks[j])[:s.top_n]
        else:
            selected = sorted((j for j in holdings if ranks.get(j,10**9)<=s.keep_rank),
                              key=lambda j:ranks[j])[:s.top_n]
            for j in ranked:
                if len(selected)>=s.top_n: break
                if j not in selected: selected.append(j)
        weight = s.weight/s.top_n
        return {j:weight for j in selected}, {"eligible":len(ranked),"rebalance":True,
                "selected":len(selected),"forced_exits":len(emergency)}


@dataclass(frozen=True)
class PrecisionConfig:
    cash: float = 1_000_000
    commission: float = .0003
    min_commission: float = 5
    stamp: float = .0005
    transfer: float = .00001
    slippage_bps: float = 5
    participation: float = .01
    dividend_tax: float = .20
    impairment_after: int = 20
    allow_missing_actions: bool = False

    def __post_init__(self):
        if not math.isfinite(self.cash) or self.cash<=0:
            raise ValueError("Invalid capital")
        for k in ("commission","stamp","transfer","participation","dividend_tax"):
            if not math.isfinite(getattr(self,k)) or not 0<=getattr(self,k)<=1:
                raise ValueError(f"Invalid {k}")
        if (not math.isfinite(self.slippage_bps) or not 0<=self.slippage_bps<10000 or
                not math.isfinite(self.min_commission) or self.min_commission<0 or
                not isinstance(self.impairment_after,int) or self.impairment_after<1):
            raise ValueError("Invalid execution assumptions")


class MissingActions(ValueError):
    pass


@dataclass(frozen=True)
class PrecisionContext:
    date: pd.Timestamp
    symbols: tuple
    cash: float
    equity: float
    positions: object
    _history: object
    _states: object

    def history(self,field="close",lookback=None,adjusted=True):
        return self._history(field,lookback,adjusted)

    def states(self,field="isST",lookback=None):
        return self._states(field,lookback)


class PrecisionEngine:
    def __init__(self, panel, config=None):
        self.p = panel
        self.config = config or PrecisionConfig()

    def run(self, strategy, start, end):
        p,cfg = self.p,self.config
        dates = p.dates[(p.dates>=pd.Timestamp(start))&(p.dates<=pd.Timestamp(end))]
        if len(dates)<2: raise ValueError("Need at least 2 sessions")
        first,last = p.locations[dates[0]],p.locations[dates[-1]]
        if first<60: raise ValueError("Need pre-period warm-up")
        a,st = p.arrays,p.states
        n = len(p.symbols)
        shares = np.zeros(n); marks = np.zeros(n); missing_days = np.zeros(n,int)
        cash = cfg.cash
        pending = []
        receivables = []
        locks = []
        entitlements = {}
        orders,positions,equity,signals,actions,valuation = [],[],[],[],[],[]
        missing_actions = set()
        event_discrepancies=[]
        previous = peak = cfg.cash
        event_register, event_operate = {},{}
        for (symbol,year), events in p.events.items():
            if symbol not in p.index: continue
            for event in events:
                for field,target in (("dividRegistDate",event_register),("dividOperateDate",event_operate)):
                    if event.get(field): target.setdefault(event[field],[]).append((p.index[symbol],event))
        def decision(i,eq,day_number):
            if hasattr(strategy,"on_close"):
                def window(field,lookback,adjusted):
                    if field not in p.frames:raise ValueError("Unknown field")
                    if lookback is not None and (not isinstance(lookback,int) or lookback<1):raise ValueError("Invalid lookback")
                    begin=max(0,i+1-lookback) if lookback else 0
                    frame=p.frames[field].iloc[begin:i+1].copy(deep=True)
                    if adjusted:
                        if field not in ("open","high","low","close"):raise ValueError("Only prices can be adjusted")
                        frame=frame.where(frame>0)*p.frames["cumadj"].iloc[begin:i+1].where(lambda x:x>0)
                    return frame
                def states(field,lookback):
                    if field not in p.states:raise ValueError("Unknown state field")
                    if lookback is not None and (not isinstance(lookback,int) or lookback<1):raise ValueError("Invalid lookback")
                    begin=max(0,i+1-lookback) if lookback else 0
                    return pd.DataFrame(p.states[field][begin:i+1].copy(),index=p.dates[begin:i+1],columns=p.symbols)
                context=PrecisionContext(p.dates[i],p.symbols,cash,eq,
                                         MappingProxyType({p.symbols[j]:shares[j] for j in range(n)}),window,states)
                raw=strategy.on_close(context)
                if raw is None:return None,{}
                from .engine import validate_weights
                raw=validate_weights(raw,p.symbols)
                return {p.index[s]:w for s,w in raw.items() if st["isST"][i,p.index[s]]==0},{}
            raw,diagnostic=strategy.weights(p,i,{j:shares[j] for j in np.flatnonzero(shares>1e-8)},day_number)
            if raw is not None:
                if any(not isinstance(j,(int,np.integer)) or j<0 or j>=n or not math.isfinite(w) or not 0<=w<=1 for j,w in raw.items()) or sum(raw.values())>1+1e-10:
                    raise ValueError("Invalid strategy weights")
            return raw,diagnostic

        # Warm-up signals are permitted; performance and starting cash begin on first session.
        def make_orders(i, weights, eq):
            plans=[]
            for j in sorted(set(np.flatnonzero(shares>1e-8))|set(weights),key=lambda j:p.symbols[j]):
                price=a["close"][i,j]
                if not np.isfinite(price) or price<=0:
                    if shares[j]>0 and j not in weights:
                        plans.append((j,"SELL",shares[j],shares[j],np.nan))
                    continue
                star=p.symbols[j].startswith(("688","689"))
                step,minimum=(1,200) if star else (100,100)
                target=math.floor(weights.get(j,0)*eq/price/step)*step
                if 0<target<minimum: target=0
                gap=target-shares[j]
                if abs(gap)<1e-8: continue
                side="BUY" if gap>0 else "SELL"
                requested=abs(gap)
                cap=max(0,p.mean_amt[i,j]*cfg.participation/price) if np.isfinite(p.mean_amt[i,j]) else 0
                qty=min(requested,cap,50_000)
                if side=="SELL" and target==0 and qty>=shares[j]-1e-8:
                    qty=shares[j]
                else:
                    qty=math.floor(qty/step)*step
                if side=="BUY" and qty<minimum: qty=0
                if side=="SELL" and star and qty<200 and qty<shares[j]-1e-8: qty=0
                plans.append((j,side,requested,qty,price))
            return sorted(plans,key=lambda v:(v[1]=="BUY",p.symbols[v[0]]))

        warm_weights,_=decision(first-1,cfg.cash,0)
        if warm_weights is not None:
            pending=make_orders(first-1,warm_weights,cfg.cash)
        for day_number,i in enumerate(range(first,last+1)):
            date=str(p.dates[i].date()); signal_date=str(p.dates[i-1].date())
            day_fees=day_tax=day_turnover=0.0
            # Settle only when cash is actually payable / additional shares tradable.
            remaining=[]
            for item in receivables:
                if item["pay_date"]<=date:
                    cash+=item["amount"]
                    actions.append({"date":date,"symbol":item["symbol"],"type":"DIVIDEND_PAID","cash_delta":item["amount"],"shares_delta":0,"receivable_delta":-item["amount"]})
                else: remaining.append(item)
            receivables=remaining
            locks=[item for item in locks if item["release"]>date]
            processed=set()
            for j,event in event_operate.get(date,[]):
                entitlement=entitlements.pop((j,event["dividOperateDate"],event.get("dividRegistDate","")),None)
                if entitlement is None:
                    # No pre-period position; a registration date before performance start has no entitlement.
                    entitlement=0
                if entitlement<=0: continue
                def value(key):
                    v=event.get(key,"")
                    return float(v) if v not in (None,"") else 0.0
                dividend=value("dividCashPsBeforeTax")
                bonus=value("dividStocksPs")
                reserve=value("dividReserveToStockPs")
                prior=a["close"][i-1,j]
                override=p.reference_overrides.get((p.symbols[j],date))
                if override and (abs(dividend-override["actual_cash_per_share"])>1e-7 or abs(bonus+reserve-override["actual_share_ratio"])>1e-7):
                    event_discrepancies.append({"date":date,"symbol":p.symbols[j],"reason":"ACTUAL_DISTRIBUTION_DISAGREES_WITH_ISSUER"})
                reference_cash=override["reference_cash_per_share"] if override else dividend
                reference_shares=override["reference_share_ratio"] if override else bonus+reserve
                expected_ref=(prior-reference_cash)/(1+reference_shares)
                observed_ref=st["preclose"][i,j]
                reference_error=abs(expected_ref-observed_ref) if np.isfinite(observed_ref) else np.nan
                if not np.isfinite(reference_error) or reference_error>max(.02,abs(expected_ref)*.0001):
                    event_discrepancies.append({"date":date,"symbol":p.symbols[j],"expected_reference":expected_ref,"provider_reference":observed_ref})
                gross=money_product(entitlement,dividend)
                # Conservative fixed 20% cash-dividend withholding, not a claim of exact personal tax.
                net=money_product(gross,1-cfg.dividend_tax)
                pay=event.get("dividPayDate") or date
                extra=math.floor(entitlement*(bonus+reserve)+1e-8)
                delivery=event.get("dividStockMarketDate") or date
                if extra:
                    shares[j]+=extra
                    if delivery>date: locks.append({"j":j,"shares":extra,"release":delivery})
                if pay<=date: cash+=net
                else: receivables.append({"symbol":p.symbols[j],"amount":net,"pay_date":pay})
                day_tax+=gross-net
                actions.append({"date":date,"symbol":p.symbols[j],"type":"EX_DIVIDEND_OR_BONUS",
                                "cash_delta":net if pay<=date else 0,"shares_delta":extra,
                                "receivable_delta":net if pay>date else 0,"gross_dividend":gross,
                                "dividend_tax":gross-net,"cash_pay_date":pay,"stock_release_date":delivery,
                                "stock_date_assumed":bool(extra and not event.get("dividStockMarketDate")),
                                "cash_per_share":dividend,"bonus_per_share":bonus,"reserve_per_share":reserve,
                                "reference_error":reference_error,"reference_cash_per_share":reference_cash,
                                "reference_share_ratio":reference_shares,"reference_override_source":override["source"] if override else ""})
                processed.add(j)
                if not np.isfinite(a["close"][i,j]) and np.isfinite(st["preclose"][i,j]):
                    marks[j]=st["preclose"][i,j]
            factor_change=(a["cumadj"][i]/a["cumadj"][i-1]-1)
            event_day=np.isfinite(factor_change)&(np.abs(factor_change)>1e-5)
            for j in np.flatnonzero((shares>0)&event_day):
                if j not in processed:
                    events=p.events.get((p.symbols[j],p.dates[i].year))
                    # Known empty history cannot explain a material factor event.
                    missing_actions.add((p.symbols[j],int(p.dates[i].year)))
                    if cfg.allow_missing_actions:
                        delta=shares[j]*factor_change[j]
                        shares[j]+=delta
                        actions.append({"date":date,"symbol":p.symbols[j],"type":"PROVISIONAL_FACTOR_UNITS","cash_delta":0,"shares_delta":delta,"receivable_delta":0})
            # Fixed quantities originate at t-1 close; no t-open portfolio sizing.
            for j,side,requested,planned,reference in pending:
                row={"order_id":len(orders)+1,"signal_date":signal_date,"execution_date":date,
                     "symbol":p.symbols[j],"side":side,"requested_qty":requested,"planned_qty":planned,
                     "sizing_reference_close":reference,"filled_qty":0.,"raw_execution_price":None,
                     "notional":0.,"commission":0.,"stamp_tax":0.,"transfer_fee":0.,
                     "status":"REJECTED","reason":"","cash_after":cash,"lower_limit":None,"upper_limit":None}
                row.update(signal_is_st=st["isST"][i-1,j],execution_is_st=st["isST"][i,j],
                           historical_preclose=st["preclose"][i,j],lagged_mean_amount20=p.mean_amt[i-1,j],
                           raw_open=a["open"][i,j])
                def reject(reason):
                    row["reason"]=reason;orders.append(row)
                raw=a["open"][i,j]
                if not np.isfinite(st["isST"][i,j]) or not np.isfinite(st["tradestatus"][i,j]):
                    reject("UNKNOWN_HISTORICAL_STATE");continue
                if side=="BUY" and st["isST"][i,j]!=0:
                    reject("ST_EXCLUDED_AT_EXECUTION");continue
                if side=="BUY" and st["isST"][i-1,j]!=0:
                    reject("ST_OR_UNKNOWN_AT_SIGNAL");continue
                if side=="BUY" and p.age[i-1,j]<60:
                    reject("INSUFFICIENT_LISTING_HISTORY_FOR_RULE_LIMITS");continue
                if st["tradestatus"][i,j]!=1:
                    reject("SUSPENDED");continue
                if not np.isfinite(raw) or raw<=0:
                    reject("MISSING_OPEN");continue
                if not np.isfinite(a["amt"][i,j]) or a["amt"][i,j]<=0 or not np.isfinite(a["num_trades"][i,j]) or a["num_trades"][i,j]<=0:
                    reject("ZERO_OR_MISSING_FULL_DAY_TRADING");continue
                if event_day[j]:
                    reject("CORPORATE_ACTION_CANCEL_REPLAN_AT_CLOSE");continue
                preclose=st["preclose"][i,j]
                if not np.isfinite(preclose) or preclose<=0:
                    reject("MISSING_OFFICIAL_REFERENCE_PROXY");continue
                rate=.20 if p.symbols[j].startswith(("300","301","302","688","689")) else .10
                # Main-board ST limit widened on 2026-07-06; ChiNext/STAR stay 20%.
                if st["isST"][i,j]!=0 and rate==.10 and date<"2026-07-06": rate=.05
                lower,upper=bounds(preclose,rate)
                row.update(lower_limit=lower,upper_limit=upper)
                if raw<lower-.005 or raw>upper+.005:
                    reject("OPEN_OUTSIDE_RULE_BOUNDS");continue
                if side=="BUY" and raw>=upper-.000001:
                    reject("LIMIT_UP_CANNOT_BUY");continue
                if side=="SELL" and raw<=lower+.000001:
                    reject("LIMIT_DOWN_CANNOT_SELL");continue
                slip=cfg.slippage_bps/10000
                price=(math.ceil(raw*(1+slip)*100-1e-8) if side=="BUY" else math.floor(raw*(1-slip)*100+1e-8))/100
                if price<=0 or price>upper+1e-8 or price<lower-1e-8:
                    reject("SLIPPAGE_OUTSIDE_BOUNDS");continue
                if side=="BUY" and price>=upper-1e-8:
                    reject("SLIPPAGE_AT_LIMIT_UP");continue
                if side=="SELL" and price<=lower+1e-8:
                    reject("SLIPPAGE_AT_LIMIT_DOWN");continue
                # A daily-bar feasibility veto; never use today's high/low to select stocks.
                if not a["low"][i,j]-.005<=price<=a["high"][i,j]+.005:
                    reject("SLIPPAGE_OUTSIDE_OBSERVED_RANGE");continue
                star=p.symbols[j].startswith(("688","689"));step,minimum=(1,200) if star else (100,100)
                qty=planned
                if side=="SELL":
                    locked=sum(v["shares"] for v in locks if v["j"]==j)
                    qty=min(qty,max(0,shares[j]-locked))
                    if qty<shares[j]-1e-8: qty=math.floor(qty/step)*step
                    if star and qty<200 and qty<shares[j]-1e-8: qty=0
                else:
                    # Broker risk check may shrink a pre-fixed buy; no strategy recomputation.
                    budget=max(0,min(cash-cfg.min_commission,cash/(1+cfg.commission+cfg.transfer)))
                    qty=min(qty,math.floor(budget/price/step)*step)
                    if qty<minimum:qty=0
                if qty<=0:
                    reject("CASH_LOT_CAPACITY_OR_DELIVERY_LOCK");continue
                notional=money_product(qty,price)
                commission=max(cfg.min_commission,money_product(notional,cfg.commission))
                stamp=money_product(notional,cfg.stamp) if side=="SELL" else 0.
                transfer=money_product(notional,cfg.transfer)
                fee=commission+stamp+transfer
                if side=="BUY":
                    if notional+fee>cash+1e-8:
                        reject("INSUFFICIENT_CASH_FOR_FEES");continue
                    cash-=notional+fee;shares[j]+=qty
                    locks.append({"j":j,"shares":qty,"release":str((p.dates[i]+pd.Timedelta(days=1)).date())})
                else:
                    cash+=notional-fee;shares[j]-=qty
                row.update(filled_qty=qty,raw_execution_price=price,notional=notional,
                           commission=commission,stamp_tax=stamp,transfer_fee=transfer,
                           status="FILLED" if abs(qty-requested)<1e-8 else "PARTIAL",
                           reason="FILLED" if abs(qty-requested)<1e-8 else "LOT_CAPACITY_CASH_OR_LOCK",
                           cash_after=cash)
                orders.append(row);day_fees+=fee;day_turnover+=notional
                if cash<-.00001 or (shares<-1e-8).any():raise ArithmeticError("Negative cash/position")
            pending=[]
            good=np.isfinite(a["close"][i])&(a["close"][i]>0)
            marks[good]=a["close"][i,good]
            missing_days[good]=0
            missing_days[~good]+=1
            carried=marks.copy()
            marks[missing_days>=cfg.impairment_after]=0
            # Do not describe a write-down as a sale: shares remain and cash does not change.
            for j in np.flatnonzero((shares>0)&(~good)):
                valuation.append({"date":date,"symbol":p.symbols[j],"shares":shares[j],"last_mark":carried[j],
                                  "missing_days":int(missing_days[j]),"valuation_mark":marks[j],
                                  "type":"IMPAIRMENT_TO_ZERO" if missing_days[j]>=cfg.impairment_after else "STALE_MARK"})
            outstanding=sum(x["amount"] for x in receivables)
            value=float(np.dot(shares,marks));eq=cash+value+outstanding
            peak=max(peak,eq)
            equity.append({"date":date,"cash":cash,"market_value":value,"dividend_receivable":outstanding,
                           "equity":eq,"net_value":eq/cfg.cash,"daily_return":eq/previous-1,
                           "drawdown":eq/peak-1,"fees":day_fees,"dividend_tax":day_tax,
                           "traded_notional":day_turnover,"exposure":value/eq,
                           "stale_positions":int(((shares>0)&(~good)).sum()),
                           "impaired_positions":int(((shares>0)&(missing_days>=cfg.impairment_after)).sum())})
            previous=eq
            for j in np.flatnonzero(shares>1e-8):
                positions.append({"date":date,"symbol":p.symbols[j],"shares":shares[j],
                                  "raw_close":a["close"][i,j],"valuation_mark":marks[j],"market_value":shares[j]*marks[j],
                                  "weight":shares[j]*marks[j]/eq,"is_st":st["isST"][i,j],
                                  "stale_days":int(missing_days[j]),"locked_shares":sum(x["shares"] for x in locks if x["j"]==j)})
            for j,event in event_register.get(date,[]):
                entitlements[(j,event["dividOperateDate"],event.get("dividRegistDate",""))]=shares[j]
            weights,diagnostic=decision(i,eq,day_number+1)
            if weights is not None:
                for j,w in weights.items():
                    signals.append({"signal_date":date,"symbol":p.symbols[j],"target_weight":w,
                                    "ret5":p.ret5[i,j],"is_st":st["isST"][i,j],"mean_amount20":p.mean_amt[i,j],
                                    "execution":"OUTSIDE_RANGE" if i==last else "NEXT_SESSION_OPEN_PROXY"})
                if i<last:pending=make_orders(i,weights,eq)
        if missing_actions and not cfg.allow_missing_actions:
            raise MissingActions("Unverified held corporate actions: "+str(sorted(missing_actions)))
        if event_discrepancies and not cfg.allow_missing_actions:
            raise MissingActions("Corporate events disagree with historical preclose: "+str(event_discrepancies))
        frame=pd.DataFrame(equity)
        order_columns=["order_id","signal_date","execution_date","symbol","side","requested_qty","planned_qty",
                       "sizing_reference_close","filled_qty","raw_execution_price","notional","commission","stamp_tax",
                       "transfer_fee","status","reason","cash_after","lower_limit","upper_limit","signal_is_st",
                       "execution_is_st","historical_preclose","lagged_mean_amount20","raw_open"]
        order_frame=pd.DataFrame(orders,columns=order_columns)
        returns=frame.daily_return
        vol=float(returns.std(ddof=1))
        filled=order_frame[order_frame.notional>0] if len(order_frame) else order_frame
        metrics={"start":str(dates[0].date()),"end":str(dates[-1].date()),"trading_days":len(dates),
                 "initial_cash":cfg.cash,"final_equity":float(frame.equity.iloc[-1]),
                 "total_return":float(frame.net_value.iloc[-1]-1),
                 "annualized_return":float(frame.net_value.iloc[-1]**(252/len(dates))-1),
                 "max_drawdown":float(frame.drawdown.min()),
                 "sharpe_zero_risk_free":float(returns.mean()/vol*252**.5) if vol>1e-12 else None,
                 "total_fees":float(frame.fees.sum()),"dividend_tax":float(frame.dividend_tax.sum()),
                 "filled_orders":len(filled),"rejected_orders":int((order_frame.status=="REJECTED").sum()) if len(order_frame) else 0,
                 "turnover_one_way":float(frame.traded_notional.sum()/frame.equity.mean()/2),
                 "average_exposure":float(frame.exposure.mean()),
                 "stale_valuation_days":int((frame.stale_positions>0).sum()),
                 "ending_impaired_positions":int(frame.impaired_positions.iloc[-1]),
                 "missing_actions":[list(x) for x in sorted(missing_actions)],
                 "event_reference_discrepancies":event_discrepancies,
                 "rejection_reasons":order_frame.loc[order_frame.status=="REJECTED","reason"].value_counts().to_dict() if len(order_frame) else {}}
        return {"equity":frame,"orders":order_frame,"positions":pd.DataFrame(positions,columns=["date","symbol","shares","raw_close","valuation_mark","market_value","weight","is_st","stale_days","locked_shares"]),
                "signals":pd.DataFrame(signals,columns=["signal_date","symbol","target_weight","ret5","is_st","mean_amount20","execution"]),
                "actions":pd.DataFrame(actions) if actions else pd.DataFrame(columns=["date","symbol","type","cash_delta","shares_delta","receivable_delta"]),
                "valuation":pd.DataFrame(valuation,columns=["date","symbol","shares","last_mark","missing_days","valuation_mark","type"]),
                "metrics":metrics,"spec":asdict(strategy.spec) if hasattr(strategy,"spec") else {"key":type(strategy).__name__,"title":type(strategy).__name__},"config":asdict(cfg)}
