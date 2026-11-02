"""Separate long-only, unlevered SPY noise-band/VWAP benchmark adaptation."""
from collections import defaultdict
from datetime import datetime,timedelta
from statistics import mean
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')

def bands(prior,today_open,previous_close,slot,minimum=14):
    chosen=prior[-minimum:]
    if len(chosen)<minimum or any(slot not in day for day in chosen):
        return None
    sigma=mean(abs(day[slot].close/day[min(day)].open-1) for day in chosen)
    return max(today_open,previous_close)*(1+sigma)

def run(bars,cfg,session_closes,minimum=14,evaluation_start="",action_days=()):
    if len({b.symbol for b in bars})>1:
        raise ValueError('Benchmark accepts one ETF only')
    groups=defaultdict(list)
    for b in bars:
        groups[b.timestamp.astimezone(NY).date().isoformat()].append(b)
    cash=cfg.starting_equity
    trades,curve,prior=[],[],[]
    peak=cash
    drawdown=0.
    previous_close=None
    for day in sorted(set(groups)|set(action_days)):
        items=sorted(groups.get(day,[]),key=lambda b:b.timestamp)
        if day in action_days:
            prior.clear()
            previous_close=None
            continue
        close=session_closes.get(day)
        if not close:
            raise ValueError('Benchmark calendar missing')
        if items[0].timestamp.astimezone(NY).strftime('%H:%M')!='09:35' or items[-1].timestamp.astimezone(NY).strftime('%H:%M')!=close or any(b.timestamp-a.timestamp!=timedelta(minutes=5) for a,b in zip(items,items[1:])) or any(b.volume<=0 for b in items):
            prior.clear()
            previous_close=None
            continue
        position=pending=None
        total=volume=0.
        mapping={b.timestamp.astimezone(NY).strftime('%H:%M'):b for b in items}
        for index,b in enumerate(items):
            local=b.timestamp.astimezone(NY)
            at_close=local.strftime('%H:%M')==close
            if pending:
                stop,stamp=pending
                pending=None
                entry=b.open*(1+cfg.spread_bps/20000+cfg.slippage_bps/10000)
                per_share=entry-stop*(1-cfg.spread_bps/20000-cfg.slippage_bps/10000)
                shares=int(min((cash-cfg.fee_per_order)/entry,cfg.allocation/entry,max(0,min(cfg.risk_per_position,cfg.portfolio_risk_cap if cfg.portfolio_risk_cap is not None else cfg.risk_per_position)-2*cfg.fee_per_order)/per_share,items[index-1].volume*cfg.max_volume_fraction)) if entry>stop and per_share>0 else 0
                if shares>0:
                    cash-=shares*entry+cfg.fee_per_order
                    position={'entry':entry,'raw_entry':b.open,'stop':stop,'shares':shares,'signal_time':stamp.isoformat(),'entry_time':items[index-1].timestamp.isoformat()}
            if position:
                p=position
                raw,why=(b.open,'gap_stop') if b.open<=p['stop'] else (p['stop'],'trailing_stop') if b.low<=p['stop'] else (b.close,'session_end') if at_close else (None,None)
                if raw is not None:
                    exit_price=raw*(1-cfg.spread_bps/20000-cfg.slippage_bps/10000)
                    cash+=p['shares']*exit_price-cfg.fee_per_order
                    pnl=p['shares']*(exit_price-p['entry'])-2*cfg.fee_per_order
                    trades.append({'symbol':b.symbol,'strategy':'noise_band_vwap_adaptation','signal_time':p['signal_time'],'entry_time':p['entry_time'],'exit_time':b.timestamp.isoformat(),'entry':p['entry'],'exit':exit_price,'shares':p['shares'],'net_pnl':pnl,'exit_reason':why,'raw_entry':p['raw_entry'],'raw_exit':raw,'gross_pnl':p['shares']*(raw-p['raw_entry']),'modeled_spread_cost':p['shares']*(raw+p['raw_entry'])*cfg.spread_bps/20000,'modeled_slippage_cost':p['shares']*(raw+p['raw_entry'])*cfg.slippage_bps/10000,'fees':2*cfg.fee_per_order,'hold_minutes':(b.timestamp-datetime.fromisoformat(p['entry_time'])).total_seconds()/60})
                    position=None
            total+=(b.high+b.low+b.close)/3*b.volume
            volume+=b.volume
            vwap=total/volume
            if local.minute%30==0:
                if position:
                    position['stop']=max(position['stop'],vwap)
                elif not at_close and local.hour<15 and previous_close and day>=evaluation_start:
                    upper=bands(prior,items[0].open,previous_close,local.strftime('%H:%M'),minimum)
                    if upper and b.close>max(upper,vwap) and vwap<b.close:
                        pending=(vwap,b.timestamp)
            equity=cash+(position['shares']*b.close*(1-cfg.spread_bps/20000-cfg.slippage_bps/10000)-cfg.fee_per_order if position else 0)
            peak=max(peak,equity)
            drawdown=max(drawdown,(peak-equity)/peak)
            curve.append({'timestamp':b.timestamp.isoformat(),'equity':equity,'cash':cash})
        if position:
            raise ValueError('Benchmark failed session liquidation')
        prior.append(mapping)
        previous_close=items[-1].close
    return {'summary':{'starting_equity':cfg.starting_equity,'ending_equity':cash,'net_pnl':cash-cfg.starting_equity,'trades':len(trades),'max_drawdown':drawdown},'trades':trades,'equity_curve':curve,'exit_policy':'30-minute ratcheted completed-bar VWAP stop, checked on subsequent bars; session-end liquidation','replication':'long-only unlevered adaptation, not exact published model'}
