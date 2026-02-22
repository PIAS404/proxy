import os
import json
import sqlite3
from typing import Optional, Dict, Any, Tuple

import requests
from dotenv import load_dotenv
from cryptography.fernet import Fernet

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- ENV -----------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
FERNET_SECRET = os.getenv("FERNET_SECRET", "").strip()
DB_PATH = os.getenv("DB_PATH", "bestproxy_bot.db").strip()
API_BASE = os.getenv("BESTPROXY_API_BASE", "https://api.bestproxy.com").strip().rstrip("/")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing in .env")
if not FERNET_SECRET:
    raise SystemExit("❌ FERNET_SECRET missing in .env")

fernet = Fernet(FERNET_SECRET.encode())

# ----------------- DB -----------------
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        tg_user_id INTEGER PRIMARY KEY,
        api_key_enc TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)
    conn.commit()
    conn.close()

def db_set_key(tg_user_id: int, api_key: str):
    api_key_enc = fernet.encrypt(api_key.encode()).decode()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO users(tg_user_id, api_key_enc, updated_at)
    VALUES(?,?,datetime('now'))
    ON CONFLICT(tg_user_id) DO UPDATE SET
        api_key_enc=excluded.api_key_enc,
        updated_at=datetime('now')
    """, (tg_user_id, api_key_enc))
    conn.commit()
    conn.close()

def db_get_key(tg_user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT api_key_enc FROM users WHERE tg_user_id=?", (tg_user_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    return fernet.decrypt(row[0].encode()).decode()

def db_delete_user(tg_user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE tg_user_id=?", (tg_user_id,))
    conn.commit()
    conn.close()

# ----------------- BestProxy API Client -----------------
class BestProxyAPI:
    """
    Official base: https://api.bestproxy.com
    Auth: app_key in query (GET) OR in body (POST)
    Response: {"code":200,"msg":"...","data":...}
    """
    def __init__(self, app_key: str):
        self.app_key = app_key

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return API_BASE + path

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = dict(params or {})
        params["app_key"] = self.app_key
        r = requests.get(self._url(path), params=params, timeout=TIMEOUT)
        return self._pack(r)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = dict(body or {})
        payload["app_key"] = self.app_key
        r = requests.post(self._url(path), json=payload, timeout=TIMEOUT)
        return self._pack(r)

    def _pack(self, r: requests.Response) -> Dict[str, Any]:
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
        return {"http": r.status_code, "json": data}

def ok_api(resp: Dict[str, Any]) -> Tuple[bool, str]:
    if resp.get("http", 0) >= 400:
        return False, f"HTTP {resp.get('http')}"

    j = resp.get("json", {})
    # bestproxy format: code == 200 success
    code = j.get("code")
    msg = j.get("msg") or j.get("message") or ""
    if code == 200:
        return True, msg or "OK"
    return False, f"code={code} msg={msg}"

def pretty(obj: Any, max_len: int = 3500) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(s) > max_len:
        return s[:max_len] + "\n... (trimmed)"
    return s

# ----------------- UI / States -----------------
S_WAIT_KEY = "wait_key"
S_WAIT_ADD_ACCOUNTS = "wait_add_accounts"
S_WAIT_DEL_ACCOUNTS = "wait_del_accounts"
S_WAIT_EN_ACCOUNTS = "wait_en_accounts"
S_WAIT_DIS_ACCOUNTS = "wait_dis_accounts"
S_WAIT_CH_PASS = "wait_ch_pass"
S_WAIT_CH_REMARK = "wait_ch_remark"
S_WAIT_CH_LIMIT = "wait_ch_limit"
S_WAIT_FLOW_START = "wait_flow_start"
S_WAIT_STATIC_FILTER = "wait_static_filter"
S_WAIT_STATE_SEARCH = "wait_state_search"
S_WAIT_CITY_SEARCH = "wait_city_search"

def menu(connected: bool) -> InlineKeyboardMarkup:
    if not connected:
        kb = [
            [InlineKeyboardButton("🔗 Connect API Key", callback_data="connect")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ]
        return InlineKeyboardMarkup(kb)

    kb = [
        [InlineKeyboardButton("👥 Proxy Accounts", callback_data="acc_menu"),
         InlineKeyboardButton("📊 Traffic (Daily)", callback_data="flow_menu")],
        [InlineKeyboardButton("🌍 Locations", callback_data="loc_menu"),
         InlineKeyboardButton("🧷 Static IPs", callback_data="static_menu")],
        [InlineKeyboardButton("❌ Disconnect", callback_data="disconnect"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

def acc_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📋 List", callback_data="acc_list")],
        [InlineKeyboardButton("➕ Add (bulk)", callback_data="acc_add"),
         InlineKeyboardButton("🗑️ Delete (bulk)", callback_data="acc_del")],
        [InlineKeyboardButton("✅ Enable", callback_data="acc_en"),
         InlineKeyboardButton("🚫 Disable", callback_data="acc_dis")],
        [InlineKeyboardButton("🔑 Change Pass", callback_data="acc_pass"),
         InlineKeyboardButton("📝 Change Remark", callback_data="acc_remark")],
        [InlineKeyboardButton("📦 Change Limit(GB)", callback_data="acc_limit")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(kb)

def flow_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📅 Last 7 Days (default)", callback_data="flow_default")],
        [InlineKeyboardButton("🕒 Custom start_time", callback_data="flow_custom")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(kb)

def loc_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🏷️ States list", callback_data="states_list"),
         InlineKeyboardButton("🔎 States search", callback_data="states_search")],
        [InlineKeyboardButton("🏙️ Cities list", callback_data="cities_list"),
         InlineKeyboardButton("🔎 Cities search", callback_data="cities_search")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(kb)

def static_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🧷 Get static IPs", callback_data="static_get")],
        [InlineKeyboardButton("⚙️ Get with filters", callback_data="static_filter")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(kb)

def clear_states(context: ContextTypes.DEFAULT_TYPE):
    for k in list(context.user_data.keys()):
        if k.startswith("wait_") or k in (
            S_WAIT_KEY, S_WAIT_ADD_ACCOUNTS, S_WAIT_DEL_ACCOUNTS, S_WAIT_EN_ACCOUNTS, S_WAIT_DIS_ACCOUNTS,
            S_WAIT_CH_PASS, S_WAIT_CH_REMARK, S_WAIT_CH_LIMIT, S_WAIT_FLOW_START,
            S_WAIT_STATIC_FILTER, S_WAIT_STATE_SEARCH, S_WAIT_CITY_SEARCH
        ):
            context.user_data.pop(k, None)

def get_api(update: Update) -> Optional[BestProxyAPI]:
    tg_id = update.effective_user.id
    k = db_get_key(tg_id)
    if not k:
        return None
    return BestProxyAPI(k)

# ----------------- Commands -----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    connected = db_get_key(tg_id) is not None
    text = (
        "👋 *BestProxy Multi-User Bot*\n\n"
        "✅ Login লাগে না—শুধু `app_key` দিলেই হবে\n"
        "🔐 প্রত্যেক user তাদের নিজের key use করবে\n\n"
        "Menu 👇"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=menu(connected))

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_states(context)
    connected = db_get_key(update.effective_user.id) is not None
    await update.message.reply_text("✅ Cancelled.", reply_markup=menu(connected))

# ----------------- Buttons -----------------
async def on_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tg_id = q.from_user.id
    connected = db_get_key(tg_id) is not None

    data = q.data

    if data == "help":
        await q.edit_message_text(
            "ℹ️ *Help*\n\n"
            "1) Dashboard থেকে `App_key` copy করো\n"
            "2) Bot এ `Connect API Key` চাপো\n"
            "3) Key paste করো\n\n"
            "⚠️ Key admin-level—কাউকে দিও না।",
            parse_mode="Markdown",
            reply_markup=menu(connected),
        )
        return

    if data == "connect":
        clear_states(context)
        context.user_data[S_WAIT_KEY] = True
        await q.edit_message_text(
            "🔑 এখন তোমার *App_key* paste করো.\n\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "disconnect":
        db_delete_user(tg_id)
        clear_states(context)
        await q.edit_message_text("✅ Disconnected. Your key removed.", reply_markup=menu(False))
        return

    # need connected for below menus
    if not connected:
        await q.edit_message_text("⚠️ আগে Connect করো।", reply_markup=menu(False))
        return

    if data == "back":
        await q.edit_message_text("⬅️ Back to main menu", reply_markup=menu(True))
        return

    if data == "acc_menu":
        await q.edit_message_text("👥 *Proxy Accounts Menu*", parse_mode="Markdown", reply_markup=acc_menu())
        return

    if data == "flow_menu":
        await q.edit_message_text("📊 *Traffic / Usage Menu*", parse_mode="Markdown", reply_markup=flow_menu())
        return

    if data == "loc_menu":
        await q.edit_message_text("🌍 *Locations Menu*", parse_mode="Markdown", reply_markup=loc_menu())
        return

    if data == "static_menu":
        await q.edit_message_text("🧷 *Static IP Menu*", parse_mode="Markdown", reply_markup=static_menu())
        return

    api = get_api(update)
    if not api:
        await q.edit_message_text("⚠️ Key missing. Please /start again.", reply_markup=menu(False))
        return

    # -------- Accounts actions --------
    if data == "acc_list":
        resp = api.get("/gateway/whitelist-account/list")
        ok, msg = ok_api(resp)
        if not ok:
            await q.edit_message_text(f"❌ Failed: {msg}\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
            return
        await q.edit_message_text(f"📋 *Accounts*\n```{pretty(resp['json'])}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    if data == "acc_add":
        clear_states(context)
        context.user_data[S_WAIT_ADD_ACCOUNTS] = True
        await q.edit_message_text(
            "➕ *Add Accounts (bulk)*\n\n"
            "Format:\n"
            "`user01:pass,user02:pass`\n\n"
            "Cancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "acc_del":
        clear_states(context)
        context.user_data[S_WAIT_DEL_ACCOUNTS] = True
        await q.edit_message_text(
            "🗑️ *Delete Accounts (bulk)*\n\n"
            "Format:\n"
            "`user01,user02`\n\n"
            "Cancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "acc_en":
        clear_states(context)
        context.user_data[S_WAIT_EN_ACCOUNTS] = True
        await q.edit_message_text("✅ *Enable Accounts*\n\nSend: `user01,user02`\nCancel: `/cancel`", parse_mode="Markdown")
        return

    if data == "acc_dis":
        clear_states(context)
        context.user_data[S_WAIT_DIS_ACCOUNTS] = True
        await q.edit_message_text("🚫 *Disable Accounts*\n\nSend: `user01,user02`\nCancel: `/cancel`", parse_mode="Markdown")
        return

    if data == "acc_pass":
        clear_states(context)
        context.user_data[S_WAIT_CH_PASS] = True
        await q.edit_message_text(
            "🔑 *Change Password*\n\nFormat:\n`username newpassword`\nExample: `user01 pass123`\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "acc_remark":
        clear_states(context)
        context.user_data[S_WAIT_CH_REMARK] = True
        await q.edit_message_text(
            "📝 *Change Remark*\n\nFormat:\n`username | remark text`\nExample: `user01 | my test account`\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "acc_limit":
        clear_states(context)
        context.user_data[S_WAIT_CH_LIMIT] = True
        await q.edit_message_text(
            "📦 *Change Limit (GB)*\n\nFormat:\n`username limitGB`\nExample: `user01 50`\n0 দিলে unlimited\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    # -------- Flow actions --------
    if data == "flow_default":
        resp = api.get("/gateway/user-usage-flow/total")
        ok, msg = ok_api(resp)
        if not ok:
            await q.edit_message_text(f"❌ Failed: {msg}\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=flow_menu())
            return
        await q.edit_message_text(f"📊 *Usage Flow (Daily)*\n```{pretty(resp['json'])}```", parse_mode="Markdown", reply_markup=flow_menu())
        return

    if data == "flow_custom":
        clear_states(context)
        context.user_data[S_WAIT_FLOW_START] = True
        await q.edit_message_text(
            "🕒 *Custom start_time*\n\nSend start_time like:\n`2026-02-01 00:00:00`\n\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    # -------- Locations actions --------
    if data == "states_list":
        resp = api.get("/gateway/ip/dynamic-states")
        ok, msg = ok_api(resp)
        if not ok:
            await q.edit_message_text(f"❌ Failed: {msg}\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=loc_menu())
            return
        await q.edit_message_text(f"🏷️ *States List*\n```{pretty(resp['json'])}```", parse_mode="Markdown", reply_markup=loc_menu())
        return

    if data == "states_search":
        clear_states(context)
        context.user_data[S_WAIT_STATE_SEARCH] = True
        await q.edit_message_text(
            "🔎 *States search*\n\nSend country_code like:\n`US`\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    if data == "cities_list":
        resp = api.get("/gateway/ip/dynamic-citys")
        ok, msg = ok_api(resp)
        if not ok:
            await q.edit_message_text(f"❌ Failed: {msg}\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=loc_menu())
            return
        await q.edit_message_text(f"🏙️ *Cities List*\n```{pretty(resp['json'])}```", parse_mode="Markdown", reply_markup=loc_menu())
        return

    if data == "cities_search":
        clear_states(context)
        context.user_data[S_WAIT_CITY_SEARCH] = True
        await q.edit_message_text(
            "🔎 *Cities search*\n\nSend like:\n`country_code state`\nExample: `US CA`\nCancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    # -------- Static IP actions --------
    if data == "static_get":
        resp = api.get("/gateway/ip/get-static-ip")
        ok, msg = ok_api(resp)
        if not ok:
            await q.edit_message_text(f"❌ Failed: {msg}\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=static_menu())
            return
        await q.edit_message_text(f"🧷 *Static IPs*\n```{pretty(resp['json'])}```", parse_mode="Markdown", reply_markup=static_menu())
        return

    if data == "static_filter":
        clear_states(context)
        context.user_data[S_WAIT_STATIC_FILTER] = True
        await q.edit_message_text(
            "⚙️ *Static IP filters*\n\n"
            "Send JSON filters (any of these):\n"
            "`{\"country_code\":\"US\",\"product_type\":25,\"page\":1,\"size\":20}`\n\n"
            "product_type: 25=Static Residential, 14=Datacenter\n"
            "status: 1 valid, 2 invalid, 3 expiring, 4 maintenance\n\n"
            "Cancel: `/cancel`",
            parse_mode="Markdown",
        )
        return

    await q.edit_message_text("⚠️ Unknown action", reply_markup=menu(True))


# ----------------- Text handler (User inputs) -----------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    text = (update.message.text or "").strip()

    # save key
    if context.user_data.get(S_WAIT_KEY):
        context.user_data[S_WAIT_KEY] = False
        db_set_key(tg_id, text)
        await update.message.reply_text("✅ Connected! এখন /start দাও বা menu use করো 😄")
        return

    api = get_api(update)
    if not api:
        await update.message.reply_text("⚠️ Not connected. /start দিয়ে Connect করো।")
        return

    # Add accounts
    if context.user_data.get(S_WAIT_ADD_ACCOUNTS):
        context.user_data[S_WAIT_ADD_ACCOUNTS] = False
        resp = api.post("/gateway/whitelist-account/add", body={"accounts": text, "remark": ""})
        await update.message.reply_text(f"➕ Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Delete accounts
    if context.user_data.get(S_WAIT_DEL_ACCOUNTS):
        context.user_data[S_WAIT_DEL_ACCOUNTS] = False
        resp = api.post("/gateway/whitelist-account/delete", body={"accounts": text})
        await update.message.reply_text(f"🗑️ Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Enable / Disable
    if context.user_data.get(S_WAIT_EN_ACCOUNTS):
        context.user_data[S_WAIT_EN_ACCOUNTS] = False
        resp = api.post("/gateway/whitelist-account/enable", body={"accounts": text})
        await update.message.reply_text(f"✅ Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    if context.user_data.get(S_WAIT_DIS_ACCOUNTS):
        context.user_data[S_WAIT_DIS_ACCOUNTS] = False
        resp = api.post("/gateway/whitelist-account/disable", body={"accounts": text})
        await update.message.reply_text(f"🚫 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Change password
    if context.user_data.get(S_WAIT_CH_PASS):
        context.user_data[S_WAIT_CH_PASS] = False
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("⚠️ Format: `username newpassword`", parse_mode="Markdown")
            return
        account = parts[0].strip()
        password = parts[1].strip()
        resp = api.post("/gateway/whitelist-account/change-password", body={"account": account, "password": password})
        await update.message.reply_text(f"🔑 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Change remark
    if context.user_data.get(S_WAIT_CH_REMARK):
        context.user_data[S_WAIT_CH_REMARK] = False
        if "|" not in text:
            await update.message.reply_text("⚠️ Format: `username | remark`", parse_mode="Markdown")
            return
        left, remark = text.split("|", 1)
        account = left.strip()
        remark = remark.strip()
        resp = api.post("/gateway/whitelist-account/change-remark", body={"account": account, "remark": remark})
        await update.message.reply_text(f"📝 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Change limit
    if context.user_data.get(S_WAIT_CH_LIMIT):
        context.user_data[S_WAIT_CH_LIMIT] = False
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("⚠️ Format: `username limitGB`", parse_mode="Markdown")
            return
        account = parts[0].strip()
        try:
            limit = int(parts[1].strip())
        except ValueError:
            await update.message.reply_text("⚠️ limitGB must be number", parse_mode="Markdown")
            return
        resp = api.post("/gateway/whitelist-account/change-limit", body={"account": account, "limit": limit})
        await update.message.reply_text(f"📦 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=acc_menu())
        return

    # Custom flow start_time
    if context.user_data.get(S_WAIT_FLOW_START):
        context.user_data[S_WAIT_FLOW_START] = False
        resp = api.get("/gateway/user-usage-flow/total", params={"start_time": text})
        await update.message.reply_text(f"📊 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=flow_menu())
        return

    # states search
    if context.user_data.get(S_WAIT_STATE_SEARCH):
        context.user_data[S_WAIT_STATE_SEARCH] = False
        cc = text.strip().upper()
        resp = api.get("/gateway/ip/dynamic-states/search", params={"country_code": cc})
        await update.message.reply_text(f"🔎 States:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=loc_menu())
        return

    # cities search
    if context.user_data.get(S_WAIT_CITY_SEARCH):
        context.user_data[S_WAIT_CITY_SEARCH] = False
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("⚠️ Format: `country_code state` (example: `US CA`)", parse_mode="Markdown")
            return
        cc = parts[0].strip().upper()
        st = parts[1].strip()
        resp = api.get("/gateway/ip/dynamic-citys/search", params={"country_code": cc, "state": st})
        await update.message.reply_text(f"🔎 Cities:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=loc_menu())
        return

    # static filter
    if context.user_data.get(S_WAIT_STATIC_FILTER):
        context.user_data[S_WAIT_STATIC_FILTER] = False
        try:
            filters_json = json.loads(text)
            if not isinstance(filters_json, dict):
                raise ValueError()
        except Exception:
            await update.message.reply_text("⚠️ Please send valid JSON object.", parse_mode="Markdown")
            return
        resp = api.get("/gateway/ip/get-static-ip", params=filters_json)
        await update.message.reply_text(f"🧷 Result:\n```{pretty(resp)}```", parse_mode="Markdown", reply_markup=static_menu())
        return

    # default
    await update.message.reply_text("✅ Menu use করো: /start")

# ----------------- main -----------------
def main():
    db_init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("✅ Bot running...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
