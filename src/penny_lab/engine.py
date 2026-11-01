"""Five-minute retrospective simulation; structural targets are opt-in via manifest."""
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import time,timedelta
from statistics import mean
from zoneinfo import ZoneInfo
from .models import Position,Trade
from .providers.base import CoverageError
from .risk import adverse_price,size_position
from .strategies import scan
from .target_policy import previous_high,raw_price_allowed,net_plan

NY=ZoneInfo('America/New_York')
ENGINE_VERSION='structural-target-v4'

def rank_trades(trades,strategies):
    rows=[]
    for name in strategies:
        chosen=[t for t in trades if t.strategy==name]
        gains=sum(max(t.net_pnl,0) for t in chosen)
        losses=-sum(min(t.net_pnl,0) for t in chosen)
        expectancy=mean(t.net_pnl for t in chosen) if chosen else None
        rows.append({'strategy':name,'trades':len(chosen),'net_pnl':sum(t.net_pnl for t in chosen),'expectancy':expectancy,'win_rate':sum(t.net_pnl>0 for t in chosen)/len(chosen) if chosen else None,'profit_factor':gains/losses if losses else None,'status':'exploratory_in_sample' if chosen else 'no_trades'})
    return sorted(rows,key=lambda r:(r['expectancy'] is None,-(r['expectancy'] or 0),r['strategy']))

def exit_decision(bar,position,at_close):
    if bar.open<=position.stop:
        return bar.open,'gap_through_stop'
    if bar.low<=position.stop:
        return position.stop,'stop_and_target_same_bar' if bar.high>=position.target else 'stop'
    if bar.high>=position.target:
        return position.target,'target'
    return (bar.close,'session_end') if at_close else (None,'')

def run(bars,cfg,manifest):
    if cfg.universe!='listed_under_10' or manifest.get('universe')!=cfg.universe:
        raise CoverageError('OTC requires a dedicated data integration; no silent substitution')
    sessions=manifest.get('session_closes',{})
    if not sessions:
        raise CoverageError('Explicit exchange-calendar session_closes required in manifest')
    policy=manifest.get('entry_policy')
    if policy and (policy.get('target_mode')!='pre_pullback_high' or policy.get('hold_mode')!='session_end' or policy.get('minimum_net_rr',0)<=0):
        raise ValueError('Unsupported structural target policy')
    groups,seen=defaultdict(list),set()
    for bar in bars:
        key=(bar.symbol,bar.timestamp)
        if key in seen:
            raise ValueError('Duplicate bar')
        seen.add(key)
        local=bar.timestamp.astimezone(NY)
        day=local.date().isoformat()
        if day not in sessions:
            raise CoverageError(f'Calendar missing for {day}')
        closing=time.fromisoformat(sessions[day])
        if not time(9,35)<=closing<=time(16):
            raise CoverageError('Invalid session close')
        if time(9,35)<=local.time()<=closing:
            if bar.volume<=0:
                raise CoverageError('Zero-volume bars cannot establish executable fills; clean or investigate input')
            if local.second or local.microsecond or local.minute%5:
                raise ValueError('Bars must align to five-minute boundaries')
            groups[(day,bar.symbol)].append(bar)
    if not groups:
        raise CoverageError('No regular-hours bars')
    events=defaultdict(list)
    for (day,symbol),items in groups.items():
        items.sort(key=lambda b:b.timestamp)
        if items[-1].timestamp.astimezone(NY).time()!=time.fromisoformat(sessions[day]):
            raise CoverageError(f'{symbol} {day}: missing session-close bar; cannot fabricate liquidation')
        for bar in items:
            events[bar.timestamp].append(bar)
    cash=cfg.starting_equity
    positions,pending,histories,last_prices={},{},{},{}
    raw_entries,last_observed,references,entry_plans={},{},{},{}
    trades,rejects,curve,executions=[],[],[],[]
    max_equity,max_drawdown=cash,0.0
    step=timedelta(minutes=cfg.timeframe_minutes)
    def reject(stamp,symbol,reason):
        rejects.append({'timestamp':stamp.isoformat(),'symbol':symbol,'reason':reason})
    for stamp,batch in sorted(events.items()):
        batch.sort(key=lambda b:b.symbol)
        current={b.symbol:b for b in batch}
        for symbol in positions:
            if symbol not in current or stamp-last_observed[symbol]!=step:
                raise CoverageError(f'{symbol}: unresolved gap while position open; no guessed stop or liquidation')
        waiting,pending=pending,{}
        for symbol,(signal,prior_volume) in sorted(waiting.items(),key=lambda item:(-item[1][0].score,item[0])):
            bar=current.get(symbol)
            if bar is None or stamp-signal.timestamp!=step:
                reject(stamp,symbol,'missing_next_bar; pending signal expired')
                continue
            if symbol in positions:
                reject(stamp,symbol,'duplicate_position')
                continue
            entry=adverse_price(bar.open,True,cfg)
            bad_price=not raw_price_allowed(bar.open,policy) if policy else entry>=cfg.max_price
            if bad_price or bar.open<=signal.stop:
                reject(stamp,symbol,'gap_invalidated_price_or_stop')
                continue
            room=cfg.risk_per_position if cfg.portfolio_risk_cap is None else max(0,cfg.portfolio_risk_cap-sum(p.planned_risk for p in positions.values()))
            shares,risk=size_position(entry,signal.stop,cash,room,prior_volume,cfg)
            if shares<=0:
                reject(stamp,symbol,'cash_risk_or_prior_volume_limit')
                continue
            if policy:
                reference=references.get((symbol,signal.timestamp))
                if not reference:
                    reject(stamp,symbol,'historical_high_reference_unavailable')
                    continue
                target=reference['target']
                if target<=bar.open:
                    reject(stamp,symbol,'historical_high_at_or_below_entry')
                    continue
                plan=net_plan(entry,signal.stop,target,shares,risk,cfg)
                if plan['expected_net_rr'] is None or plan['expected_net_rr']<policy['minimum_net_rr']:
                    reject(stamp,symbol,'historical_high_insufficient_net_rr')
                    continue
                entry_plans[symbol]={**reference,**plan,'target_frozen_at':signal.timestamp.isoformat(),'price_filter_basis':'raw_entry_price_inclusive','hold_mode':'session_end'}
            else:
                target=entry+cfg.reward_risk*(entry-signal.stop)
                entry_plans[symbol]={'target':target,'target_mode':'legacy_fixed_rr'}
            cash-=shares*entry+cfg.fee_per_order
            positions[symbol]=Position(signal,stamp-step,entry,shares,signal.stop,target,risk,cfg.fee_per_order)
            raw_entries[symbol]=bar.open
        for bar in batch:
            symbol=bar.symbol
            local=stamp.astimezone(NY)
            day=local.date().isoformat()
            at_close=local.time()==time.fromisoformat(sessions[day])
            position=positions.get(symbol)
            if position:
                raw_exit,why=exit_decision(bar,position,at_close)
                if raw_exit is not None:
                    exit_price=adverse_price(raw_exit,False,cfg)
                    cash+=position.shares*exit_price-cfg.fee_per_order
                    pnl=position.shares*(exit_price-position.entry)-position.entry_fee-cfg.fee_per_order
                    trades.append(Trade(symbol,position.signal.strategy,position.signal.timestamp.isoformat(),position.entry_time.isoformat(),stamp.isoformat(),position.entry,exit_price,position.shares,position.stop,position.target,position.planned_risk,pnl,why,position.signal.reason))
                    raw_entry=raw_entries.pop(symbol)
                    notional=position.shares*(raw_entry+raw_exit)
                    spread=notional*cfg.spread_bps/20000
                    slippage=notional*cfg.slippage_bps/10000
                    fees=position.entry_fee+cfg.fee_per_order
                    gross=position.shares*(raw_exit-raw_entry)
                    reconciled=gross-spread-slippage-fees
                    if abs(reconciled-pnl)>1e-7*max(1,abs(gross)):
                        raise ValueError('Trade cost reconciliation failed')
                    lower=stamp if why=='session_end' else stamp-step
                    executions.append({'trade_number':len(trades),'symbol':symbol,'strategy':position.signal.strategy,'signal_available_at':position.signal.timestamp.isoformat(),'order_submitted_at':position.signal.timestamp.isoformat(),'modeled_entry_at':position.entry_time.isoformat(),'entry_price_basis':'next_bar_open_plus_modeled_costs','exit_time_lower_bound':lower.isoformat(),'exit_time_upper_bound':stamp.isoformat(),'exit_time_exact':why=='session_end','raw_entry':raw_entry,'raw_exit':raw_exit,'shares':position.shares,'gross_price_pnl':gross,'modeled_spread_cost':spread,'modeled_slippage_cost':slippage,'fees':fees,'net_pnl':pnl,'reconciliation_error':pnl-reconciled,'planned_risk':position.planned_risk,'loss_exceeded_planned':-pnl>position.planned_risk+1e-8,'hold_minutes_upper_bound':(stamp-position.entry_time).total_seconds()/60,'hold_minutes_lower_bound':(lower-position.entry_time).total_seconds()/60,'exit_reason':why,**entry_plans.pop(symbol)})
                    del positions[symbol]
            last_prices[symbol]=bar.close
            last_observed[symbol]=stamp
            history=histories.setdefault((day,symbol),[])
            if history and stamp-history[-1].timestamp!=step:
                reject(stamp,symbol,'history_gap; setup warmup reset')
                history.clear()
            history.append(bar)
            if not at_close and symbol not in positions:
                if policy and not raw_price_allowed(bar.close,policy):
                    continue
                scan_cfg=replace(cfg,max_price=policy['max_price']+1e-8) if policy else cfg
                found=scan(history,scan_cfg)
                if found:
                    best=sorted(found,key=lambda s:(-s.score,s.strategy))[0]
                    if policy:
                        reference=previous_high(history,cfg.lookback)
                        if reference is None:
                            reject(stamp,symbol,'historical_high_reference_unavailable')
                            continue
                        references[(symbol,stamp)]=reference
                    pending[symbol]=(best,bar.volume)
                    for other in found:
                        if other is not best:
                            reject(stamp,symbol,f'overlapping_setup:{other.strategy};selected:{best.strategy}')
        equity=cash+sum(p.shares*adverse_price(last_prices[s],False,cfg)-cfg.fee_per_order for s,p in positions.items())
        max_equity=max(max_equity,equity)
        max_drawdown=max(max_drawdown,(max_equity-equity)/max_equity)
        curve.append({'timestamp':stamp.isoformat(),'equity':equity,'cash':cash,'open_positions':len(positions),'planned_open_risk':sum(p.planned_risk for p in positions.values())})
    if positions:
        raise CoverageError('Unclosed positions; no artificial end-of-data exits allowed')
    costs={k:sum(r[k] for r in executions) for k in ('gross_price_pnl','modeled_spread_cost','modeled_slippage_cost','fees','net_pnl')}
    costs['reconciliation_error']=costs['gross_price_pnl']-costs['modeled_spread_cost']-costs['modeled_slippage_cost']-costs['fees']-costs['net_pnl']
    return {'engine_version':ENGINE_VERSION,'summary':{'starting_equity':cfg.starting_equity,'ending_equity':cash,'net_pnl':cash-cfg.starting_equity,'trades':len(trades),'max_drawdown':max_drawdown,'evaluation':'exploratory_in_sample_not_validated'},'trades':[asdict(t) for t in trades],'execution_audit':executions,'cost_attribution':costs,'rejections':rejects,'equity_curve':curve,'strategy_ranking':rank_trades(trades,cfg.strategies),'config':cfg.to_dict(),'provenance':manifest,'limitations':['Five-minute retrospective sample; not quote-accurate execution','Complete-session positive-volume selection remains retrospective','Prior completed-bar volume sizing; no true depth or queue modeling','Same-bar stop/target collision is stop-first','Intrabar exit times are bounded, not known exactly','Costs attributed at the same fills, not a zero-cost strategy rerun','Session-end exit is a modeled fill, not guaranteed live execution','Immediate proceeds reuse; settlement/margin/PDT not modeled','No verified OTC execution, historical news gating, point-in-time universe or certified holdout']}
