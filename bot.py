# bot.py
import os
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from db import init_db, set_user_key, get_user_key_enc, delete_user
from security import CryptoBox
from bestproxy_client import BestProxyClient

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
FERNET_SECRET = os.getenv("FERNET_SECRET", "").strip()
DB_PATH = os.getenv("DB_PATH", "bestproxy_bot.db")
BASE_URL = os.getenv("BESTPROXY_BASE_URL", "https://bestproxy.com")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing in .env")
if not FERNET_SECRET:
    raise SystemExit("❌ FERNET_SECRET missing in .env")

crypto = CryptoBox(FERNET_SECRET)

# --- simple state keys ---
WAITING_APIKEY = "waiting_apikey"
WAITING_WL_ADD = "waiting_wl_add"
WAITING_WL_REMOVE = "waiting_wl_remove"
WAITING_ROTATE = "waiting_rotate"

def main_menu(connected: bool) -> InlineKeyboardMarkup:
    btns = []
    if not connected:
        btns += [[InlineKeyboardButton("🔗 Connect API Key", callback_data="connect")]]
    else:
        btns += [
            [InlineKeyboardButton("📋 Proxy List", callback_data="proxy_list"),
             InlineKeyboardButton("🔄 Rotate", callback_data="rotate")],
            [InlineKeyboardButton("📊 Traffic", callback_data="traffic"),
             InlineKeyboardButton("✅ Whitelist", callback_data="whitelist")],
            [InlineKeyboardButton("👥 Sub-Users", callback_data="subusers")],
            [InlineKeyboardButton("❌ Disconnect", callback_data="disconnect")],
        ]
    btns += [[InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
    return InlineKeyboardMarkup(btns)

def get_client_for_user(tg_user_id: int) -> BestProxyClient | None:
    enc = get_user_key_enc(DB_PATH, tg_user_id)
    if not enc:
        return None
    api_key = crypto.dec(enc)
    return BestProxyClient(BASE_URL, api_key, timeout=TIMEOUT)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    connected = get_user_key_enc(DB_PATH, tg_id) is not None
    text = (
        "👋 *BestProxy Controller Bot*\n\n"
        "✅ Multi-user supported\n"
        "🔐 Each user uses *their own API key*\n\n"
        "Menu থেকে action নাও 👇"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu(connected))

async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    q = update.callback_query
    if q:
        await q.answer()
    text = (
        "🧠 *How to use*\n\n"
        "1) Dashboard থেকে `App_key` copy করো\n"
        "2) Bot এ *Connect API Key* চাপো\n"
        "3) Key paste করো\n\n"
        "⚠️ Key কাউকে দিও না।\n"
        "🧩 যদি কোনো button কাজ না করে, তার মানে ঐ endpoint `endpoints.py` তে সেট করা হয়নি বা ভুল।"
    )
    if q and edit:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu(True))
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tg_id = q.from_user.id
    data = q.data

    connected = get_user_key_enc(DB_PATH, tg_id) is not None

    if data == "help":
        await help_cb(update, context, edit=True)
        return

    if data == "connect":
        context.user_data[WAITING_APIKEY] = True
        await q.edit_message_text(
            "🔑 *API key paste করো*\n\n"
            "Example: `b1718085....`\n\n"
            "Cancel করতে `/cancel`",
            parse_mode="Markdown"
        )
        return

    if data == "disconnect":
        delete_user(DB_PATH, tg_id)
        await q.edit_message_text("✅ Disconnected. API key removed from bot.", reply_markup=main_menu(False))
        return

    # must be connected for below
    if not connected:
        await q.edit_message_text("⚠️ আগে Connect করো।", reply_markup=main_menu(False))
        return

    client = get_client_for_user(tg_id)
    if not client:
        await q.edit_message_text("⚠️ Key not found. আবার Connect করো।", reply_markup=main_menu(False))
        return

    if data == "traffic":
        res = client.call("traffic")
        if not res.get("ok"):
            await q.edit_message_text(f"❌ Traffic failed:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
            return
        await q.edit_message_text(f"📊 *Traffic Response*\n```{res['data']}```", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    if data == "proxy_list":
        res = client.call("proxy_list")
        if not res.get("ok"):
            await q.edit_message_text(f"❌ Proxy list failed:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
            return
        await q.edit_message_text(f"📋 *Proxy List Response*\n```{res['data']}```", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    if data == "rotate":
        # Some APIs need proxy_id/session_id. We'll ask user for input.
        context.user_data[WAITING_ROTATE] = True
        await q.edit_message_text(
            "🔄 *Rotate*\n\n"
            "এখন rotate target দাও (proxy_id / session / or leave blank)\n"
            "Example: `proxy_id=123` অথবা শুধু `123`\n\n"
            "Cancel `/cancel`",
            parse_mode="Markdown"
        )
        return

    if data == "whitelist":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 List", callback_data="wl_list"),
             InlineKeyboardButton("➕ Add IP", callback_data="wl_add")],
            [InlineKeyboardButton("➖ Remove IP", callback_data="wl_remove"),
             InlineKeyboardButton("⬅️ Back", callback_data="back")]
        ])
        await q.edit_message_text("✅ *Whitelist Menu*", parse_mode="Markdown", reply_markup=kb)
        return

    if data == "wl_list":
        res = client.call("whitelist_list")
        if not res.get("ok"):
            await q.edit_message_text(f"❌ Whitelist list failed:\n`{res}`", parse_mode="Markdown")
            return
        await q.edit_message_text(f"📄 *Whitelist*\n```{res['data']}```", parse_mode="Markdown")
        return

    if data == "wl_add":
        context.user_data[WAITING_WL_ADD] = True
        await q.edit_message_text("➕ *Whitelist Add*\n\nIP দাও (example `1.2.3.4`)\nCancel `/cancel`", parse_mode="Markdown")
        return

    if data == "wl_remove":
        context.user_data[WAITING_WL_REMOVE] = True
        await q.edit_message_text("➖ *Whitelist Remove*\n\nIP দাও (example `1.2.3.4`)\nCancel `/cancel`", parse_mode="Markdown")
        return

    if data == "subusers":
        res = client.call("subusers")
        if not res.get("ok"):
            await q.edit_message_text(f"❌ Sub-users failed:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
            return
        await q.edit_message_text(f"👥 *Sub-Users Response*\n```{res['data']}```", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    if data == "back":
        await q.edit_message_text("⬅️ Back to menu", reply_markup=main_menu(True))
        return

    await q.edit_message_text("⚠️ Unknown action", reply_markup=main_menu(True))

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if context.user_data.get(WAITING_APIKEY):
        # Save key, then verify with status endpoint
        context.user_data[WAITING_APIKEY] = False
        enc = crypto.enc(text)
        set_user_key(DB_PATH, tg_id, enc)

        client = get_client_for_user(tg_id)
        res = client.call("status")
        if not res.get("ok"):
            # keep it saved but show error; user can fix endpoints/header later
            await update.message.reply_text(
                "✅ API key saved (encrypted) ✅\n"
                "⚠️ কিন্তু `status` check failed.\n"
                "👉 `endpoints.py` / headers ঠিক করলে সব কাজ করবে।\n\n"
                f"Error:\n`{res}`",
                parse_mode="Markdown",
                reply_markup=main_menu(True),
            )
            return

        await update.message.reply_text("✅ Connected successfully!", reply_markup=main_menu(True))
        return

    client = get_client_for_user(tg_id)

    if context.user_data.get(WAITING_WL_ADD):
        context.user_data[WAITING_WL_ADD] = False
        if not client:
            await update.message.reply_text("⚠️ Not connected.")
            return
        res = client.call("whitelist_add", json={"ip": text})
        await update.message.reply_text(f"➕ Result:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    if context.user_data.get(WAITING_WL_REMOVE):
        context.user_data[WAITING_WL_REMOVE] = False
        if not client:
            await update.message.reply_text("⚠️ Not connected.")
            return
        res = client.call("whitelist_remove", json={"ip": text})
        await update.message.reply_text(f"➖ Result:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    if context.user_data.get(WAITING_ROTATE):
        context.user_data[WAITING_ROTATE] = False
        if not client:
            await update.message.reply_text("⚠️ Not connected.")
            return

        # generic rotate payload; user input can be id or key=value
        payload = {}
        if "=" in text:
            k, v = text.split("=", 1)
            payload[k.strip()] = v.strip()
        elif text:
            payload["id"] = text

        res = client.call("proxy_rotate", json=payload if payload else None)
        await update.message.reply_text(f"🔄 Rotate Result:\n`{res}`", parse_mode="Markdown", reply_markup=main_menu(True))
        return

    # default reply
    connected = get_user_key_enc(DB_PATH, tg_id) is not None
    await update.message.reply_text("Menu use করো 👇", reply_markup=main_menu(connected))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    tg_id = update.effective_user.id
    connected = get_user_key_enc(DB_PATH, tg_id) is not None
    await update.message.reply_text("✅ Cancelled.", reply_markup=main_menu(connected))

def run():
    init_db(DB_PATH)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("✅ Bot running...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    run()
