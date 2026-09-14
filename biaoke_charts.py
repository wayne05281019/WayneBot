# -*- coding: utf-8 -*-
"""1709／社團附圖索引。圖檔不進 git，只留 URL＋短註＋代號。

頭像不算圖。第 4／5 顆讀這份索引：問一檔帶公開附圖對官方日K。
社團附圖只對價，不進話筒原文、不送圖。
"""
from __future__ import annotations

import gzip
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
CHART_INDEX_GZ = os.path.join(_DIR, "chart_index.json.gz")
AVATAR_NEEDLE = "image.cmoney.tw/profile/"
_CODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEARS = {str(y) for y in range(1990, 2036)}

# 已目視過的關鍵圖。不准靠 OCR 亂猜，也不准發明建築兩檔代號。
_NOTE_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": "平台依賴度排名（當時 F10）",
    "f04ffb08-735d-42f8-a1c4-c473afa72034": "紅框：台光電量縮站上1265、金像電量縮小紅",
    "57effce7-7abf-4894-9354-e5d3812260d1": "紅框：漢唐量沒再放大",
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": "台光電 AI 高速 CCL 護城河 S+++",
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": "穎崴 2027 EPS 190～200",
    "59129621-6b40-42b2-90fa-74a1945b3b48": "金像電 CCL 漲價侵蝕毛利＝舊利空發酵",
    "9de6eef2-0bfa-4eb1-bf1f-47216dde15e0": "AI 族群重要性表：記憶體不宜當主線",
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": "勤誠破支撐就不適合操作",
    "nu9_05aT_7A": "YouTube 縮圖：PCB開始震",
    "3e7ba93c-b7d1-4ef5-bbd7-d5f39fd6783b": "智原日K：abc 修正、不確定過396",
    "41887249-c7df-4936-afae-6e89c2b69c1e": "萬海：突破頸線確認K線",
    "b330272a-5450-4d1e-aaeb-cae23a0c3aba": "新興日K：一年半底部",
    "57073c49-89a5-4b82-b978-a05e89d38ddd": "新興：一年半W底＋下飄旗",
    "b735aca2-0e7c-4c72-b59b-92be5df9beb1": "新興15分：短線破底翻",
    "e25c0db0-efb4-427f-8220-ad9978ddb1bc": "萬海15分：破底翻確認",
    "2bfc7988-2140-4df1-8bf9-de09903e774a": "新興：主力成本區／破線（文說裕民一樣）",
    "47069aed-1411-489b-be09-56331d956c35": "新興教學圖：下飄旗＋破底翻確認",
    "046492e4-cc55-460f-a081-5f1aa9a04bf7": "台指期：假突破／做頭（主文點華碩，圖不是華碩日K）",
    "73437676-c106-4922-a48e-42e91e0a48b0": "台指期：做頭，頭肩頂左肩或M頭左側",
    "01804ab6-2fdd-47b7-8390-adf0caf8f170": "廣達1/26日K：回測頸線收盤不能跌破",
    "76b9bce8-f8e9-45ea-b565-17153a894777": "廣達2/2日K：頸線越墊越高",
    "b7132fee-a48f-4a69-956b-ebedacf4f75c": "台指近月60分：上升軌道破壞（主文點台通／頎邦，圖不是個股日K）",
    "54a8021a-7174-4b99-a26f-5ed31a27ca92": "櫃買指數日K：B然後C（不是台通／頎邦日K）",
    "47b69e0f-de57-44d9-a9ec-4e809202ca13": "光聖盤中走勢：反彈至125附近（不是日K）",
    "925ae6d3-392a-4e43-8cf7-6ef7c03a7406": "頎邦盤中走勢：回測支撐確認（不是日K）",
    "9a56b8cc-9e24-4397-a5cb-68d6df19c5a5": "廣達盤中走勢：2/15-16缺口壓力（不是日K）",
    "f413de27-c9fa-4a44-8bcb-4832929d6930": "台指期近月日K：上升軌道有點跌破（庫沒柱）",
    "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82": "樺漢盤中走勢：站上頸線、回測327（主文寫鴻海機器人概念股，圖不是鴻海日K）",
    "3d8bf14c-9c2f-4feb-ac93-8c56755b79af": "樺漢盤中走勢：10:20測326-327先觀望（不是日K）",
    "d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8": "樺漢盤中走勢：12:31拉回後改口可買完（不是日K，不是1231）",
    "df0553e6-4348-4cd8-ab64-09a179b9d6e1": "樺漢盤中走勢：12:15看327有沒有守（不是日K）",
    "ead7aa97-2233-4df3-a6d2-4016a6b6fb01": "樺漢盤中走勢：09:32最後上車、比鴻海多（圖不是鴻海日K）",
    "b0b38f9c-6ac5-4260-8f9d-0206f1167367": "光聖盤中走勢：10:10多空支撐仍寫125（不是日K）",
    "a23ff8ba-c9f6-4086-89a8-b4b7e2d68168": "光聖盤中走勢：09:15看144-145反壓不是漲停（不是日K）",
    "c3095408-726b-4dde-b71f-7cebd42ae8b5": "廣達盤中走勢：10:17洗到282再連續漲（不是日K）",
    "5e0d0c26-161f-4a5b-946f-94c6ca086382": "樺漢盤中走勢：13:30必過400看明天周K（不是日K／不是周K）",
    "d9ca1bdc-42f3-444b-87fc-6852e905a126": "廣達盤中走勢：13:30不像鴻海過282一路飆（不是日K，不是鴻海日K）",
    "26d9c950-b806-47d5-959b-7cd66855e460": "廣達盤中走勢：10:30改口非常強、用282算還有20%（不是日K，不是鴻海日K）",
    "0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9": "樺漢盤中走勢：12:00早盤洗盤、長下引線紅K才噴（不是日K）",
    "90440d1d-dfb5-4562-bd28-71be2bb2607c": "樺漢盤中走勢：10:18回測365及350、認為350守得住（不是日K）",
    "821625f8-5d5f-426d-8a50-6f5c953706bc": "廣達盤中走勢：13:30下星期上半週站穩300、不要賺幾%就下車（不是日K）",
    "d6a36765-2022-4e9e-a780-29c96479a294": "光聖盤中走勢：13:30下週一攻克144-145、測前高161.5否則整理半年（不是日K）",
    "b8455d0f-0bc8-42d9-838a-7a13256a54af": "廣達盤中走勢：09:27多空分界289.5-291、收盤要站291（不是日K）",
    "195e7491-0a99-4b9d-aedd-a3815e9f84ee": "豐達科盤中走勢：09:41回測109、短線先測124（不是日K）",
    "959f8ed1-4de2-4852-8f41-986cc63ea4c4": "豐達科盤中走勢：09:51回測114-114.5去年高點壓力（不是日K）",
    "487f0e8b-4cbf-432e-a0c6-bb2d9e504eb4": "廣達盤中走勢：13:30收盤守多方最低標準282（不是日K）",
    "a2ca173c-8a8e-4bb9-81bc-7277983f9a82": "廣達盤中走勢：09:29挑戰前高298、放假前300（不是日K）",
    "9749924c-a3e0-43b8-acd0-5db50dae7fe4": "廣達回貼昨天09:27多空分界289.5-291那則（不是日K）",
    "909aaff2-51bc-4393-8a6f-ca014f7ac88f": "迎廣盤中走勢：10:43開盤盤下、等6117上車（不是日K，不是6416日K）",
    "e25bcfc1-8852-431b-b463-cf05f9577ab0": "台積電盤中走勢：10:51最小目標810今天到了（不是日K）",
    "3129a0d0-1538-4578-8064-47897b3c3025": "雷虎盤中走勢：11:09早盤低點（不是日K）",
    "7482636f-fcb7-478d-b199-84184302a5e5": "晟銘電盤中走勢：11:09急殺買（不是日K）",
    "a078f516-26c5-49f8-b7de-f7dfe14959cb": "雷科盤中走勢：10:54止漲回測先買1/2（不是日K）",
    "d1fb2f19-5bac-4d15-8d8b-5b30b9654f59": "志聖盤中走勢：10:55一二月賺錢對照（不是日K）",
    "c81d96de-10f0-4de6-b971-45ddb33d511f": "均豪盤中走勢：10:55一二月賺錢對照（不是日K）",
    "6f617165-51b9-4396-b3b4-3d436947bea7": "晟銘電盤中走勢：11:09大黑K後強勢反彈（不是日K）",
    "40be401e-c52c-4114-8a9d-605cb5b37f21": "迎廣盤中走勢：11:09昨天漲停今大跌最佳上車（不是日K）",
    "8760c259-e431-4c9a-99cc-8d1061413ad2": "晟銘電盤中走勢：11:04近2-3日似乎比較強（不是日K）",
    "3e28b3b3-ae1a-4ebc-9f27-404450609327": "迎廣盤中走勢：11:05波動更大問解惑（不是日K）",
    "237c5965-cc4c-4126-bc0f-f185c2a95603": "晟銘電盤中走勢：10:27支撐沿5日均線比較強（不是日K）",
    "886911b5-d689-4033-b8f3-a9b2d0cf0eeb": "迎廣盤中走勢：10:27跌破5日均線看10日（不是日K）",
    "56a489b6-ca84-40d8-a131-ba1e42ff9978": "佳能盤中走勢：10:41漲停38.9（不是日K）",
    "ef4a177b-7a37-4712-9c70-2d5c138f9fb0": "協易機盤中走勢：10:40漲停40.25（不是日K）",
    "5945f017-f1e1-407a-abe8-19fe2b06c6fe": "雷科盤中走勢：11:00第二階段型態目標（不是日K）",
    "ada1f9ba-cced-4a3f-8213-6a21cf775572": "廣達盤中走勢：11:21支撐273不是282（不是日K）",
    "bc7d90d8-fdd4-47d0-a861-4d091ae87b61": "雷虎盤中走勢：12:41上車最佳時機（不是日K）",
    "b297cbc0-0e9c-426b-a0d4-0031be1da493": "雷虎盤中走勢：09:32挑戰歷史高點85.2（不是日K）",
    "0b1449bb-43f1-4115-84c3-8b4b243660de": "雷科盤中走勢：09:55回測5MA支撐線（不是日K）",
    "b5a3d066-a5d9-46e6-98b0-f7783b9fec02": "佳能盤中走勢：12:05鎖股40.1（不是日K）",
    "7cbc1625-37b5-42c6-be61-0338ba837fc3": "協易機盤中走勢：12:08爆大量已賣（不是日K）",
    "a7f487e1-297e-45d5-afc2-3b91158ae8c2": "漢科盤中走勢：12:04鎖股119（不是日K）",
    "d9f126f0-5318-4e29-be3b-966a1cb1f8de": "佳能盤中走勢：10:19早盤37.4先買一半（不是日K）",
    "b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6": "漢科盤中走勢：10:25先掛117-117.5先買1/3（不是日K）",
    "6820b93c-0852-47bd-868e-9c07421125a4": "雷科盤中走勢：10:30打到頸線56.5（不是日K）",
    "7ad20984-9c2f-4119-811e-a49f4656e7c0": "主文大盤19650：這張是佳能12:07盤中，主文沒點名不對圖（不是日K）",
    "f233c076-a0d5-4be2-8cd5-f6f6946abb12": "台積電盤中走勢：12:06法說前786（不是日K、不是台指）",
    "721c2c75-3ca9-4401-879a-c84164150a11": "主文大盤19650：這張是0050盤中，主文沒點名不對圖（不是日K）",
    "8cd5d5c2-72cf-4b8f-8409-19037d427f95": "主文大盤19500~19650：這張是台積電4/16收盤，主文沒點名不對圖（不是日K）",
    "f26afa9e-f9c8-4b04-a861-065073c91b6c": "主文大盤19500~19650：這張是漢科4/16收盤，主文沒點名不對圖（不是日K）",
    "ac9395fb-1692-4640-a2ec-c81638b9cbe6": "主文大盤19500~19650：這張是佳能4/16收盤，主文沒點名不對圖（不是日K）",
    "acb86ccf-ea62-404a-9a48-c6240e370891": "弘塑盤中走勢：12:30漲停過前高1110（不是日K）",
    "7913362a-11b8-4286-beee-d3c4c593ccb4": "雷科盤中走勢：12:30也會過前高64.5（不是日K）",
    "ffa9234a-1de5-48b4-9f81-aa7ba9a60e8c": "主文台指期夜盤19650：這張是台積電4/17收盤，主文沒點名不對圖（不是日K）",
    "eadff9cf-d2dd-4e94-9ea4-7c82df1c4ccd": "主文台指期夜盤19650：這張是漢科4/17收盤，主文沒點名不對圖（不是日K）",
    "a9e194fd-ba63-432c-8366-88f688d244c5": "主文台指期夜盤19650：這張是佳能4/17收盤，主文沒點名不對圖（不是日K）",
    "120a18bc-51be-460b-9d01-9b39e46abe87": "黃培碩加權日K：3-4浪極限18752-19012（轟天雷4/19）",
    "5d2ca298-069f-44c9-adb9-c0a07bb715a2": "黃培碩加權日K：手畫1-2-3-4浪（轟天雷4/19）",
    "28244ab1-8764-4f52-8417-79798406448f": "緯創盤中走勢：13:30上周五收盤115，小時線還沒站上119（不是日K，不是廣達／金像電／台光電）",
    "848aa61c-5fb5-4719-8a62-2c4c0c61da1a": "勤誠盤中走勢：09:48約297，持續看好可跌再進（不是日K）",
    "493f2e88-231c-48b2-ab73-035291c94c8b": "廣達盤中走勢：09:47約263.5，伺服器漲勢確認（不是日K，不是智原／緯創）",
    "f46970b1-fe3b-4937-b354-95761405af6c": "緯穎盤中走勢：09:48約2380，比較看好（不是日K，不是智原／緯創）",
    "b459a4ea-2d0d-4a99-ab03-c6686c5f11a5": "勤誠盤中走勢：12:57約289.5，站上289頭肩底目標過前高323（不是日K）",
    "7700b8ea-640f-43f5-b5be-778b1c37eea8": "光環盤中走勢：13:21約50.1，行進中短線買點（不是日K）",
    "dfc3e6d9-d626-4189-b2bc-57aa6cbcee15": "光環盤中走勢：09:35約48.55，被處置往下打（不是日K）",
    "6e00e8dc-c2e8-45d7-bd9a-4af5c867236d": "光聖盤中走勢：09:37約165.5，確認不是假突破（不是日K）",
    "37db3808-6362-474f-ab88-348ce95e3cec": "廣達盤中走勢：13:30約256.5，文寫60分頭肩底／週線右肩（不是日K，不是60分／週線，不是台積電／聯發科／1459）",
    "5efc30e4-a857-49d0-a8ff-13a007847d8d": "廣達盤中走勢：09:42約272.5，型態最少滿足價區到了（不是日K，不是緯創／緯穎）",
    "2b13c5f0-d84b-4deb-ac02-c13f4893a4ff": "台光電盤中走勢：09:30約412.5，今天在做型態右肩（不是日K）",
    "171f0639-5819-4329-bbb5-96d4e7e8e3fe": "世芯-KY盤中走勢：13:30約2760，不要抄底（不是日K，不是60分，不是廣達／智原）",
    "f867e1ab-7301-4cff-9385-2430f8217ad7": "廣達盤中走勢：09:15約274.5，提早上280的跡象（不是日K，不是鼎天／廣明／緯穎／鴻海）",
    "9759bcbb-623d-4f16-bc7c-b616edebbb7b": "華碩盤中走勢：09:54約478，文寫過271（不是日K，不是廣達）",
    "f67e2dfe-1bc5-4e20-8d4f-f20f7f54f02b": "世芯-KY盤中走勢：10:22約2520，換股至華碩、滿足約2150（不是日K，不是富野）",
    "23219170-a90a-4d45-a3bc-4896dc578cef": "勤誠盤中走勢：10:41約275，被6669帶著早盤洗（不是日K，不是緯創／緯穎／廣達）",
    "5b5ed874-9577-4296-98e6-1eb759affb15": "台光電盤中走勢：10:44約417，被6669帶著早盤洗（不是日K，不是緯創／緯穎／廣達）",
    "e54e963e-5576-4058-9e80-761a7d453640": "勤誠盤中走勢：11:31約275.5，要重新站上289（不是日K）",
    "651f4c31-2e20-4429-b317-2d78e36dcbdf": "台光電盤中走勢：11:30約416.5，要站上450才會漲得快（不是日K）",
    "5e96754a-7f28-452d-b6a8-bc7f7720aad0": "華碩盤中走勢：13:05約471，主力作價頸線461-462（不是日K，不是萬海／陽明）",
    "87acb739-5f83-4c24-9641-52b150feba26": "廣達盤中走勢：13:21約274.5，關注多方格局（不是日K，不是台積電／華碩／航運／緯創）",
    "f414adc8-792d-4af0-8b51-1c31d31808cd": "緯穎盤中走勢：13:21約2405，關注多方格局（不是日K，不是台積電／華碩／航運／緯創）",
    "3c6619ac-f707-4062-b495-5282e17ccb91": "廣達盤中走勢：10:26約276，看有沒有站穩273（不是日K）",
    "d45ebe1b-59ab-48dc-b778-5b02fad3502d": "廣達盤中走勢：09:41約288，支撐282壓力290（不是日K）",
    "8089d63a-9bc7-4676-8200-f081a8ac92f2": "萬海盤中走勢：10:21約70.4，風險最高獲利也可能最高（不是日K，不是台積電）",
    "082fe1e0-9a33-4a03-a871-614e2ab2afdf": "陽明盤中走勢：10:20約71.4，賺快錢（不是日K，不是台積電）",
    "b1e9f107-4112-44b7-8073-c84ed0138a0a": "長榮盤中走勢：10:20約206.5，不如買整理完電子（不是日K，不是台積電）",
    "bf1db5dc-a2de-4b60-b121-645c32838250": "台光電盤中走勢：10:45約421，黎明前的黑暗（不是日K）",
    "109304d1-ce6c-457f-9900-3bf52e91b411": "藍天盤中走勢：11:49約58漲停橫盤，連三根漲停（不是日K，不是華碩）",
    "53d75100-477f-4dc0-bfe7-2219a1d3bc68": "華碩盤中走勢：11:50約501，假突破再給一天（不是日K，不是藍天）",
    "eada4ea7-5ce9-4dad-bde2-dd88315619eb": "廣達盤中走勢：13:30約287，主文寫EPS 3.13（不是日K，不是數字）",
    "4fd7bb2d-76a2-4b14-a675-0ac8643ff395": "華碩盤中走勢：12:18約513，離目標價還很遠（不是日K）",
    "c6dac0ec-b44c-49ae-9e5b-0fe7d8efba71": "廣達盤中走勢：09:23約286.5，主力攻擊成本3/29支撐270-273（不是日K，不是3/29日K）",
    "e5c2ddd7-9252-4296-9ddf-9d5decd178e3": "華碩盤中走勢：10:20約508，最後上車或加碼（不是日K，不是廣達）",
    "fc2da086-1a6d-4ca4-bd09-0690a67dab80": "台光電盤中走勢：11:35約447.5，紅三兵吃掉3/13大量（不是日K，不是3167）",
    "1fa3e9ae-a32c-4ccf-95cd-eff57ded0189": "主文大盤21100：這張是台積電09:59盤中約834，主文沒點名不對圖（不是日K，不是大盤）",
    "7bdf5e68-2755-4e51-bc46-db0ef8c07e29": "主文大盤下降楔形：這張是台積電10:52盤中約838，主文沒點名不對圖（不是日K，不是大盤）",
    "7176c3a5-cb62-4fb8-b2ee-d9f657c67f78": "鼎天盤中走勢：12:22約58.3，廣達集團兩檔難操作（不是日K，不是廣達）",
    "8850edce-5e37-4337-bd9b-665b194463bf": "廣達盤中走勢：12:26約282.5，廣達也不會寂寞（不是日K，不是鼎天／廣明）",
    "d19a4996-49ff-4716-94da-e2b4ffd1e319": "廣明盤中走勢：12:23約105，廣達集團兩檔難操作（不是日K，不是廣達）",
}
_TICKERS_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": [
        "2330",
        "2383",
        "2059",
        "3017",
        "2308",
        "6223",
        "6515",
        "2368",
        "8210",
        "3081",
        "2454",
        "7769",
    ],
    "f04ffb08-735d-42f8-a1c4-c473afa72034": ["2383", "2368"],
    "57effce7-7abf-4894-9354-e5d3812260d1": ["2404"],
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": ["2383"],
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": ["6515"],
    "59129621-6b40-42b2-90fa-74a1945b3b48": ["2368"],
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": ["8210"],
    "3e7ba93c-b7d1-4ef5-bbd7-d5f39fd6783b": ["3035"],
    "41887249-c7df-4936-afae-6e89c2b69c1e": ["2615"],
    "b330272a-5450-4d1e-aaeb-cae23a0c3aba": ["2605"],
    "57073c49-89a5-4b82-b978-a05e89d38ddd": ["2605"],
    "b735aca2-0e7c-4c72-b59b-92be5df9beb1": ["2605"],
    "e25c0db0-efb4-427f-8220-ad9978ddb1bc": ["2615"],
    "2bfc7988-2140-4df1-8bf9-de09903e774a": ["2605"],
    "47069aed-1411-489b-be09-56331d956c35": ["2605"],
    "046492e4-cc55-460f-a081-5f1aa9a04bf7": ["2357"],
    "01804ab6-2fdd-47b7-8390-adf0caf8f170": ["2382"],
    "76b9bce8-f8e9-45ea-b565-17153a894777": ["2382"],
    "b7132fee-a48f-4a69-956b-ebedacf4f75c": ["8011", "6147"],
    "54a8021a-7174-4b99-a26f-5ed31a27ca92": ["8011", "6147"],
    "47b69e0f-de57-44d9-a9ec-4e809202ca13": ["6442"],
    "925ae6d3-392a-4e43-8cf7-6ef7c03a7406": ["6147"],
    "9a56b8cc-9e24-4397-a5cb-68d6df19c5a5": ["2382"],
    "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82": ["6414"],
    "3d8bf14c-9c2f-4feb-ac93-8c56755b79af": ["6414"],
    "d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8": ["6414"],
    "df0553e6-4348-4cd8-ab64-09a179b9d6e1": ["6414"],
    "ead7aa97-2233-4df3-a6d2-4016a6b6fb01": ["6414"],
    "b0b38f9c-6ac5-4260-8f9d-0206f1167367": ["6442"],
    "a23ff8ba-c9f6-4086-89a8-b4b7e2d68168": ["6442"],
    "c3095408-726b-4dde-b71f-7cebd42ae8b5": ["2382"],
    "5e0d0c26-161f-4a5b-946f-94c6ca086382": ["6414"],
    "d9ca1bdc-42f3-444b-87fc-6852e905a126": ["2382"],
    "26d9c950-b806-47d5-959b-7cd66855e460": ["2382"],
    "0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9": ["6414"],
    "90440d1d-dfb5-4562-bd28-71be2bb2607c": ["6414"],
    "821625f8-5d5f-426d-8a50-6f5c953706bc": ["2382"],
    "d6a36765-2022-4e9e-a780-29c96479a294": ["6442"],
    "b8455d0f-0bc8-42d9-838a-7a13256a54af": ["2382"],
    "195e7491-0a99-4b9d-aedd-a3815e9f84ee": ["3004"],
    "959f8ed1-4de2-4852-8f41-986cc63ea4c4": ["3004"],
    "487f0e8b-4cbf-432e-a0c6-bb2d9e504eb4": ["2382"],
    "a2ca173c-8a8e-4bb9-81bc-7277983f9a82": ["2382"],
    "9749924c-a3e0-43b8-acd0-5db50dae7fe4": ["2382"],
    "909aaff2-51bc-4393-8a6f-ca014f7ac88f": ["6117"],
    "e25bcfc1-8852-431b-b463-cf05f9577ab0": ["2330"],
    "3129a0d0-1538-4578-8064-47897b3c3025": ["8033"],
    "7482636f-fcb7-478d-b199-84184302a5e5": ["3013"],
    "a078f516-26c5-49f8-b7de-f7dfe14959cb": ["6207"],
    "d1fb2f19-5bac-4d15-8d8b-5b30b9654f59": ["2467"],
    "c81d96de-10f0-4de6-b971-45ddb33d511f": ["5443"],
    "6f617165-51b9-4396-b3b4-3d436947bea7": ["3013"],
    "40be401e-c52c-4114-8a9d-605cb5b37f21": ["6117"],
    "8760c259-e431-4c9a-99cc-8d1061413ad2": ["3013"],
    "3e28b3b3-ae1a-4ebc-9f27-404450609327": ["6117"],
    "237c5965-cc4c-4126-bc0f-f185c2a95603": ["3013"],
    "886911b5-d689-4033-b8f3-a9b2d0cf0eeb": ["6117"],
    "56a489b6-ca84-40d8-a131-ba1e42ff9978": ["2374"],
    "ef4a177b-7a37-4712-9c70-2d5c138f9fb0": ["4533"],
    "5945f017-f1e1-407a-abe8-19fe2b06c6fe": ["6207"],
    "ada1f9ba-cced-4a3f-8213-6a21cf775572": ["2382"],
    "bc7d90d8-fdd4-47d0-a861-4d091ae87b61": ["8033"],
    "b297cbc0-0e9c-426b-a0d4-0031be1da493": ["8033"],
    "0b1449bb-43f1-4115-84c3-8b4b243660de": ["6207"],
    "b5a3d066-a5d9-46e6-98b0-f7783b9fec02": ["2374"],
    "7cbc1625-37b5-42c6-be61-0338ba837fc3": ["4533"],
    "a7f487e1-297e-45d5-afc2-3b91158ae8c2": ["3402"],
    "d9f126f0-5318-4e29-be3b-966a1cb1f8de": ["2374"],
    "b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6": ["3402"],
    "6820b93c-0852-47bd-868e-9c07421125a4": ["6207"],
    "7ad20984-9c2f-4119-811e-a49f4656e7c0": ["TWII"],
    "f233c076-a0d5-4be2-8cd5-f6f6946abb12": ["2330"],
    "721c2c75-3ca9-4401-879a-c84164150a11": ["TWII"],
    "8cd5d5c2-72cf-4b8f-8409-19037d427f95": ["TWII"],
    "f26afa9e-f9c8-4b04-a861-065073c91b6c": ["TWII"],
    "ac9395fb-1692-4640-a2ec-c81638b9cbe6": ["TWII"],
    "acb86ccf-ea62-404a-9a48-c6240e370891": ["3131"],
    "7913362a-11b8-4286-beee-d3c4c593ccb4": ["6207"],
    "ffa9234a-1de5-48b4-9f81-aa7ba9a60e8c": ["TX"],
    "eadff9cf-d2dd-4e94-9ea4-7c82df1c4ccd": ["TX"],
    "a9e194fd-ba63-432c-8366-88f688d244c5": ["TX"],
    "120a18bc-51be-460b-9d01-9b39e46abe87": ["TWII"],
    "5d2ca298-069f-44c9-adb9-c0a07bb715a2": ["TWII"],
    "28244ab1-8764-4f52-8417-79798406448f": ["3231"],
    "848aa61c-5fb5-4719-8a62-2c4c0c61da1a": ["8210"],
    "493f2e88-231c-48b2-ab73-035291c94c8b": ["2382"],
    "f46970b1-fe3b-4937-b354-95761405af6c": ["6669"],
    "b459a4ea-2d0d-4a99-ab03-c6686c5f11a5": ["8210"],
    "7700b8ea-640f-43f5-b5be-778b1c37eea8": ["3234"],
    "dfc3e6d9-d626-4189-b2bc-57aa6cbcee15": ["3234"],
    "6e00e8dc-c2e8-45d7-bd9a-4af5c867236d": ["6442"],
    "37db3808-6362-474f-ab88-348ce95e3cec": ["2382"],
    "5efc30e4-a857-49d0-a8ff-13a007847d8d": ["2382"],
    "2b13c5f0-d84b-4deb-ac02-c13f4893a4ff": ["2383"],
    "171f0639-5819-4329-bbb5-96d4e7e8e3fe": ["3661"],
    "f867e1ab-7301-4cff-9385-2430f8217ad7": ["2382"],
    "9759bcbb-623d-4f16-bc7c-b616edebbb7b": ["2357"],
    "f67e2dfe-1bc5-4e20-8d4f-f20f7f54f02b": ["3661"],
    "23219170-a90a-4d45-a3bc-4896dc578cef": ["8210"],
    "5b5ed874-9577-4296-98e6-1eb759affb15": ["2383"],
    "e54e963e-5576-4058-9e80-761a7d453640": ["8210"],
    "651f4c31-2e20-4429-b317-2d78e36dcbdf": ["2383"],
    "5e96754a-7f28-452d-b6a8-bc7f7720aad0": ["2357"],
    "87acb739-5f83-4c24-9641-52b150feba26": ["2382"],
    "f414adc8-792d-4af0-8b51-1c31d31808cd": ["6669"],
    "3c6619ac-f707-4062-b495-5282e17ccb91": ["2382"],
    "d45ebe1b-59ab-48dc-b778-5b02fad3502d": ["2382"],
    "8089d63a-9bc7-4676-8200-f081a8ac92f2": ["2615"],
    "082fe1e0-9a33-4a03-a871-614e2ab2afdf": ["2609"],
    "b1e9f107-4112-44b7-8073-c84ed0138a0a": ["2603"],
    "bf1db5dc-a2de-4b60-b121-645c32838250": ["2383"],
    "109304d1-ce6c-457f-9900-3bf52e91b411": ["2362"],
    "53d75100-477f-4dc0-bfe7-2219a1d3bc68": ["2357"],
    "eada4ea7-5ce9-4dad-bde2-dd88315619eb": ["2382"],
    "4fd7bb2d-76a2-4b14-a675-0ac8643ff395": ["2357"],
    "c6dac0ec-b44c-49ae-9e5b-0fe7d8efba71": ["2382"],
    "e5c2ddd7-9252-4296-9ddf-9d5decd178e3": ["2357"],
    "fc2da086-1a6d-4ca4-bd09-0690a67dab80": ["2383"],
    "1fa3e9ae-a32c-4ccf-95cd-eff57ded0189": ["TWII"],
    "7bdf5e68-2755-4e51-bc46-db0ef8c07e29": ["TWII"],
    "7176c3a5-cb62-4fb8-b2ee-d9f657c67f78": ["3306"],
    "8850edce-5e37-4337-bd9b-665b194463bf": ["2382"],
    "d19a4996-49ff-4716-94da-e2b4ffd1e319": ["6188"],
}
_ALIAS = {
    "穎葳": "6515",
    "川湖": "2059",
    "聖暉": "5536",
    "旺矽": "6223",
    "鴻勁": "7769",
    "志聖": "2467",
    "漢唐": "2404",
    "樺漢": "6414",
    "豐達科": "3004",
    "迎廣": "6117",
    "雷虎": "8033",
    "晟銘電": "3013",
    "雷科": "6207",
    "弘塑": "3131",
    "均豪": "5443",
    "佳能": "2374",
    "協易機": "4533",
    "漢科": "3402",
    "加權": "TWII",
    "加權指數": "TWII",
    "台指期": "TX",
    "緯創": "3231",
    "緯穎": "6669",
    "光環": "3234",
    "世芯": "3661",
    "世芯-KY": "3661",
    "鼎天": "3306",
    "廣明": "6188",
    "華碩": "2357",
    "萬海": "2615",
    "陽明": "2609",
    "長榮": "2603",
    "藍天": "2362",
}


@lru_cache(maxsize=1)
def _event_snip_maps() -> tuple:
    """76 段起歸屬從 ledger 長出來，不必再抄 _TICKERS_BY_SNIP／_NOTE_BY_SNIP。"""
    try:
        from biaoke_chrono import event_snip_maps

        return event_snip_maps()
    except Exception:
        return {}, {}


@lru_cache(maxsize=1)
def _event_alias_and_own() -> tuple:
    """新股名從 ledger 長出別名與盤中走勢歸屬。"""
    alias: Dict[str, str] = {}
    own: List[tuple] = []
    try:
        from biaoke_chrono import auto_slice_events

        for e in auto_slice_events():
            name = str(e.get("name") or "").strip()
            sid = str(e.get("sid") or "").strip()
            if not name or not sid:
                continue
            alias[name] = sid
            own.append((f"{name}盤中走勢", sid))
    except Exception:
        pass
    return alias, tuple(own)


def _snip_note(url: str) -> str:
    u = url or ""
    notes, _ticks = _event_snip_maps()
    for snip, note in notes.items():
        if snip in u:
            return note
    for snip, note in _NOTE_BY_SNIP.items():
        if snip in u:
            return note
    return ""


def _snip_tickers(url: str) -> List[str]:
    u = url or ""
    _notes, ticks = _event_snip_maps()
    for snip, ids in ticks.items():
        if snip in u:
            return list(ids)
    for snip, ids in _TICKERS_BY_SNIP.items():
        if snip in u:
            return list(ids)
    return []


def _add_sid(found: List[str], sid: str, valid: Optional[set]) -> None:
    sid = str(sid or "").strip()
    if not sid or sid in found:
        return
    if valid is not None and sid not in valid:
        return
    found.append(sid)


def extract_tickers(
    ocr: str = "",
    blob: str = "",
    *,
    url: str = "",
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
    limit: int = 12,
) -> List[str]:
    found: List[str] = []
    valid = set(valid_ids) if valid_ids is not None else None
    for sid in _snip_tickers(url):
        _add_sid(found, sid, valid)
    names = dict(_ALIAS)
    names.update(_event_alias_and_own()[0])
    if name_to_sid:
        names.update(name_to_sid)
    text = (ocr or "") + "\n" + (blob or "")
    for name in sorted(names, key=len, reverse=True):
        if name and name in text:
            _add_sid(found, names[name], valid)
        if len(found) >= limit:
            return found[:limit]
    for code in _CODE.findall(ocr or ""):
        if code in _YEARS:
            continue
        _add_sid(found, code, valid)
        if len(found) >= limit:
            break
    return found[:limit]


def _short_note(kind: str, tickers: Sequence[str], url: str) -> str:
    known = _snip_note(url)
    if known:
        return known[:80]
    ids = ",".join(list(tickers)[:4])
    if kind == "kline":
        return ("日K截圖 " + ids).strip()[:80]
    if kind == "screenshot":
        return ("討論截圖 " + ids).strip()[:80]
    return ("其他附圖 " + ids).strip()[:80]


def _texts_for_aid(posts: Sequence[Dict[str, Any]], aid: str) -> str:
    aid = str(aid or "")
    if not aid:
        return ""
    chunks: List[str] = []
    for row in posts or []:
        pid = str(row.get("id") or "")
        parent = str(row.get("parent") or "")
        if pid == aid or parent == aid or pid.startswith(aid + ":"):
            tags = " ".join(str(t) for t in (row.get("tags") or []) if t)
            chunks.append(tags)
            chunks.append(str(row.get("text") or ""))
    return "\n".join(chunks)


def build_chart_index(
    catalog: Sequence[Dict[str, Any]],
    *,
    posts: Optional[Sequence[Dict[str, Any]]] = None,
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """用已下載分類結果建精簡索引。不准塞整段 OCR，不准把頭像算進去。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    src_count: Dict[str, int] = {}
    post_rows = list(posts or [])
    valid = list(valid_ids) if valid_ids is not None else None
    for raw in catalog or []:
        url = str(raw.get("url") or "").strip()
        if not url or AVATAR_NEEDLE in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        src = str(raw.get("src") or "")
        aid = str(raw.get("aid") or "")
        kind = str(raw.get("kind") or "other")
        blob = _texts_for_aid(post_rows, aid)
        tickers = extract_tickers(
            str(raw.get("ocr") or ""),
            blob,
            url=url,
            name_to_sid=name_to_sid,
            valid_ids=valid,
        )
        rows.append(
            {
                "src": src,
                "date": str(raw.get("date") or ""),
                "aid": aid,
                "url": url,
                "kind": kind,
                "tickers": tickers,
                "note": _short_note(kind, tickers, url),
            }
        )
        src_count[src] = src_count.get(src, 0) + 1
    return {
        "n": len(rows),
        "sources": src_count,
        "note": "圖檔不進 git；頭像已剔除。神經元下一件才讀圖。",
        "charts": rows,
    }


def write_chart_index(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or CHART_INDEX_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    return dest


@lru_cache(maxsize=1)
def load_chart_index() -> Dict[str, Any]:
    if not os.path.isfile(CHART_INDEX_GZ):
        return {}
    with gzip.open(CHART_INDEX_GZ, "rt", encoding="utf-8") as fh:
        blob = json.load(fh) or {}
    if not isinstance(blob, dict):
        return {}
    return blob


def charts_for(sid: str) -> List[Dict[str, Any]]:
    """這檔出現在附圖索引裡的列。沒有就空。已目視短註蓋過索引裡的「日K截圖」。"""
    want = str(sid or "").strip()
    if not want:
        return []
    out: List[Dict[str, Any]] = []
    for row in load_chart_index().get("charts") or []:
        url = str(row.get("url") or "")
        ticks = [str(t) for t in (row.get("tickers") or [])]
        extra = _snip_tickers(url)
        if extra:
            ticks = list(extra)
        if want not in ticks:
            continue
        item = dict(row)
        item["tickers"] = ticks
        known = _snip_note(url)
        if known:
            item["note"] = known
        out.append(item)
    return out


def load_name_map(db_path: str = "") -> Dict[str, str]:
    """官方股名→代號。前華科對不到就不編。"""
    out = dict(_ALIAS)
    out.update(_event_alias_and_own()[0])
    path = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "wayne_market.db"
    )
    if not path or not os.path.isfile(path):
        return out
    try:
        import sqlite3

        conn = sqlite3.connect(path, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT stock_id, stock_name FROM stock_universe"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return out
    for sid, name in rows:
        sid_s = str(sid or "").strip()
        name_s = str(name or "").replace("*", "").strip()
        if sid_s and name_s and name_s not in out:
            out[name_s] = sid_s
    return out


def valid_stock_ids(db_path: str = "") -> List[str]:
    names = load_name_map(db_path)
    return sorted(set(names.values()))


_PUBLIC_SRC = "public1709"
_NOTE_WEIGHT = {
    "平台依賴": 200,
    "F10": 180,
    "紅框": 170,
    "護城河": 160,
    "舊利空": 90,
    "破支撐": 90,
    "不宜當主線": 80,
    "長抱": 80,
    "EPS": 60,
}
_HOLD_NOTE = ("平台依賴", "護城河", "F10", "長抱", "紅框")
# 註記已經寫死是哪一檔的，別檔問句不要搶第一。
_NOTE_OWN = (
    ("漢唐量沒再放大", "2404"),
    ("台光電量縮站上1265", "2383"),
    ("台光電 AI 高速 CCL", "2383"),
    ("穎崴 2027", "6515"),
    ("金像電 CCL", "2368"),
    ("勤誠破支撐", "8210"),
    ("智原日K", "3035"),
    ("萬海：突破頸線", "2615"),
    ("萬海15分", "2615"),
    ("新興日K", "2605"),
    ("新興：一年半W底", "2605"),
    ("新興15分", "2605"),
    ("新興：主力成本區", "2605"),
    ("新興教學圖", "2605"),
    ("台指期：假突破", "2357"),
    ("台指期：做頭", "2357"),
    ("廣達1/26日K", "2382"),
    ("廣達2/2日K", "2382"),
    ("台指近月60分", "8011"),
    ("櫃買指數日K", "6147"),
    ("光聖盤中走勢", "6442"),
    ("頎邦盤中走勢", "6147"),
    ("廣達盤中走勢", "2382"),
    ("樺漢盤中走勢", "6414"),
    ("豐達科盤中走勢", "3004"),
    ("迎廣盤中走勢", "6117"),
    ("台積電盤中走勢", "2330"),
    ("雷虎盤中走勢", "8033"),
    ("晟銘電盤中走勢", "3013"),
    ("雷科盤中走勢", "6207"),
    ("志聖盤中走勢", "2467"),
    ("均豪盤中走勢", "5443"),
    ("佳能盤中走勢", "2374"),
    ("協易機盤中走勢", "4533"),
    ("漢科盤中走勢", "3402"),
    ("弘塑盤中走勢", "3131"),
    ("緯創盤中走勢", "3231"),
    ("勤誠盤中走勢", "8210"),
    ("緯穎盤中走勢", "6669"),
    ("光環盤中走勢", "3234"),
    ("台光電盤中走勢", "2383"),
    ("世芯-KY盤中走勢", "3661"),
    ("華碩盤中走勢", "2357"),
    ("萬海盤中走勢", "2615"),
    ("陽明盤中走勢", "2609"),
    ("長榮盤中走勢", "2603"),
    ("藍天盤中走勢", "2362"),
    ("鼎天盤中走勢", "3306"),
    ("廣明盤中走勢", "6188"),
)


def _px_short(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def official_on(db_path: str, sid: str, date: str) -> Dict[str, Any]:
    """這檔這天的官方日K。沒這列就空，不准編。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return {}
    ymd = str(date or "").replace("-", "")[:8]
    if len(ymd) != 8 or not ymd.isdigit():
        return {}
    try:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, open, high, low, close, volume FROM daily_quotes "
                "WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=? LIMIT 1",
                (str(sid), ymd),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {
        "date": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": row[5],
    }


_STAMP_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?"
)


def parse_chart_stamp(raw: str) -> tuple[str, str]:
    """圖上 2024/04/16 10:25 → (2024-04-16, 10:25)。沒戳就空。不准 OCR。"""
    m = _STAMP_RE.search(raw or "")
    if not m:
        return "", ""
    y, mo, d, hh, mm = m.groups()
    date_s = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    if hh is None:
        return date_s, ""
    return date_s, f"{int(hh):02d}:{mm}"


def text_tickers(
    blob: str, *, name_to_sid: Optional[Dict[str, str]] = None
) -> List[str]:
    """主文點名的股票。不看附圖。"""
    found = extract_tickers("", blob, url="", name_to_sid=name_to_sid)
    try:
        from biaoke_facts import names_in_ask

        for sid, _name in names_in_ask(blob):
            _add_sid(found, sid, None)
    except Exception:
        pass
    return found


def chart_matches_text(blob: str, url: str) -> bool:
    """主文點名的股票與附圖對得上才用這張圖分析這則。

    沒對上就略過該圖。圖上時間戳另用來鎖定主文那檔的當下量價。
    附圖還沒目視對代號、或主文沒點名股票，先留著。
    """
    chart_sids = _snip_tickers(url)
    if not chart_sids:
        return True
    named = text_tickers(blob)
    if not named:
        return True
    return any(sid in named for sid in chart_sids)


def keep_charts_for_text(blob: str, urls: Sequence[str]) -> List[str]:
    """文不對題的附圖不進這則。"""
    out: List[str] = []
    seen = set()
    for url in urls or []:
        u = str(url or "").strip()
        if not u or u in seen:
            continue
        if not chart_matches_text(blob, u):
            continue
        seen.add(u)
        out.append(u)
    return out


def official_for_text_at_stamp(
    db_path: str,
    text_sid: str,
    stamp: str,
    *,
    chart_sids: Sequence[str] = (),
) -> Dict[str, Any]:
    """附圖股票對不上主文：不用這張圖分析該則。

    圖上時間戳鎖定主文那檔／那件事的當下，再對官方量價。
    截圖價不准寫成官方柱。庫沒這列就空。
    """
    date_s, time_s = parse_chart_stamp(stamp)
    named = str(text_sid or "").strip()
    chart = [str(s).strip() for s in chart_sids if str(s).strip()]
    mismatch = bool(named and chart and named not in chart)
    bar = official_on(db_path, named, date_s) if named and date_s else {}
    return {
        "use_chart": not mismatch,
        "mismatch": mismatch,
        "stamp_date": date_s,
        "stamp_time": time_s,
        "sid": named,
        "official": bar,
    }


def _names_for_sid(sid: str) -> List[str]:
    want = str(sid or "").strip()
    if not want:
        return []
    names: List[str] = []
    for name, code in _ALIAS.items():
        if code == want and name not in names:
            names.append(name)
    for name, code in _event_alias_and_own()[0].items():
        if code == want and name not in names:
            names.append(name)
    return names


def _note_not_this_stock(note: str, sid: str) -> bool:
    """目視已寫「圖不是這檔／不是個股日K」就不要當這檔預測圖送。"""
    blob = str(note or "")
    mark = blob.find("圖不是")
    if mark < 0:
        return False
    tail = blob[mark:]
    if "個股" in tail:
        return True
    want = str(sid or "").strip()
    if want and want in tail:
        return True
    return any(name and name in tail for name in _names_for_sid(want))


def pick_charts(
    sid: str,
    *,
    limit: int = 3,
    public_only: bool = True,
    hold: bool = False,
) -> List[Dict[str, Any]]:
    """問一檔只帶最有用的幾張。公開文才進話筒；社團不送。圖不是這檔的不送。"""
    rows = charts_for(sid)
    if public_only:
        rows = [r for r in rows if str(r.get("src") or "") == _PUBLIC_SRC]
    if hold:
        rows = [
            r
            for r in rows
            if any(k in str(r.get("note") or "") for k in _HOLD_NOTE)
        ]
    rows = [r for r in rows if not _note_not_this_stock(str(r.get("note") or ""), sid)]

    def score(row: Dict[str, Any]) -> tuple:
        note = str(row.get("note") or "")
        n = 0
        for key, weight in _NOTE_WEIGHT.items():
            if key in note:
                n = max(n, weight)
        if _snip_note(str(row.get("url") or "")):
            n = max(n, 95)
        if str(row.get("kind") or "") == "screenshot":
            n += 10
        for hint, own in list(_NOTE_OWN) + list(_event_alias_and_own()[1]):
            if hint in note and own and own != str(sid):
                n -= 120
                break
        return (n, str(row.get("date") or ""))

    rows = sorted(rows, key=score, reverse=True)
    return rows[: max(0, int(limit))]


def format_charts_vs_official(
    sid: str,
    db_path: str = "",
    *,
    hold: bool = False,
    limit: int = 3,
) -> str:
    """第 4 顆眼睛：他的公開附圖對這檔官方日K。沒日K就標缺。"""
    rows = pick_charts(sid, limit=limit, public_only=True, hold=hold)
    if not rows:
        return ""
    parts: List[str] = []
    saw_bar = False
    missing = False
    for row in rows:
        note = str(row.get("note") or "附圖").strip()
        day = str(row.get("date") or "")
        bar = official_on(db_path, sid, day)
        if bar:
            saw_bar = True
            close = _px_short(bar.get("close"))
            hi = _px_short(bar.get("high"))
            lo = _px_short(bar.get("low"))
            op = _px_short(bar.get("open"))
            extra = f"官方收{close or '—'} 開{op or '—'} 高{hi or '—'} 低{lo or '—'}"
            parts.append(f"{day} {note}（{extra}）")
        else:
            missing = True
            parts.append(f"{day} {note}".strip())
    head = "他的附圖（長抱／F10）：" if hold else "他的附圖對官方日K："
    text = head + "；".join(parts)
    if missing and not saw_bar:
        text += "。官方這顆庫當日沒這列，不准編"
    elif missing:
        text += "。缺日K的不准編"
    text += "。截圖是他當下讀數，會改口。不是買訊"
    return text[:420]
