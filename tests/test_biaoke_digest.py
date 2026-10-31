# -*- coding: utf-8 -*-
"""飆大未讀匣：重疊更新只留最新，按進去看一口重點。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_digest import (
    biaoke_button_label,
    format_focus_oral,
    format_latest_focus,
    format_unread_digest,
    mark_biaoke_read,
    normalize_biaoke_button,
    record_ingest_events,
    take_unread_digest,
    unread_count,
)
from biaoke_ingest import AFTER_EVERY_SEC, poll_wait_seconds
from bot_servers import MENU_BTN_BIAOKE, WayneTelegramBot, _normalize_menu_text


def test_poll_wait_until_three():
    tz = ZoneInfo("Asia/Taipei")
    still = datetime(2026, 9, 10, 2, 50, tzinfo=tz)
    assert poll_wait_seconds(still) == AFTER_EVERY_SEC
    stop = datetime(2026, 9, 10, 3, 0, tzinfo=tz)
    assert poll_wait_seconds(stop) == AFTER_EVERY_SEC


def test_unread_dedupes_same_post_and_splits_users(tmp_path):
    db = str(tmp_path / "w.db")
    wayne, bro = "9001", "9002"
    record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"}],
        now=datetime(2026, 9, 11, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "10:20", "text": "散熱還在、記憶體先看量"}],
        now=datetime(2026, 9, 11, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    record_ingest_events(
        db,
        [{"post_id": "1:r1", "kind": "reply", "time": "10:24", "text": "但絕對不是南亞科"}],
        now=datetime(2026, 9, 11, 11, 5, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert unread_count(wayne, db) == 2
    assert unread_count(bro, db) == 2
    html = take_unread_digest(wayne, db, now=datetime(2026, 9, 11, 11, 43, tzinfo=ZoneInfo("Asia/Taipei")))
    assert "飆大現在在講" in html
    assert "散熱還在" in html
    assert "散熱最強" not in html
    assert "不是南亞科" in html
    assert "11:43" in html
    assert "不是買訊" not in html
    assert "今天飆大重點就是" not in html
    assert "官方加權盤中現價" not in html
    assert "程式標籤" not in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
    mark_biaoke_read(wayne, db, now=datetime(2026, 9, 11, 11, 44, tzinfo=ZoneInfo("Asia/Taipei")))
    assert unread_count(wayne, db) == 0
    assert unread_count(bro, db) == 2
    assert biaoke_button_label(wayne, db) == "飆大"
    assert biaoke_button_label(bro, db) == "飆大 2"


def test_button_face_and_normalize():
    assert normalize_biaoke_button("飆大") == "飆大"
    assert normalize_biaoke_button("飆大 3") == "飆大"
    assert normalize_biaoke_button("飆大 12") == "飆大"
    assert _normalize_menu_text("飆大 3") == "飆大"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert [b.text for b in kb.keyboard[0]][-3] == MENU_BTN_BIAOKE
    assert [b.text for b in kb.keyboard[0]][-2] == "台股大盤"
    assert [b.text for b in kb.keyboard[0]][-1] == "資金輪動"


def test_format_digest_empty():
    assert format_unread_digest([]) == ""


def test_unchanged_repost_does_not_revive_unread(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    tz = ZoneInfo("Asia/Taipei")
    row = {"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"}
    record_ingest_events(db, [row], now=datetime(2026, 9, 11, 10, 0, tzinfo=tz))
    mark_biaoke_read(uid, db, now=datetime(2026, 9, 11, 10, 5, tzinfo=tz))
    assert unread_count(uid, db) == 0
    n = record_ingest_events(db, [row], now=datetime(2026, 9, 11, 13, 0, tzinfo=tz))
    assert n == 0
    assert unread_count(uid, db) == 0
    n = record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "13:10", "text": "散熱還在、記憶體先看量"}],
        now=datetime(2026, 9, 11, 13, 10, tzinfo=tz),
    )
    assert n == 1
    assert unread_count(uid, db) == 1


def test_reply_menu_badge_uses_unread_count(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    record_ingest_events(
        db,
        [
            {"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"},
            {"post_id": "2", "kind": "post", "time": "10:01", "text": "記憶體看量"},
        ],
        now=datetime(2026, 9, 11, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._reply_menu(uid)
    assert [b.text for b in kb.keyboard[0]][-3] == "飆大 2"
    assert [b.text for b in kb.keyboard[0]][-2] == "台股大盤"
    assert [b.text for b in kb.keyboard[0]][-1] == "資金輪動"


def test_focus_oral_sep18_not_timestamp_wall():
    mains = [
        {
            "id": "m918",
            "date": "2026-09-18",
            "time": "08:58",
            "text": (
                "1. 從夜盤反彈到47205，這次C波下殺已經沒了。不過這次大盤要漲到目標點位"
                "一定要過前波高點47578，否則大盤頭部型態已經初步出現，未來不是再一次"
                "出現這一次大修正，或者走2024/10~2025/02 做一個大的頭部型態出來。"
                " 2. 目前唯一在多頭格局的族群就是ASIC，再來是散熱，再次之就是光通訊、記憶體，依照強弱排序。"
                " 3. 有一個新族群目前在底部蠢蠢欲動，因為現在追蹤我的人數過多，我已經無法像以前那樣公開點名。"
            ),
        },
        {
            "id": "m917",
            "date": "2026-09-17",
            "time": "10:42",
            "text": "1. 台光電至少要整理三個月 ，和 ABF一樣 。 2. PCB全面走弱 ，建議全面減碼。",
        },
    ]
    replies = [
        {
            "id": "r1",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "22:44",
            "text": "PCB整理時間會比ABF短很多，昨天錯殺成分居多，應該是下波會漲主流族群",
        },
        {
            "id": "r2",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "22:40",
            "text": "我這周末比較忙，星期日晚上我發一篇對台光電、金像電、台燿、富喬、金居 的技術分析看法。",
        },
        {
            "id": "r3",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "19:26",
            "text": "很有心 我很多都是看盤當下寫的，我自己都沒有備份，而且說實話，就算出書 也不可能寫這麼細。",
        },
        {
            "id": "r4",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "16:20",
            "text": "全新 打錯",
        },
        {
            "id": "r5",
            "kind": "reply",
            "date": "2026-09-16",
            "time": "09:21",
            "text": "大盤今天觀察只要收盤不破3日低點45398代表C-5低點確認",
        },
    ]
    html = format_focus_oral(
        mains,
        replies,
        now=datetime(2026, 9, 20, 11, 35, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert html.startswith("<b>飆大現在在講</b>")
    assert "9/18 晚上 22:44" in html
    assert "47578" in html
    assert "如果句" in html
    assert "ASIC" in html
    assert "比 ABF 短" in html or "比ABF短" in html
    assert "整理三個月" in html
    assert "星期日晚上" in html or "星期天晚上" in html
    assert "11:35" in html
    assert "不是買訊" not in html
    assert "還能問" in html
    assert "47578過了沒" in html
    board_html = html.split("<b>族群</b>")[0] if "<b>族群</b>" in html else html
    assert "47205" in board_html
    assert "47578" in board_html
    assert "頭部型態" in board_html
    assert "如果句" in board_html
    assert "一定要過" in board_html
    assert "2024年10月" in board_html or "2024/10" in board_html
    assert "樓下 2026-09-18" not in html
    assert "2026-09-17" not in html
    assert "2026-09-16" not in html
    assert "C-5低點確認" not in html
    assert "出書" not in html
    assert "打錯" not in html
    assert "你可能會問" not in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
    assert "庫 " not in html
    assert html.count("9/17") == 0
    assert html.count("9/16") == 0
    assert len(html) < 1800


def test_latest_focus_is_oral_not_july_bwave():
    html = format_latest_focus("")
    assert "飆大現在在講" in html
    assert "不是買訊" not in html
    assert "直接打字或語音" in html
    assert "不掛可點清單" in html
    assert "還能問" not in html
    assert "quote/" not in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
    assert "位階不講死" not in html
    assert "庫 " not in html
    assert "你可能會問" not in html
    assert "今天飆大重點就是" not in html
    assert "樓下 2026-" not in html
    assert "模糊的精確" not in html
    assert "安全邊際" not in html
    assert "和碩" not in html
    assert "仁寶" not in html
    assert "新發：" not in html
    assert "45000" not in html
    assert "46000" not in html
    assert "語料" not in html
    assert "量先價行" not in html
    assert len(html) < 2200


def test_focus_oral_strips_cmoney_google_chrome():
    """話筒摘要不准出現 CMoney「要加入 google 偏好」宣傳。"""
    mains = [
        {
            "id": "185883781",
            "kind": "post",
            "date": "2026-10-15",
            "time": "16:45",
            "text": (
                "大盤波浪位階為A波拆解3-3主跌段下殺運行中\n"
                "將網站加入你的 google 偏好搜尋來源，更容易搜尋到喜愛的內容\n"
                "昨天夜盤及今日日盤波浪位階已經訂好了，目前為A-3-3運行中已經到修正末端。"
            ),
        }
    ]
    html = format_focus_oral(
        mains,
        [],
        now=datetime(2026, 10, 15, 17, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert "A-3-3" in html
    assert "偏好" not in html
    assert "google" not in html.lower()
    assert "喜愛的內容" not in html


def test_format_latest_focus_scopes_replies_to_latest_two_threads(tmp_path):
    """按飆大只組最新兩則主文＋這兩串自回；別串舊回不准混進。"""
    from biaoke_desk import upsert_biaoke_posts
    from biaoke_digest import format_latest_focus

    db = str(tmp_path / "w.db")
    upsert_biaoke_posts(
        db,
        [
            {
                "id": "200000002",
                "date": "2026-10-15",
                "time": "16:45",
                "kind": "post",
                "tags": [],
                "text": "1.大盤目前為A-3-3主跌運行中，明天會有A-3-4反彈逃命。",
            },
            {
                "id": "200000001",
                "date": "2026-10-15",
                "time": "08:52",
                "kind": "post",
                "tags": [],
                "text": "1.夜盤最差修正ABC-X-ABC，多空分界約47500，抄底看47300到47500。",
            },
            {
                "id": "200000002:r1",
                "parent": "200000002",
                "date": "2026-10-15",
                "time": "17:00",
                "kind": "reply",
                "layer": 1,
                "tags": [],
                "text": "他自己也會明天或下周一反彈全部出清股票。",
            },
            {
                "id": "200000001:r1",
                "parent": "200000001",
                "date": "2026-10-15",
                "time": "10:24",
                "kind": "reply",
                "layer": 1,
                "tags": [],
                "text": "黃框還有一段B波假突破，橘框是B波反彈不過前高後大跌。",
            },
            {
                "id": "199000000:r9",
                "parent": "199000000",
                "date": "2026-10-14",
                "time": "18:00",
                "kind": "reply",
                "layer": 1,
                "tags": [],
                "text": "這是更早一串的自回，不該進最新兩則摘要。",
            },
            {
                "id": "199000000",
                "date": "2026-10-14",
                "time": "09:00",
                "kind": "post",
                "tags": [],
                "text": "1.大盤昨天舊文不該當現在在講。",
            },
        ],
    )
    html = format_latest_focus(db)
    assert "A-3-3" in html
    # 兩則主文都要對齊：最新大盤欄＋前一則進他還說
    assert "47500" in html or "47300" in html
    assert "出清" in html
    assert "黃框" in html or "橘框" in html
    assert "更早一串" not in html
    assert "昨天舊文" not in html


def test_focus_oral_board_prefers_latest_main_not_older():
    """最新主文有大盤句時，不准被更早主文的「緩步上攻」蓋掉。"""
    mains = [
        {
            "id": "185192837",
            "kind": "post",
            "date": "2026-10-07",
            "time": "10:22",
            "text": (
                "1.\t大盤因為是中繼站頭肩底型態可以用等幅測距漲到56000左右(保守估計)，"
                "因此只要沒有接近56000，都是做多安全環境。\n"
                "2.\t今天光通訊較低位階股票紛紛大漲，最具代表性就是InP聯亞漲停。"
            ),
        },
        {
            "id": "184931175",
            "kind": "post",
            "date": "2026-09-24",
            "time": "08:57",
            "text": (
                "目前大盤看起來是走緩步上攻可能性比較大，但要看整理時間及拉回幅度，"
                "有沒有破壞長線有可能產生九組推升脈動的波型才能判斷，目前證據不夠。"
            ),
        },
    ]
    html = format_focus_oral(
        mains,
        [],
        now=datetime(2026, 10, 8, 22, 14, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    board_html = html.split("<b>族群</b>")[0] if "<b>族群</b>" in html else html
    assert "56000" in board_html
    assert "頭肩底" in board_html or "中繼站" in board_html
    assert "緩步上攻" not in board_html
    assert "10/7" in html or "10/8" in html
    if "<b>族群</b>" in html:
        field_html = html.split("<b>族群</b>", 1)[1]
        field_html = field_html.split("<b>", 1)[0]
        assert "56000" not in field_html
        assert "光通訊" in field_html or "聯亞" in field_html


def test_focus_oral_does_not_repeat_board_in_said():
    """大盤欄講過的，他還說不准再貼同一段（話筒不重複）。"""
    board = (
        "目前大盤看起來是走緩步上攻可能性比較大，但要看整理時間及拉回幅度，"
        "有沒有破壞長線有可能產生九組推升脈動的波型才能判斷，目前證據不夠。"
        "今天早盤要買股票，先不動作，尾盤再考慮介入。"
    )
    field = (
        "目前台股最強主流是ASIC，創意、聯發科都是有效突破歷史高點，"
        "我的判斷方式，這兩檔股票5月見高點之後竟然能整理4個月就能有效突破歷史高點。"
    )
    pcb = "台光電 非常適合左側交易 和 台積電一樣， 這次消息利空大跌 再一次驗證。"
    extra = (
        "因為南亞科其實已經漲非常多 我認為記憶體要再漲一倍 微乎其微 "
        "反而光通訊 幾乎比較大。光通訊 我估計第一檔發動攻擊 就是 全新、大立光、聯亞這三檔。"
    )
    mains = [
        {
            "id": "m1",
            "kind": "post",
            "date": "2026-09-26",
            "time": "11:50",
            "text": f"1. {board}\n2. {field}\n3. {pcb}",
        }
    ]
    replies = [
        {
            "id": "r1",
            "kind": "reply",
            "date": "2026-09-26",
            "time": "12:10",
            "text": board + " " + extra,
        }
    ]
    html = format_focus_oral(
        mains,
        replies,
        now=datetime(2026, 9, 26, 13, 12, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert "<b>大盤</b>" in html
    assert "緩步上攻" in html
    assert "<b>族群</b>" in html
    assert "ASIC" in html
    assert "<b>PCB</b>" in html or "台光電" in html
    # 他還說若有，不准整段再貼大盤。自回裡多出來的南亞科進黃金脈絡。
    if "<b>他還說</b>" in html:
        said = html.split("<b>他還說</b>", 1)[1]
        said = said.split("<b>", 1)[0]
        assert said.count("緩步上攻") == 0
    assert "南亞科" in html or "光通訊" in html or "全新" in html
    assert html.count("緩步上攻") == 1
    assert "13:12" in html


def test_old_inbox_not_counted_as_unread(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    tz = ZoneInfo("Asia/Taipei")
    # 14 日窗必須吃注入的 now，不准靠真實牆鐘（CI 過台北午夜會把固定日踢掉）
    clock = datetime(2026, 9, 11, 22, 3, tzinfo=tz)
    record_ingest_events(
        db,
        [
            {
                "post_id": "181149602",
                "kind": "post",
                "date": "2026-07-30",
                "time": "09:55",
                "text": "就算大盤今天開始正式開始走大B波反彈，反彈目標45000~46000",
            }
        ],
        now=datetime(2026, 9, 11, 22, 0, tzinfo=tz),
    )
    assert unread_count(uid, db, now=clock) == 0
    record_ingest_events(
        db,
        [
            {
                "post_id": "184545002",
                "kind": "post",
                "date": "2026-09-11",
                "time": "17:49",
                "text": "今晚夜盤至少要穿越46506",
            }
        ],
        now=datetime(2026, 9, 11, 22, 1, tzinfo=tz),
    )
    html = take_unread_digest(uid, db, now=clock)
    assert "46506" in html
    assert "45000" not in html
    assert "17:49" in html
    assert "樓下 2026-09-11" not in html
    assert "飆大現在在講" in html


def test_gold_tail_follows_latest_voice_not_old_script(tmp_path):
    """黃金脈絡到結尾跟最新主文＋自回，對已收官方柱。舊雙箭頭稿不准再印。"""
    import sqlite3

    from biaoke_reweave import reweave_gold

    db = str(tmp_path / "w.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE biaoke_posts(
            id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, parent TEXT,
            layer INTEGER, kind TEXT, tags TEXT, text TEXT, updated_at TEXT
        );
        CREATE TABLE futures_daily(
            date TEXT, symbol TEXT, session TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE index_daily(
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL
        );
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO futures_daily VALUES('20261015','TX','regular',47716,47720,46883,46979,84911)"
    )
    conn.execute(
        "INSERT INTO index_daily VALUES('20261015','TWII',48382.75,48382.75,46795.38,46969.87,18709109)"
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES('20261015','2330',2420,2450,2420,2440,58486)"
    )
    conn.commit()
    conn.close()
    old_arrow = {
        "id": "old-arrow",
        "kind": "post",
        "date": "2026-09-20",
        "time": "10:00",
        "text": "光通訊 InP 先釘主流後，創意創高把 ASIC 拉成並列，到過年前雙箭頭。",
    }
    mains = [
        {
            "id": "185962404",
            "kind": "post",
            "date": "2026-10-16",
            "time": "10:27",
            "text": (
                "用台指期來分析大盤多空轉折，台指期現在必須反彈至少48240之上，"
                "才能化解第三波往下擴延。否則目前還是空方主場，需先降低持股，"
                "至少保持現金5成以上(最好是七成)。"
                "關鍵數字：台指期多空關鍵點位48240。除非能穿刺48240目前都是以空方誘多視之。"
            ),
        },
    ]
    replies = [
        {
            "id": "r-bystander",
            "kind": "bystander",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "16:00",
            "text": "我覺得會噴到88888，快買。",
        },
        {
            "id": "r-corr",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "16:15",
            "text": (
                "今天波浪大師分析大盤從費半去分析。"
                "原來訂此次為A波修正，改為C波修正，不見得會破7月底A波低點39000左右。"
            ),
        },
        {
            "id": "r-lya-am",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "10:37",
            "layer": 2,
            "reply_to_text": "目前只留一張聯亞讓他飄",
            "text": "我也只剩下聯亞零股觀察單，因為這檔股票只要一旦發動都是用跳空方式不讓散戶上車",
        },
        {
            "id": "r-lrg",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "10:59",
            "layer": 2,
            "reply_to_text": "想請問大立光跌破大量的低點，會不會假跌破",
            "text": "會回到5700或之下",
        },
        {
            "id": "r-pos",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "17:22",
            "text": "我後來看創意破線，我最後連聯亞觀察單都出清，我現在是空手，包含台積電都沒有了。",
        },
        {
            "id": "r-clear",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "21:38",
            "text": "我也決定全部清光持股 包含台積電(2200)",
        },
        {
            "id": "r-snark",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "22:14",
            "text": "\"也包含聯亞嗎\" 也決定全部清光持股 包含台積電(2200) 是不是有閱讀障礙",
        },
        {
            "id": "r-99",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "16:34",
            "text": "99%撐不住，多空關鍵點位其實我和波浪大師說的點位完全一致，只是他用大盤，我用台指期。",
        },
        {
            "id": "r-charity",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "22:03",
            "text": "等這波修正完成，抄底賺大錢，不要忘記社會有很多需要幫助的人，能夠行有餘力盡量多做一些慈善",
        },
        {
            "id": "r-8",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "23:27",
            "text": (
                "\"違反人性的當下確實會很掙扎 事後回頭看不見得不好\" "
                "確實 對超過8成沒進行台指期多空雙向交易的投資人會很掙扎"
            ),
        },
        {
            "id": "r-yes",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "11:04",
            "text": "Yes厲害 看樣子命中機率高 高手",
        },
        {
            "id": "r-short",
            "kind": "reply",
            "parent": "185962404",
            "date": "2026-10-16",
            "time": "12:52",
            "text": "其實空股票幾乎和隔日沖差不多，非常難操作。開課的人裡蕭明道會要求學生把賺的錢捐出來。",
        },
    ]
    html = format_focus_oral(
        mains,
        replies,
        now=datetime(2026, 10, 16, 22, 20, tzinfo=ZoneInfo("Asia/Taipei")),
        db_path=db,
    )
    tail = html.split("<b>脈絡黃金</b>", 1)[-1]
    assert "<b>脈絡黃金</b>" in html
    assert "黃金脈絡：" in tail
    assert "改為C波" in html or "C波修正" in html
    assert "39000" in tail
    assert "48240" in tail
    assert "清光" in html or "空手" in html
    assert "2200" in tail
    assert "官方柱" in tail
    assert "殺兩週左右" in tail
    assert "C-3-4" in tail
    assert "超過九成" in tail
    assert "聯亞</a>已賣出" in tail or "聯亞已賣出" in tail
    assert "加權2026-10-16缺完整官方開高低收" in tail
    assert "46979" not in tail
    assert "2440" not in tail
    assert "創高把" not in html
    assert "過年前雙箭頭" not in html
    assert "該怎麼做" not in html
    assert "可接" not in html
    assert "88888" not in html
    assert "99999" not in html
    assert "閱讀障礙" not in tail
    assert "不在清光那句裡" not in tail
    assert "聯亞還在" not in tail
    assert "不是聯亞" not in tail
    assert "都賣光了" in tail
    assert "聯亞" in tail
    assert "零股" in tail
    assert "5700" in tail
    assert "大立光" in tail
    assert "99%" in tail
    assert "台指期" in tail
    # 主文後含「抄底」的自回會併進大盤口語（2026-10-24）
    assert "行有餘力" in html
    assert "8成" in tail
    assert "違反人性" not in tail
    assert "命中機率高" in tail
    assert "空股票" in tail
    assert "蕭明道" in tail
    assert "不是買訊" not in html
    from biaoke_desk import upsert_biaoke_posts

    upsert_biaoke_posts(
        db,
        [old_arrow] + mains + [r for r in replies if r["kind"] != "bystander"],
    )
    pack = reweave_gold(db, force=True)
    blob = "\n".join(pack.get("gold") or [])
    assert "改為C波" in blob or "C波修正" in blob
    assert "創高把" not in blob
    assert "48240" in blob
    from biaoke_reweave import voice_gold_lines

    glued = "\n".join(
        voice_gold_lines(
            [
                {
                    "id": "m",
                    "kind": "post",
                    "date": "2026-10-16",
                    "time": "10:27",
                    "text": "台指期必須反彈至少48240之上。",
                },
                {
                    "id": "r0050",
                    "kind": "reply",
                    "date": "2026-10-16",
                    "time": "12:47",
                    "text": "那就定期定額0050",
                    "reply_to_text": "聯亞比較可惜，今天高點直接出清。",
                },
            ],
            "",
        )
    )
    assert "0050" in glued
    assert "聯亞，那就" not in glued


def test_blank_focus_no_stock_blue_links_and_has_gates(tmp_path):
    """空白鍵：無奇摩藍字／還能問股名；主文後自回進大盤；附關卡×已收。"""
    import sqlite3

    from biaoke_digest import format_focus_oral, format_index_gates_confront_html

    db = str(tmp_path / "gates.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE index_daily (
            symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
            pct_change REAL, PRIMARY KEY(symbol, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE futures_daily (
            symbol TEXT, date TEXT, session TEXT,
            open REAL, high REAL, low REAL, close REAL, pct_change REAL,
            PRIMARY KEY(symbol, date, session)
        )
        """
    )
    conn.execute(
        "INSERT INTO index_daily VALUES ('TWII','20261022',46942.75,47332.18,46041.43,46041.43,-1.8)"
    )
    conn.execute(
        "INSERT INTO futures_daily VALUES ('TX','20261022','regular',47164,47337,46217,46272,0)"
    )
    conn.execute(
        "INSERT INTO futures_daily VALUES ('TX','20261022','night',46991,47555,46983,47482,0)"
    )
    conn.commit()
    conn.close()

    mains = [
        {
            "id": "186534405",
            "kind": "post",
            "date": "2026-10-22",
            "time": "13:21",
            "text": (
                "大盤已經破前低，但是看預估量還是沒放量出來，也就是沒有進行大量籌碼交換，"
                "從量價結構來看完全沒出現止跌訊號。"
            ),
        }
    ]
    replies = [
        {
            "id": "186534405:c-272",
            "kind": "reply",
            "parent": "186534405",
            "date": "2026-10-23",
            "time": "10:38",
            "text": "記住 下星期二絕對不能抄底 風險太高",
        },
        {
            "id": "186534405:c-256-3",
            "kind": "reply",
            "parent": "186534405",
            "date": "2026-10-23",
            "time": "10:36",
            "text": "應該會直接殺破 45000",
        },
        {
            "id": "186346610",
            "kind": "post",
            "date": "2026-10-21",
            "time": "08:50",
            "text": "大盤反彈不過壓48066主跌段會啟動。已經空手者不要再介入買進。",
        },
    ]
    # 空白鍵路徑旗標
    html = format_focus_oral(
        mains,
        replies,
        now=datetime(2026, 10, 24, 15, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        db_path=db,
        stock_links=False,
        include_gates=True,
    )
    assert "飆大現在在講" in html
    assert "止跌" in html or "破前低" in html
    assert "星期二" in html and "抄底" in html
    assert "45000" in html
    assert "quote/" not in html
    assert "tw.stock.yahoo.com" not in html
    assert "還能問" not in html
    assert "不掛可點清單" in html
    assert "關卡 × 官方已收" in html
    assert "48066" in html or "45000" in html
    assert "高未到" in html or "區間碰到" in html or "低已破" in html

    gates = format_index_gates_confront_html(
        db,
        posts=mains
        + replies
        + [
            {
                "id": "186423955:c-124",
                "kind": "reply",
                "date": "2026-10-21",
                "time": "19:29",
                "text": "補充弱勢反彈不過 47729，雖然過下降軌道，但還是很快會下去。如果反彈點位(0.618)48697，會拖比較久才會開啟主跌段。",
            }
        ],
        now=datetime(2026, 10, 24, 15, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert "47729" in gates
    assert "48697" in gates
    assert "他說：" in gates
    assert "官方：" in gates
    assert "加權" in gates or "台指" in gates


def test_blank_send_biaoke_page_skips_advice_charts():
    """按飆大空白：不准再送結構圖按檔名單；改送教具圖。"""
    import asyncio
    import inspect
    from unittest.mock import AsyncMock, MagicMock, patch

    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "教具" in src or "_send_biaoke_teach_charts" in src
    assert "if not q" in src

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    bot._pending = {}
    bot._biaoke_hist = {}
    bot._enter_biaoke_chat = MagicMock()
    bot._mark_menu_layout_ok = MagicMock()
    bot._uid_from_message = MagicMock(return_value="11")
    bot._actor_key = MagicMock(return_value="11:11")
    bot._begin_actor_op = AsyncMock(return_value=1)
    bot._actor_op_alive = MagicMock(return_value=True)
    bot._start_plain_wait = AsyncMock(return_value=(None, None, None))
    bot._stop_plain_wait = AsyncMock()
    bot._show_biaoke_leave_key = AsyncMock()
    bot._biaoke_hub_markup = MagicMock(return_value=None)
    bot._biaoke_reply_menu = MagicMock(return_value=None)
    bot._send_biaoke_advice_charts = AsyncMock()
    bot._send_biaoke_structure_chart = AsyncMock()
    bot._send_biaoke_teach_charts = AsyncMock()
    msg = MagicMock()
    msg.reply_html = AsyncMock()
    msg.reply_text = AsyncMock()
    html = "<b>飆大現在在講</b>\n大盤口語\n<b>關卡 × 官方已收</b>\n45000"
    with patch("biaoke_digest.take_unread_digest", return_value=""), patch(
        "biaoke_digest.format_latest_focus", return_value=html
    ), patch("biaoke_digest.mark_biaoke_read"):
        asyncio.run(bot._send_biaoke_page(msg, ask="", uid="11"))
    bot._send_biaoke_advice_charts.assert_not_awaited()
    bot._send_biaoke_structure_chart.assert_not_awaited()
    bot._send_biaoke_teach_charts.assert_awaited()
    assert msg.reply_html.await_count >= 1
    sent = msg.reply_html.await_args.args[0]
    assert "關卡 × 官方已收" in sent or "飆大現在在講" in sent


def test_strip_classmate_echo_keeps_his_judgment():
    from biaoke_digest import _scrub_post_text, _speak

    raw = (
        '「請問老師台光電還能抱嗎？」Yes，目前我認為整理時間會比 ABF 短很多，'
        "昨天錯殺居多。"
    )
    scrubbed = _scrub_post_text(raw)
    assert "請問老師" not in scrubbed
    spoken = _speak(raw, 200)
    assert "請問" not in spoken
    assert "錯殺" in spoken or "整理" in spoken


def test_format_teach_brief_empty_db_ok(tmp_path):
    from biaoke_digest import format_teach_brief

    assert format_teach_brief("") == ""
    db = str(tmp_path / "empty.db")
    # 無活畫 pack 也要空字串，不准拋
    out = format_teach_brief(db)
    assert out == "" or "白話結論" in out
