# 查股五張圖目標（使用者鎖死方向）

使用者買的是**個股**。最終要對他有幫助的是查股五張圖：

1. 高低溫度卡  
2. 介紹圖  
3. 結構圖  
4. 大量撐壓圖  
5. 當天走勢  

## 要加強什麼
- **買進標記**：波浪各波段起漲（主 W3／均衡核）；愈早、愈準愈好  
- **賣出標記**：相對高點（首碰 20 高／浪頂；使用者：相對高點就賣）  
- **資訊**：蕭量價、裸K建設／挡、大盤特徵位階（輔助，不是取代高低卡）  
- **準度**：過閘（n≥20、贏隨機＋leave_zero／現況）才准改話筒顯示  

## 現況標記（先保留）
- 買：leave_zero 藍▲；已確認 ma60 紅箭  
- 賣：如何賣／20 高（介紹圖／高低卡）  

## 實驗室 → 話筒掛鉤（未過閘不准合）
| 候選記號 | 來源軌 | 狀態 |
| --- | --- | --- |
| W3 起漲買點 | wave／balanced／champion | 實驗室；厚樣本均衡約 76%@50 日 |
| 近窗量∨S55 濾後買 | balanced | 實驗室均衡冠軍 |
| 相對高點賣（hi20∨浪頂） | relhigh_sell | 對質中 |
| 裸K 非避開 | market_sync | 實驗室抬勝率輔助 |
| 大盤 feat 閘 | TWII 特徵位階 | 輔助同步 |

`phone_sync=blocked` 直到單項過閘；過閘後才改 `wayne_navigator`／`vol_zone_chart`／介紹圖畫記，不准改 leave_zero 公式本身。
EOF
cp /workspace/docs/expert_notes/飆客/decade_lab/phone_lookup_five_chart_target.md /opt/cursor/artifacts/
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/opt/cursor/artifacts/phone_autonomous_loop_state.json')
d=json.loads(p.read_text()) if p.exists() else {}
d['user_deliverable_zh']='查股五張圖：更準／更早的買進與相對高點賣出標記'
d['goal_zh']='起漲買＋相對高點賣 → 過閘後畫上查股五張圖；厚樣本高勝率'
d['rule_zh']='不准輕易說沒辦法；每輪檢討加因子再測；目標對準查股標記準度'
p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
print('updated')
PY
cd /workspace && git add docs/expert_notes/飆客/decade_lab/phone_lookup_five_chart_target.md
git commit -m "$(cat <<'EOF'
lab: lock deliverable = lookup five-chart buy/sell marks

User buys stocks; optimize for earlier/more accurate wave-start buy
and relative-high sell glyphs on the five lookup charts after gate.
EOF
)"
git push -u origin cursor/hsiao-wave-lab-d6f7
git status -sb
# peek PR body head - don't overwrite human edits heavily; timer will update later
gh pr view 837 --json title --jq .title