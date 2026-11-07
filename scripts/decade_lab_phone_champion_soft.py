# -*- coding: utf-8 -*-
"""Soft OR / mild V around champions — try lift days without killing winrate."""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np, pandas as pd
from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits
from scripts.decade_lab_phone_extreme_hillclimb import (
    _align_feat, _cores, _wave_hsiao_bank, KEEP_EXIT, CORE_NAMES, _bool
)
ART=Path('/opt/cursor/artifacts'); DOC=Path('docs/expert_notes/飆客/decade_lab')

def main():
    t0=time.time()
    uni=select_g_universe(n=100, include_twse_top100=True)
    symbols=uni['stock_id'].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols: symbols.append(sid)
    bucket={'leave_zero__hi20_or_desync':[],'random__leave_zero__hi20_or_desync':[]}
    meta_n=0; errors=[]
    for sid in symbols:
        try:
            raw=load_stock_ohlcv(sid)
            if len(raw)<150: continue
            meta_n+=1
            df=_normalize_ohlc(raw)
            feat=_align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
            wave=_align_wave(df,_wave_frame(raw)); wmasks=_wave_masks(wave)
            masks=_build_mark_masks(df); cores=_cores(masks,wmasks,feat)
            f=_wave_hsiao_bank(feat,wmasks,wave)
            hl,temp=__import__('scripts.decade_lab_phone_trade_confront',fromlist=['_build_hl_temp'])._build_hl_temp(df)
            seed=abs(hash(sid))%(2**32)
            lz=_bool(masks.get('leave_zero_blue_tri'), df.index)
            bucket['leave_zero__hi20_or_desync'].extend(_simulate_exits(df,lz,hl=hl,temp_label=temp,sid=sid,entry_tag='lz',exit_mode=KEEP_EXIT))
            bucket['random__leave_zero__hi20_or_desync'].extend(_simulate_exits(df,_random_matched(lz,pd.Series(True,index=df.index),seed=seed),hl=hl,temp_label=temp,sid=sid,entry_tag='rnd_lz',exit_mode=KEEP_EXIT))
            # soft factor defs
            V=f['hsiao_V']; Vm=f['hsiao_Vmild']; S55=f['score55']; macd=f['hsiao_macd']
            week=f['hsiao_week']; T=f['hsiao_T']; safe=f['wave_safe']
            soft={
                'D0': pd.Series(True,index=df.index),
                'V': V, 'Vmild': Vm, 'S55': S55, 'macd': macd,
                'V_or_S55': V|S55,
                'Vmild_or_S55': Vm|S55,
                'V_or_macd': V|macd,
                'VT': V&T,
                'Vmild_T': Vm&T,
                'V_or_S55_week': (V|S55)&week,
                'S55_or_macd': S55|macd,
                'safe_V_or_S55': safe&(V|S55),
                'safe_Vmild': safe&Vm,
            }
            for core_name in CORE_NAMES:
                core_m=cores[core_name].fillna(False)
                for cname,fmask in soft.items():
                    entry=core_m & fmask.reindex(df.index).fillna(False)
                    key=f'{core_name}__SOFT_{cname}__{KEEP_EXIT}'
                    bucket.setdefault(key,[]).extend(_simulate_exits(df,entry,hl=hl,temp_label=temp,sid=sid,entry_tag=key,exit_mode=KEEP_EXIT))
                    pool=cores['core_w3_or_ma60w3'].fillna(False)|cores['core_w3_start'].fillna(False)
                    if int(pool.sum())<5: pool=pd.Series(True,index=df.index)
                    rnd=_random_matched(entry, pool & fmask.reindex(df.index).fillna(False) if cname!='D0' else pool, seed=seed+len(key))
                    bucket.setdefault(f'random__{key}',[]).extend(_simulate_exits(df,rnd,hl=hl,temp_label=temp,sid=sid,entry_tag=f'rnd__{key}',exit_mode=KEEP_EXIT))
        except Exception as e:
            errors.append(f'{sid}:{type(e).__name__}:{e}')
    from scripts.decade_lab_phone_trade_confront import _agg_trades
    by={k:_agg_trades(v) for k,v in bucket.items()}; lz0=by.get('leave_zero__hi20_or_desync') or {}
    ranking=[]
    for key,st in by.items():
        if key.startswith('random__') or key.startswith('leave_zero__'): continue
        rnd=by.get(f'random__{key}') or {}
        days=int(st.get('n_unique_entry_days') or 0); ok=days>=20
        beats_r=bool(ok and np.isfinite(st.get('expectancy',np.nan)) and np.isfinite(rnd.get('expectancy',np.nan)) and float(st['expectancy'])>float(rnd['expectancy']) and float(st['win_rate'])>float(rnd['win_rate']))
        beats_lz=bool(ok and lz0 and float(st.get('expectancy',np.nan))>float(lz0.get('expectancy',np.nan)) and float(st.get('win_rate',np.nan))>=float(lz0.get('win_rate',np.nan))-0.005)
        ranking.append({'key':key,'n_trades':st.get('n_trades'),'n_unique_entry_days':days,'win_rate':st.get('win_rate'),'expectancy':st.get('expectancy'),'avg_hold':st.get('avg_hold'),'exit_reason_counts':st.get('exit_reason_counts'),'random_win_rate':rnd.get('win_rate'),'random_expectancy':rnd.get('expectancy'),'beats_random':beats_r,'beats_leave_zero':beats_lz})
    ranking.sort(key=lambda r:(int(r['beats_random']),int(r['beats_leave_zero']),float(r.get('win_rate') or -1),float(r.get('expectancy') or -9)), reverse=True)
    winners=[r for r in ranking if r['beats_random'] and r['beats_leave_zero']]
    by_win=sorted([r for r in ranking if int(r.get('n_unique_entry_days') or 0)>=20], key=lambda r:float(r.get('win_rate') or -1), reverse=True)
    gate=f"soft winners={len(winners)}/{len(ranking)}; best={by_win[0]['key'] if by_win else None} win={by_win[0].get('win_rate') if by_win else None} E={by_win[0].get('expectancy') if by_win else None}; promote_lookup=NO"
    out={'phone_sync':'blocked','not_buy_signal':True,'elapsed_s':round(time.time()-t0,1),'n_stocks':meta_n,'ranking':ranking,'by_winrate_n20':by_win[:20],'winners_beat_random_and_lz':winners,'promote_to_lookup_display':False,'gate_one_liner':gate,'leave_zero_baseline':lz0,'errors_n':len(errors),'note_zh':'SOFT：V/S55 OR 與 Vmild，試圖加厚樣本仍保高勝率'}
    text=json.dumps(out,ensure_ascii=False,indent=2,default=str)
    (ART/'phone_champion_soft_latest.json').write_text(text,encoding='utf-8')
    (DOC/'phone_champion_soft_latest.json').write_text(text,encoding='utf-8')
    print('GATE',gate,flush=True)
    print('WINNERS',json.dumps(winners[:8],ensure_ascii=False,default=str)[:2000],flush=True)
if __name__=='__main__':
    main()
