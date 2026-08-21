# -*- coding: utf-8 -*-
"""
WayneBot Phase 3: 多管道安全通訊與自動排程告警模組
檔案名稱: bot_servers.py
職責:
  1. Telegram 安全推播引擎 (自動分片、異常重試、防崩潰)
  2. LINE Webhook 伺服器與驗證 (HMAC-SHA256 簽章防偽、Flex Message 產生器)
"""

import os
import time
import json
import hmac
import hashlib
import base64
import logging
from typing import List, Dict, Any, Optional, Union
import requests

# 設定日誌模組
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WayneBot.Servers")


# ==========================================
# 1. Telegram 安全推播引擎
# ==========================================

class TelegramBotClient:
    """Telegram Bot 輕量封裝客戶端，直接使用 requests 確保相容性與重試韌性"""
    def __init__(self, token: str, timeout: int = 15):
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.timeout = timeout
        self._validate_token()

    def _validate_token(self) -> None:
        if not self.token or ":" not in self.token:
            raise ValueError("無效的 Telegram Bot Token 格式")

    def send_message(
        self,
        chat_id: Union[str, int],
        text: str,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = True
    ) -> requests.Response:
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": disable_web_page_preview
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = requests.post(url, json=payload, timeout=self.timeout)
        return response


def init_telegram_bot(token: Optional[str] = None) -> TelegramBotClient:
    """
    初始化 Telegram Bot 客戶端
    優先讀取傳入之 token，若無則讀取環境變數 TG_BOT_TOKEN
    """
    bot_token = token or os.getenv("TG_BOT_TOKEN")
    if not bot_token:
        raise ValueError("未提供 Telegram Bot Token，且未於環境變數中設定 TG_BOT_TOKEN")
    logger.info("Telegram Bot 初始化成功")
    return TelegramBotClient(token=bot_token)


def chunk_message(text: str, max_length: int = 4000) -> List[str]:
    """
    將超長文字訊息安全分割為小於等於 max_length 的多個區塊。
    
    演算法特色:
    1. 優先以換行符號 ('\\n') 作為自然斷行點，確保排版與段落完整。
    2. 若單行超長文字依然超過 max_length，則進行精準字元切片。
    3. 保證 100% 不掉字 (Reconstruction Invariant: ''.join(chunks) == text)。
    4. 嚴格限制每段長度 <= max_length (防止 Telegram 4096 限制報錯)。
    """
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    lines = text.split("\n")
    current_chunk: List[str] = []
    current_len = 0

    for idx, line in enumerate(lines):
        # 除最後一行外，還原換行符號
        line_with_nl = line if idx == len(lines) - 1 else line + "\n"
        line_len = len(line_with_nl)

        if line_len > max_length:
            # 若目前暫存區已有內容，先輸出
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0

            # 單行強制分片
            start = 0
            while start < len(line_with_nl):
                end = start + max_length
                chunks.append(line_with_nl[start:end])
                start = end
        else:
            if current_len + line_len > max_length:
                chunks.append("".join(current_chunk))
                current_chunk = [line_with_nl]
                current_len = line_len
            else:
                current_chunk.append(line_with_nl)
                current_len += line_len

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


def send_telegram_safely(
    bot: TelegramBotClient,
    chat_id: Union[str, int],
    full_text: str,
    parse_mode: Optional[str] = "HTML",
    max_retries: int = 3,
    retry_delay: float = 2.0
) -> bool:
    """
    遍歷分片並安全發送訊息，內建 429 速率限制等待與連線異常重試機制。
    """
    if not full_text:
        logger.warning("欲發送之訊息為空，略過發送")
        return False

    chunks = chunk_message(full_text, max_length=4000)
    total_chunks = len(chunks)
    logger.info("準備發送 Telegram 訊息，總計 %d 個分片", total_chunks)

    success_all = True

    for i, chunk in enumerate(chunks, start=1):
        payload_text = chunk
        if total_chunks > 1:
            header = f"<b>[訊息分片 {i}/{total_chunks}]</b>\n"
            if parse_mode == "HTML":
                payload_text = header + chunk
            else:
                payload_text = f"[{i}/{total_chunks}]\n" + chunk

        sent = False
        for attempt in range(1, max_retries + 1):
            try:
                response = bot.send_message(
                    chat_id=chat_id,
                    text=payload_text,
                    parse_mode=parse_mode
                )

                if response.status_code == 200:
                    logger.info("分片 [%d/%d] 發送成功", i, total_chunks)
                    sent = True
                    # 避免連續觸發 Telegram Rate Limit
                    time.sleep(0.35)
                    break
                elif response.status_code == 429:
                    # 遭遇 Telegram 頻率限制
                    retry_after = 5
                    try:
                        res_data = response.json()
                        retry_after = res_data.get("parameters", {}).get("retry_after", 5)
                    except Exception:
                        pass
                    logger.warning("觸發 Rate Limit (429)，等待 %s 秒後重試...", retry_after)
                    time.sleep(retry_after)
                else:
                    logger.error("發送失敗 HTTP %d: %s", response.status_code, response.text)
                    time.sleep(retry_delay * attempt)

            except requests.exceptions.RequestException as e:
                logger.error("連線發生異常 (嘗試 %d/%d): %s", attempt, max_retries, str(e))
                time.sleep(retry_delay * attempt)

        if not sent:
            logger.critical("分片 [%d/%d] 發送徹底失敗！", i, total_chunks)
            success_all = False

    return success_all


# ==========================================
# 2. LINE Webhook 伺服器與 Flex 訊息生成
# ==========================================

def verify_and_handle_line_webhook(
    request_body: str,
    signature: str,
    channel_secret: Optional[str] = None
) -> bool:
    """
    驗證 LINE Webhook 請求之 X-Line-Signature 簽章，防止偽造攻擊。
    演算法: HMAC-SHA256(channel_secret, request_body) -> Base64 比對
    """
    secret = channel_secret or os.getenv("LINE_CHANNEL_SECRET")
    if not secret:
        logger.error("缺少 LINE_CHANNEL_SECRET，無法進行簽章驗證")
        return False

    if not request_body or not signature:
        logger.warning("request_body 或 signature 為空，驗證失敗")
        return False

    try:
        hash_digest = hmac.new(
            secret.encode("utf-8"),
            request_body.encode("utf-8"),
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hash_digest).decode("utf-8")
        is_valid = hmac.compare_digest(expected_signature, signature)

        if is_valid:
            logger.info("LINE Webhook 簽章驗證通過")
        else:
            logger.warning("LINE Webhook 簽章不符，可能為偽造請求")
        return is_valid
    except Exception as e:
        logger.error("簽章驗證過程發生異常: %s", str(e))
        return False


def build_screening_flex_message(
    report_title: str,
    trade_date: str,
    stock_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    將 WayneBot 量化篩選結果轉換為符合 LINE 規格之 Flex Message 結構。
    
    stock_items 格式範例:
    [
        {
            "code": "2330",
            "name": "台積電",
            "close": 980.0,
            "foreign_buy": 12500,
            "trust_buy": 2100,
            "pattern": "頸線突破"
        },
        ...
    ]
    """
    stock_boxes = []

    for item in stock_items:
        code = str(item.get("code", "0000"))
        name = str(item.get("name", "未知"))
        close = str(item.get("close", "-"))
        foreign_buy = item.get("foreign_buy", 0)
        trust_buy = item.get("trust_buy", 0)
        pattern = str(item.get("pattern", "多頭型態"))

        stock_box = {
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "paddingAll": "sm",
            "backgroundColor": "#F8F9FA",
            "cornerRadius": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{code} {name}",
                            "weight": "bold",
                            "size": "sm",
                            "color": "#111111",
                            "flex": 4
                        },
                        {
                            "type": "text",
                            "text": f"${close}",
                            "weight": "bold",
                            "size": "sm",
                            "color": "#D32F2F",
                            "align": "end",
                            "flex": 2
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"外資:{foreign_buy:+d}張 | 投信:{trust_buy:+d}張",
                            "size": "xxs",
                            "color": "#666666",
                            "flex": 5
                        },
                        {
                            "type": "text",
                            "text": pattern,
                            "size": "xxs",
                            "color": "#1976D2",
                            "align": "end",
                            "flex": 3
                        }
                    ]
                }
            ]
        }
        stock_boxes.append(stock_box)

    if not stock_boxes:
        stock_boxes.append({
            "type": "text",
            "text": "今日無符合條件之標的",
            "size": "sm",
            "color": "#888888",
            "align": "center",
            "margin": "md"
        })

    flex_payload = {
        "type": "flex",
        "altText": f"{report_title} ({trade_date})",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1E293B",
                "paddingAll": "lg",
                "contents": [
                    {
                        "type": "text",
                        "text": "WayneBot 量化雷達",
                        "size": "xs",
                        "color": "#38BDF8",
                        "weight": "bold"
                    },
                    {
                        "type": "text",
                        "text": report_title,
                        "size": "lg",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "margin": "xs"
                    },
                    {
                        "type": "text",
                        "text": f"交易日期: {trade_date}",
                        "size": "xs",
                        "color": "#94A3B8",
                        "margin": "xs"
                    }
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": "【籌碼與型態共振篩選結果】",
                        "size": "xs",
                        "color": "#475569",
                        "weight": "bold"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "sm",
                        "contents": stock_boxes
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "※ 量化數據僅供參考，請嚴格執行停損與風控紀律",
                        "size": "xxs",
                        "color": "#999999",
                        "align": "center"
                    }
                ]
            }
        }
    }
    return flex_payload
