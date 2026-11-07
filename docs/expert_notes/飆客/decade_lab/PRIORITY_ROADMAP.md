# 20y 回測優先序（一次一件｜已吸收 Mine）

對齊 `USER_ASKS_MINE.md`／`LONGITUDINAL_EVAL.md`／`CONTINUOUS_REDO_PLAN.md`。  
硬規則：**禁止再報方向 100% 當成果**（稀釋／soft_range 踢難案）。不是買訊。不上話筒。

---

## 步驟（3～5；一次一件）

### 1｜測法：OOS 封印加厚（本 PR 立刻可跑）
- **對 B：** 跑中「找不出脈絡＝規則錯？」；收尾「怎樣再提高勝率？」  
- **對 C：** OOS；as-of 防前瞻（承接 #800）  
- **做什麼：** `_oos_seal_gate`／`scripts/decade_lab_path_oos_seal.py`；holdout≥20 計分日或末 20%（取較大且 ≤n//2）；未達標＝`seal_ok=false`，不准把薄窗 `ok` 當真 holdout  
- **過閘：** `seal_ok` 且 holdout_n≥20；規則指紋封印後 holdout 只驗不調；**不得**用 dir hit_rate=1.0 宣稱過關  
- **§13 下一鍵：** `path_oos_seal_vnext`（本 PR 落檔；未贏不准換現況編碼）

### 2｜測法收尾／厚庫重跑（接 #800）
- **對 B：** 因素不足；兩套差異  
- **對 C：** as-of；分軌  
- **做什麼：** 合進 #800 前瞻修後，用厚庫重跑 `decade_lab_path_forecast.py`；摘要必帶 `sample_audit`；call_rate／integrity  
- **過閘：** `integrity_ok` 中除 `WAVE_NEURONS_MATCH_false` 外 blockers 清空；仍不上話筒

### 3｜幅度 small 專殺（接 #798 B）
- **對 B：** 勝率是否只到漲跌／點位；怎樣再提高  
- **對 C：** crash-bounce＋幅度帶（small）  
- **做什麼：** 只動 `path_amp_small_vnext` 槓桿；不改 bias／買訊  
- **過閘：** small 子集獨立交易日 n≥20 且 hit 贏現況≈0.40；不傷 mid／large；OOS 封印後只驗

### 4｜波浪位階對質（接 #798 C／#799）
- **對 B：** 訓練完能否像飆大；符合波浪還缺什麼  
- **對 C：** 八循環／細微波／五件  
- **做什麼：** 續 `level_bar_vnext_explicit_hybrid` 收集；他點過→官方柱  
- **過閘：** n≥20 且贏現況 `level_bar_fwd5_role_infer`；`WAVE_NEURONS_MATCH` 才談下一步話筒——**本步過閘仍≠上話筒自動開**

### 5｜缺欄補齊（不准腦補）— 僅在 1–4 不堵時
- **對 B：** 因素不足還加什麼；Michael 擴大  
- **對 C：** 1.3 兆／融資長史／OTC／主動 ETF  
- **做什麼：** factor_gap 長史補官方；缺則標缺  
- **過閘：** 有官方序列才進計分；補欄勝率分軌不准混 path

---

## 當下唯一進行中

**步驟 1→2（測法閘＋厚庫誠實全窗；見 `SMART_PHONE_SCHEDULE.md` A→B）。**  
OOS 封印形式已有；本輪修 soft_range 灌水指紋／attempted call_rate 後重跑全窗。步驟 3–5 記再走，不准同時進化兩條產品功能。
