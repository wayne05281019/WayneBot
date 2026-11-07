# -*- coding: utf-8 -*-
"""查股標記極高勝率加厚：鎖死起漲買×相對高點賣；目標 win 高且 days≥20。

phone_sync=blocked。不准改 leave_zero。
候選：W3×V、W3×S55、Vnear∨S55、再疊 barek／feat_ok／time_align 近窗軟門。
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
from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _cores, _near, _wave_hsiao_bank
from scripts.decade_lab_phone_market_wave_sync import _align_mkt, _barek_masks, _stock_wave_events, _twii_wave_pack
from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC='blocked'; ART=Path('/opt/cursor/artifacts'); DOC=Path('docs/expert_notes/飆客/decade_lab')
SELL='hi20_or_wave_top'; DAY_FLOOR=50

def _bal(w,d):
    if not np.isfinite(w) or d<=0: return float('-inf')
    return float(w)*min(1.0,d/float(DAY_FLOOR))

def run(*, n_universe: int = 100) -> Dict[str, Any]:
    t0=time.time(); ART.mkdir(parents=True,exist_ok=True); DOC.mkdir(parents=True,exist_ok=True)
    _, mkt_raw=_twii_wave_pack(entry_preset='A0_strict', score_threshold=40.0)
    uni=select_g_universe(n=n_universe, include_twse_top100=True)
    symbols=uni['stock_id'].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols: symbols.append(sid)
    bucket={}; meta_n=0; errors=[]
    for sid in symbols:
        try:
            raw=load_stock_ohlcv(sid)
            if len(raw)<150: continue
            meta_n+=1
            df=_normalize_ohlc(raw)
            feat=_align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
            wave=_align_wave(df,_wave_frame(raw)); wmasks=_wave_masks(wave)
            cores=_cores(_build_mark_masks(df), wmasks, feat)
            bank=_wave_hsiao_bank(feat,wmasks,wave)
            ev=_stock_wave_events(raw,df); mkt=_align_mkt(df,mkt_raw)
            hl,temp=_build_hl_temp(df); seed=abs(hash(sid))%(2**32)
            bk=_barek_masks(df)
            V=bank['hsiao_V'].fillna(False); Vnear=_near(V,3); S55=bank['score55'].fillna(False)
            w3=cores['core_w3_start'].fillna(False); w3u=cores['core_w3_or_ma60w3'].fillna(False)
            bal=w3u & (Vnear|S55)
            wave_top=(ev.get('LAB_W1_TOP')|ev.get('LAB_W3_TOP')|ev.get('LAB_SELL_W5_TOP')).fillna(False)
            filters={
                'F0': pd.Series(True,index=df.index),
                'F_V': V,
                'F_Vnear': Vnear,
                'F_S55': S55,
                'F_V_or_S55': Vnear|S55,
                'F_barek': bk['bk_not_avoid'].fillna(False),
                'F_barek_near': _near(bk['bk_not_avoid'].fillna(False),2),
                'F_feat_ok': mkt.get('mkt_feat_ok', pd.Series(True,index=df.index)).fillna(False),
                'F_V_barek': V & bk['bk_not_avoid'].fillna(False),
                'F_S55_barek': S55 & bk['bk_not_avoid'].fillna(False),
                'F_Vnear_feat': Vnear & mkt.get('mkt_feat_ok', pd.Series(True,index=df.index)).fillna(False),
            }
            entries={'E_w3': w3, 'E_w3u': w3u, 'E_bal': bal}
            for en,em in entries.items():
                for fn,fm in filters.items():
                    entry=em & fm & (~mkt['mkt_rel_high_risk'].fillna(False))
                    key=f'{en}__{fn}__SELL_{SELL}'
                    bucket.setdefault(key,[]).extend(_simulate_relhigh(df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=SELL))
                    pool=w3u|w3
                    if int(pool.sum())<5: pool=pd.Series(True,index=df.index)
                    rnd=_random_matched(entry, pool & fm, seed=seed+len(key))
                    bucket.setdefault(f'random__{key}',[]).extend(_simulate_relhigh(df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f'rnd__{key}', wave_top=wave_top, mode=SELL))
        except Exception as e:
            errors.append(f'{sid}:{type(e).__name__}:{e}')
    by={k:_agg_trades(v) for k,v in bucket.items()}
    ranking=[]
    for key,st in by.items():
        if key.startswith('random__'): continue
        rnd=by.get(f'random__{key}') or {}
        days=int(st.get('n_unique_entry_days') or 0); win=float(st.get('win_rate') or np.nan); exp=float(st.get('expectancy') or np.nan)
        ok=days>=20
        beats=bool(ok and np.isfinite(exp) and np.isfinite(rnd.get('expectancy',np.nan)) and exp>float(rnd['expectancy']) and win>float(rnd.get('win_rate') or -1))
        ranking.append({'key':key,'n_trades':st.get('n_trades'),'n_unique_entry_days':days,'win_rate':win,'expectancy':exp,'beats_random':beats,'balanced_score':_bal(win,days) if ok else float('-inf'),'win_ge80':bool(ok and win>=0.80),'win_ge85':bool(ok and win>=0.85)})
    # 極高勝率優先排序
    extreme=sorted([r for r in ranking if r['beats_random'] and r.get('win_ge80')], key=lambda r:(float(r['win_rate']), int(r['n_unique_entry_days'])), reverse=True)
    by_bal=sorted([r for r in ranking if r['beats_random']], key=lambda r:(float(r.get('balanced_score') or -9), float(r.get('win_rate') or -1)), reverse=True)
    gate=f"lookup_extreme winners_ge80={len(extreme)}; best_win={extreme[0]['key'] if extreme else None} win={extreme[0].get('win_rate') if extreme else None} days={extreme[0].get('n_unique_entry_days') if extreme else None}; best_bal={by_bal[0]['key'] if by_bal else None}; promote_lookup=NO"
    out={'phone_sync':PHONE_SYNC,'promote_to_lookup_display':False,'user_goal_zh':'五張圖買賣相對位置＋極高勝率','elapsed_s':round(time.time()-t0,1),'n_stocks':meta_n,'ranking':ranking,'extreme_win_ge80':extreme[:20],'by_balanced_score':by_bal[:15],'gate_one_liner':gate,'errors_n':len(errors),'errors_sample':errors[:8]}
    text=json.dumps(out,ensure_ascii=False,indent=2,default=str)
    (ART/'phone_lookup_extreme_win_latest.json').write_text(text,encoding='utf-8')
    (DOC/'phone_lookup_extreme_win_latest.json').write_text(text,encoding='utf-8')
    print('GATE',gate,flush=True)
    return out

if __name__=='__main__':
    run(n_universe=100)
