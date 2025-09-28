import os
import json
import requests
from datetime import datetime, timedelta, date
from telegram import Update
from telegram.ext import ContextTypes
from gspread import WorksheetNotFound
import gspread

# Google Sheets connect
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
WAIFU_SHEET_URL = os.getenv("WAIFU_SHEET_URL")

if not GOOGLE_SHEETS_CREDENTIALS or not WAIFU_SHEET_URL:
    raise Exception("⚠️ Add GOOGLE_SHEETS_CREDENTIALS and WAIFU_SHEET_URL in .env")

creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
gc = gspread.service_account_from_dict(creds_dict)
sh = gc.open_by_url(WAIFU_SHEET_URL)

# ---------- Helpers ----------
def get_waifu_sheet():
    try:
        return sh.worksheet("waifu_data")
    except WorksheetNotFound:
        ws = sh.add_worksheet("waifu_data", rows="1000", cols="8")
        ws.append_row([
            "user_id", "username", "collection", "last_claim",
            "last_daily", "married_id", "group_id", "last_drop"
        ])
        return ws

def get_or_create_user_row(ws, user_id: int, username: str):
    col1 = ws.col_values(1)
    if str(user_id) in col1:
        row = col1.index(str(user_id)) + 1
        return row, ws.row_values(row)
    else:
        ws.append_row([str(user_id), username, "[]", "", "", "", "", ""])
        col1 = ws.col_values(1)
        row = col1.index(str(user_id)) + 1
        return row, ws.row_values(row)

def fetch_random_character():
    try:
        r = requests.get("https://api.jikan.moe/v4/random/characters", timeout=10)
        r.raise_for_status()
        data = r.json().get("data", {})
        return {
            "id": data.get("mal_id"),
            "name": data.get("name"),
            "image_url": data.get("images", {}).get("jpg", {}).get("image_url")
        }
    except Exception:
        return None

# ---------- Commands ----------
async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    ws = get_waifu_sheet()
    row, values = get_or_create_user_row(ws, user_id, username)

    last_claim = None
    if len(values) > 3 and values[3]:
        last_claim = datetime.fromisoformat(values[3])
    if last_claim and (datetime.utcnow() - last_claim) < timedelta(minutes=30):
        await update.message.reply_text("🕒 Wait 30 minutes before next claim!")
        return

    char = fetch_random_character()
    if not char:
        await update.message.reply_text("🚫 Failed to fetch character.")
        return

    coll = []
    if len(values) > 2 and values[2]:
        try:
            coll = json.loads(values[2])
        except:
            coll = []
    coll.append(char)
    ws.update_cell(row, 3, json.dumps(coll))
    ws.update_cell(row, 4, datetime.utcnow().isoformat())

    caption = f"🎉 You claimed **{char['name']}**!"
    if char.get("image_url"):
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id,
                                         photo=char["image_url"],
                                         caption=caption,
                                         parse_mode="Markdown")
            return
        except:
            pass
    await update.message.reply_text(caption, parse_mode="Markdown")


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    ws = get_waifu_sheet()
    row, values = get_or_create_user_row(ws, user_id, username)

    today = date.today()
    last_daily = None
    if len(values) > 4 and values[4]:
        last_daily = date.fromisoformat(values[4])
    if last_daily == today:
        await update.message.reply_text("📅 You already used daily today!")
        return

    char = fetch_random_character()
    if not char:
        await update.message.reply_text("🚫 Failed to fetch character.")
        return

    coll = []
    if len(values) > 2 and values[2]:
        try:
            coll = json.loads(values[2])
        except:
            coll = []
    coll.append(char)
    ws.update_cell(row, 3, json.dumps(coll))
    ws.update_cell(row, 5, today.isoformat())

    caption = f"🌟 Daily pull: **{char['name']}**!"
    if char.get("image_url"):
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id,
                                         photo=char["image_url"],
                                         caption=caption,
                                         parse_mode="Markdown")
            return
        except:
            pass
    await update.message.reply_text(caption, parse_mode="Markdown")


async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ws = get_waifu_sheet()
    col1 = ws.col_values(1)
    if str(user_id) not in col1:
        await update.message.reply_text("❌ No characters yet. Use /claim!")
        return
    row = col1.index(str(user_id)) + 1
    values = ws.row_values(row)

    coll = []
    if len(values) > 2 and values[2]:
        try:
            coll = json.loads(values[2])
        except:
            coll = []
    if not coll:
        await update.message.reply_text("❌ No characters yet. Use /claim!")
        return

    married_id = values[5] if len(values) > 5 else None
    text = "📚 **Your Collection:**\n"
    for i, char in enumerate(coll, start=1):
        line = f"{i}. {char.get('name','Unknown')}"
        if married_id and str(char.get("id")) == married_id:
            line += " 💖 (Married)"
        text += line + "\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def marry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ws = get_waifu_sheet()
    col1 = ws.col_values(1)
    if str(user_id) not in col1:
        await update.message.reply_text("❌ You have no characters. Use /claim first!")
        return
    row = col1.index(str(user_id)) + 1
    values = ws.row_values(row)

    coll = []
    if len(values) > 2 and values[2]:
        try:
            coll = json.loads(values[2])
        except:
            coll = []
    if not coll:
        await update.message.reply_text("❌ You have no characters.")
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /marry <number>")
        return
    idx = int(args[0])
    if idx < 1 or idx > len(coll):
        await update.message.reply_text("❌ Invalid index.")
        return

    spouse = coll[idx-1]
    ws.update_cell(row, 6, str(spouse.get("id")))
    await update.message.reply_text(f"💍 Married to **{spouse.get('name')}**!", parse_mode="Markdown")


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Trade system coming soon!")

# ---------- Auto Drop ----------
async def auto_drop(context: ContextTypes.DEFAULT_TYPE):
    ws = get_waifu_sheet()
    # sab groups ki list nikalo
    group_ids = list(set(ws.col_values(7)))
    for gid in group_ids:
        if not gid or gid == "group_id":
            continue
        char = fetch_random_character()
        if not char:
            continue
        caption = f"⚡ A wild waifu appeared: **{char['name']}**!\nType /claim to grab!"
        try:
            await context.bot.send_photo(chat_id=int(gid),
                                         photo=char["image_url"],
                                         caption=caption,
                                         parse_mode="Markdown")
        except:
            await context.bot.send_message(chat_id=int(gid), text=caption, parse_mode="Markdown")
    ws.update_cell(2, 8, datetime.utcnow().isoformat())  # last_drop time
