# 查股五張圖標記候選（仍 blocked）

- gate: `lookup-mark candidate: buy=core_w3_or_ma60w3__BAL_Vnear2_or_S55__hi20_or_desync win=0.76 days=50; sell=relhigh sealed; earliness best_bal=core_w3_start; phone_sync=blocked; promote=NO`
- phone_sync: blocked；promote_to_lookup_display: false
- 買標候選：均衡核 win=0.76／日50；提早量另見 mark_earliness
- 賣標候選：relhigh 已封（hi20_or_desync／hi20_or_wave_top）
- 五張 hook：已掛 stub（phone_lookup_mark_hook_map.md）
- 下一步：等 champion_v3 封口；未過閘繼續加因子，不准改 leave_zero
