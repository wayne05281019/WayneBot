# 黃二月大回測核對表（指向總彙整）

**單一真相源：** `huang_master_consolidate.md`（不准讀完再說少東少西／忘記測）。  
細節契約：`huang_feb_backtest_ops_spec.md`／`.json`；每日欄位模板：`huang_days/_TEMPLATE.json`。

## 已鎖規則

見總彙整 A–E（主軸、每日必填、巢狀、同步／族群、結案閘）。全部已鎖。

## 執行狀態

### 已有骨架／短窗

- [x] index／scoreboard／sample_register／days 模板／蓋牌卡  
- [x] 短窗 1110–1127 對質（holdout 基線）  
- [x] 總彙整 `huang_master_consolidate.md`  

### 開跑前未勾（必須勾完才准自稱讀完）

- [ ] 1127 live 對質  
- [ ] 交易曆 2026-02→今  
- [ ] TWII OHLC＋日量  
- [ ] SOX／ADR／點名美股＋台指期日／夜 資料源  
- [ ] 60 分 K 路徑  
- [ ] Drive 二月起片＋掃檔  

### 開跑中每日本檢

- [ ] `_TEMPLATE`／總彙整 B 表全欄 + `no_forget_audit` 全 true 才 complete  

### DONE

- [ ] 反隨便結案閘全過（總彙整 E）＝才准說會判／變準  

## 刻意不做

買訊／海選／leave_zero；蓋牌推播；發明族群籃。
