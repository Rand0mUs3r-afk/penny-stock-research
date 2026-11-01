"""Targets fixed before entry; RR is informational unless explicitly gated."""
from math import isfinite
from .risk import adverse_price

POLICY={'min_price':1.0,'max_price':35.0,'target_mode':'pre_pullback_high','minimum_net_rr':None,'hold_mode':'session_end'}

def previous_high(history,lookback):
    base=history[-lookback-2:-2]
    if len(base)!=lookback:
        return None
    high=max(b.high for b in base)
    stamp=max(b.timestamp for b in base if b.high==high)
    return {'target':high,'reference_time':stamp.isoformat(),'reference_rule':f'highest_high_of_{lookback}_completed_bars_before_pullback_and_confirmation'}

def raw_price_allowed(price,policy):
    return isfinite(price) and policy['min_price']<=price<=policy['max_price']

def net_plan(entry,stop,target,shares,planned_risk,cfg):
    reward=shares*(adverse_price(target,False,cfg)-entry)-2*cfg.fee_per_order
    ratio=reward/planned_risk if planned_risk>0 else None
    return {'target':target,'expected_net_reward':reward,'planned_net_risk':planned_risk,'expected_net_rr':ratio}
