import asyncio
import yt_dlp
import random
import httpx
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- 1. PROXY ROTATOR (Render IP Block Se Bachne Ke Liye) ---
async def get_video_direct(url: str):
    """
    Direct API Bridge: Ye yt-dlp use nahi karta, isliye Render block nahi hoga.
    """
    # Naye stable gateways
    gateways = [
        "https://api.cobalt.tools/api/json",
        "https://cobalt-api.v06.io/api/json",
        "https://api.v06.io/api/json"
    ]
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0"
    }
    
    payload = {"url": url, "vQuality": "720"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for api in gateways:
            try:
                res = await client.post(api, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    # Direct link status check
                    if data.get("status") in ["stream", "redirect"]:
                        return data.get("url"), "Video"
                    if data.get("status") == "picker":
                        return data["picker"][0]["url"], "Video"
            except:
                continue
    return None, None

# --- Core Handler Update ---
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id=chat_id, text="🚀 **Bypassing with API Bridge...**")

    # Yahan hum direct API call kar rahe hain, yt-dlp nahi
    video_url, title = await get_video_direct(url)

    if video_url:
        try:
            await context.bot.send_video(chat_id=chat_id, video=video_url, caption="✅ **Done!**")
            await msg.delete()
        except:
            await msg.edit_text("❌ Size too big for Telegram.")
    else:
        # Last resort button
        ss_url = url.replace("youtube.com", "ssyoutube.com").replace("youtu.be", "ssyoutube.com")
        keyboard = [[InlineKeyboardButton("📥 Download Manually", url=ss_url)]]
        await msg.edit_text("🛑 Security High! Use button:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    # --- FINAL FALLBACK: Agar sab kuch fail ho jaye ---
    

# --- 4. MESSAGE HANDLER (Auto Detect) ---
async def auto_youtube_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return
    
    # YouTube Link Regex
    yt_regex = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/[^\s]+'
    match = re.search(yt_regex, update.message.text)
    
    if match:
        asyncio.create_task(handle_youtube_link(update, context, match.group(0)))

# --- 5. COMMAND HANDLER ---
async def youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Adhyan, link toh do! `/youtube <link>`")
        return
    await handle_youtube_link(update, context, context.args[0])
