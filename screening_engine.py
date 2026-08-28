# ------------------------------------------------------------------------------
# Telegram 訊息格式化輸出模組 (供 main_runner.py 調用)
# ------------------------------------------------------------------------------
def format_telegram_report(screening_results: dict) -> str:
    """
    將選股與決策結果格式化為 Telegram 推播文字
    """
    date_str = screening_results.get("date", datetime.now().strftime("%Y-%m-%d"))
    s1_list = screening_results.get("select_01", [])
    s2_list = screening_results.get("select_02", [])
    s3_list = screening_results.get("select_03", [])
    s4_list = screening_results.get("select_04", [])
    day_trade = screening_results.get("day_trade", [])
    swing_pick = screening_results.get("swing_pick", [])

    lines = [
        f"🚀 <b>WayneBot 量化決策戰報 ({date_str})</b>",
        "═" * 28
    ]

    # 1. 強勢突破選股
    lines.append("⚡ <b>【即時強勢選股】</b>")
    if s1_list:
        lines.append("• <i>Select 01 周帶量突破:</i> " + ", ".join([f"{x['stock_id']} {x['stock_name']}" for x in s1_list[:5]]))
    if s2_list:
        lines.append("• <i>Select 02 突破Hi120:</i> " + ", ".join([f"{x['stock_id']} {x['stock_name']}" for x in s2_list[:5]]))
    if s3_list:
        lines.append("• <i>Select 03 突破Hi480:</i> " + ", ".join([f"{x['stock_id']} {x['stock_name']}" for x in s3_list[:5]]))
    if s4_list:
        lines.append("• <i>Select 04 雙綠脫離:</i> " + ", ".join([f"{x['stock_id']} {x['stock_name']}" for x in s4_list[:5]]))
    if not (s1_list or s2_list or s3_list or s4_list):
        lines.append("• 今日無符合突破標準標的")

    lines.append("")

    # 2. 當沖/隔日沖精選
    lines.append("🎯 <b>【短線動能專區】</b>")
    if day_trade:
        lines.append("• <b>當沖候選:</b>")
        for item in day_trade[:3]:
            lines.append(f"  └ <code>{item['stock_id']} {item['stock_name']}</code> 現價:{item.get('close', 0)} 目標:{item.get('target', 0)}")
    if swing_pick:
        lines.append("• <b>隔日沖候選:</b>")
        for item in swing_pick[:3]:
            lines.append(f"  └ <code>{item['stock_id']} {item['stock_name']}</code> 進場區間:{item.get('buy_range', '市價')}")

    lines.append("═" * 28)
    lines.append("<i>⚠️ 以上為量化回測與策略篩選結果，非投資建議。</i>")

    return "\n".join(lines)
