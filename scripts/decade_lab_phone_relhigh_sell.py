# -*- coding: utf-8 -*-
"""相對高點賣出對質：起漲買 ×（首碰20高／浪頂事件／二者較早）出場。

使用者鎖死：相對高點＝賣股票。phone_sync=blocked。
"""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any, Dict, List
import numpy as np, pandas as pd
from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import KEEP_EXIT, _align_feat, _bool, _cores, _wave_hsiao_bank
from scripts.decade_lab_phone_market_wave_sync import _stock_wave_events
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits
from scripts.decade_lab_phone_trade_confront import FRICTION, MAX_HOLD, _agg_trades, _build_hl_temp

ART=Path('/opt/cursor/artifacts'); DOC=Path('docs/expert_notes/飆客/decade_lab')
PHONE_SYNC='blocked'

def _simulate_relhigh(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top: pd.Series, mode: str):
    """mode: hi20_or_desync | wave_top_next | hi20_or_wave_top"""
    from sell_discipline import classify_how_to_sell
    cl=df['close'].astype(float); op=df['open'].astype(float)
    hi=df['high'].astype(float); lo=df['low'].astype(float)
    n=len(df); trades=[]; i=0
    while i < n-2:
        if not bool(entry_mask.iloc[i]):
            i+=1; continue
        entry_i=i+1
        if entry_i>=n-1: break
        entry_px=float(op.iloc[entry_i])
        if not (np.isfinite(entry_px) and entry_px>0):
            i+=1; continue
        exit_i=None; exit_reason=None
        peak=entry_px; trough=entry_px
        for j in range(entry_i, min(n-1, entry_i+MAX_HOLD)):
            h=float(hi.iloc[j]); l=float(lo.iloc[j])
            if np.isfinite(h): peak=max(peak, h)
            if np.isfinite(l): trough=min(trough, l)
            hl_j=str(hl.iloc[j] or '')
            if j>entry_i:
                if mode in ('hi20_or_desync','hi20_or_wave_top') and hl_j=='20高':
                    exit_i=j+1; exit_reason='first_hi20'; break
                if mode=='hi20_or_desync':
                    flags=classify_how_to_sell(hl.iloc[j], temp_label.iloc[j])
                    if str(flags.get('sell_action') or '')=='直接減碼':
                        exit_i=j+1; exit_reason='sell_desync_cut'; break
                if mode in ('wave_top_next','hi20_or_wave_top') and bool(wave_top.iloc[j]):
                    exit_i=j+1; exit_reason='wave_rel_high'; break
        if exit_i is None:
            exit_i=min(n-1, entry_i+MAX_HOLD); exit_reason='max_hold_60'
        if exit_i>=n: exit_i=n-1
        exit_px=float(cl.iloc[exit_i]) if exit_reason=='max_hold_60' else float(op.iloc[exit_i] if np.isfinite(op.iloc[exit_i]) else cl.iloc[exit_i])
        if not (np.isfinite(exit_px) and exit_px>0):
            i=max(i+1, exit_i); continue
        net=exit_px/entry_px-1.0-FRICTION
        trades.append({
            'sid': sid,
            'entry_tag': entry_tag,
            'entry_i': entry_i,
            'exit_i': exit_i,
            'entry_date': str(df['date'].iloc[entry_i]) if 'date' in df.columns else str(entry_i),
            'exit_date': str(df['date'].iloc[exit_i]) if 'date' in df.columns else str(exit_i),
            'net_ret': net,
            'hold_days': int(exit_i - entry_i),
            'exit_reason': exit_reason,
            'win': int(net > 0),
            'mfe': peak / entry_px - 1.0,
            'mae': trough / entry_px - 1.0,
        })
        i=max(i+1, exit_i)
    return trades

def main():
    t0=time.time()
    uni=select_g_universe(n=100, include_twse_top100=True)
    symbols=uni['stock_id'].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols: symbols.append(sid)
    bucket={}
    meta_n=0; errors=[]
    modes=('hi20_or_desync','wave_top_next','hi20_or_wave_top')
    for sid in symbols:
        try:
            raw=load_stock_ohlcv(sid)
            if len(raw)<150: continue
            meta_n+=1
            df=_normalize_ohlc(raw)
            feat=_align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
            wave=_align_wave(df,_wave_frame(raw)); wmasks=_wave_masks(wave)
            masks=_build_mark_masks(df)
            cores=_cores(masks,wmasks,feat)
            bank=_wave_hsiao_bank(feat,wmasks,wave)
            ev=_stock_wave_events(raw,df)
            wave_top=(ev.get('LAB_W1_TOP')|ev.get('LAB_W3_TOP')|ev.get('LAB_SELL_W5_TOP')).fillna(False)
            hl,temp=_build_hl_temp(df)
            seed=abs(hash(sid))%(2**32)
            # entries: balanced champion style + pure w3
            entries={
                'w3': cores['core_w3_start'],
                'w3_or_ma60': cores['core_w3_or_ma60w3'],
                'bal_Vnear_or_S55': cores['core_w3_or_ma60w3'] & (bank['hsiao_V'].astype(float).rolling(3,min_periods=1).max().gt(0) | bank['score55']),
            }
            # fix V near using bank attack
            V=bank['hsiao_V'].fillna(False)
            Vnear=V.astype(float).rolling(3,min_periods=1).max().gt(0)
            entries['bal_Vnear_or_S55']=cores['core_w3_or_ma60w3'] & (Vnear | bank['score55'].fillna(False))
            for en,em in entries.items():
                for mode in modes:
                    key=f'{en}__SELL_{mode}'
                    bucket.setdefault(key,[]).extend(_simulate_relhigh(df, em.fillna(False), hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=mode))
                    pool=cores['core_w3_or_ma60w3'].fillna(False)|cores['core_w3_start'].fillna(False)
                    if int(pool.sum())<5: pool=pd.Series(True,index=df.index)
                    rnd=_random_matched(em.fillna(False), pool, seed=seed+len(key))
                    bucket.setdefault(f'random__{key}',[]).extend(_simulate_relhigh(df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f'rnd__{key}', wave_top=wave_top, mode=mode))
        except Exception as e:
            errors.append(f'{sid}:{type(e).__name__}:{e}')
    by={k:_agg_trades(v) for k,v in bucket.items()}
    ranking=[]
    for key,st in by.items():
        if key.startswith('random__'): continue
        rnd=by.get(f'random__{key}') or {}
        days=int(st.get('n_unique_entry_days') or 0); ok=days>=20
        win=float(st.get('win_rate') or np.nan); exp=float(st.get('expectancy') or np.nan)
        beats_r=bool(ok and np.isfinite(exp) and np.isfinite(rnd.get('expectancy',np.nan)) and exp>float(rnd['expectancy']) and win>float(rnd.get('win_rate') or -1))
        ranking.append({'key':key,'n_trades':st.get('n_trades'),'n_unique_entry_days':days,'win_rate':win,'expectancy':exp,'avg_hold':st.get('avg_hold'),'exit_reason_counts':st.get('exit_reason_counts'),'random_win_rate':rnd.get('win_rate'),'random_expectancy':rnd.get('expectancy'),'beats_random':beats_r,'balanced_score': (win*min(1.0,days/50.0) if ok and np.isfinite(win) else float('-inf'))})
    ranking.sort(key=lambda r:(int(r['beats_random']), float(r.get('balanced_score') or -9), float(r.get('win_rate') or -1)), reverse=True)
    winners=[r for r in ranking if r['beats_random']]
    gate=f"relhigh_sell winners={len(winners)}/{len(ranking)}; best={ranking[0]['key'] if ranking else None} win={ranking[0].get('win_rate') if ranking else None} days={ranking[0].get('n_unique_entry_days') if ranking else None}; promote_lookup=NO"
    out={'phone_sync':PHONE_SYNC,'not_buy_signal':True,'sell_lock_zh':'相對高點＝賣股票','elapsed_s':round(time.time()-t0,1),'n_stocks':meta_n,'ranking':ranking,'winners_beat_random':winners,'by_balanced':ranking[:15],'gate_one_liner':gate,'errors_n':len(errors),'errors_sample':errors[:8]}
    text=json.dumps(out,ensure_ascii=False,indent=2,default=str)
    (ART/'phone_relhigh_sell_latest.json').write_text(text,encoding='utf-8')
    (DOC/'phone_relhigh_sell_latest.json').write_text(text,encoding='utf-8')
    print('GATE',gate,flush=True)
    print('TOP',json.dumps(ranking[:6],ensure_ascii=False,default=str)[:1500],flush=True)

if __name__=='__main__':
    main()
