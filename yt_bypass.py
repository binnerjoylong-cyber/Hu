import httpx
import re
from telegram import Update
from telegram.ext import ContextTypes

# --- CONFIGURATION ---
RAPID_API_KEY = "37c6bbf0b8msh8958361d209856ep1583d8jsnb0a351252afd"
API_HOST = "social-media-video-downloader.p.rapidapi.com"

async def get_video_data(url: str):
    # 1. Advanced Regex: Ye Shorts, Mobile, aur Desktop sab handle karega
    regex = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    
    video_id_match = re.search(regex, url)
    
    if not video_id_match:
        print(f"DEBUG: Regex Failed for URL -> {url}") # Logs mein check karne ke liye
        return None, "Invalid URL"
    
    video_id = video_id_match.group(1)
    print(f"DEBUG: Found Video ID -> {video_id}")
    
    # 2. API Call Setup (Same as before)
    api_url = "https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details"
    params = {
        "videoId": video_id,
        "renderableFormats": "720p,480p",
        "urlAccess": "proxied"
    }
    
    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": API_HOST
    }

    async with httpx.AsyncClient(timeout=40.0) as client:
        try:
            response = await client.get(api_url, headers=headers, params=params)
            data = response.json()
            
            # 3. Check if API actually returned data
            if response.status_code != 200:
                return None, f"API Error: {response.status_code}"

            formats = data.get("formats", [])
            title = data.get("title", "YouTube Video")
            
            if formats:
                # Sabse best available link (format list se)
                direct_link = formats[0].get("url")
                return direct_link, title
            
            return None, "API returned no formats."
        except Exception as e:
            return None, f"Request Failed: {str(e)}"

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id=chat_id, text="🎯 **API Gateway Connected. Fetching Video...**")

    direct_url, title = await get_video_data(url)

    if direct_url:
        try:
            # Telegram internally link ko stream karega aur user ko video bhejega
            await context.bot.send_video(
                chat_id=chat_id,
                video=direct_url,
                caption=f"🎥 **{title}**\n\n✅ _Bypassed & Delivered!_"
            )
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ **Telegram Error:** File size exceeds 50MB limit.")
    else:
        await msg.edit_text(f"🛑 **Failed:** {title}")

# Auto-handler ko main.py mein register karna mat bhoolna!
async def youtube_auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    match = re.search(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/[^\s]+', update.message.text)
    if match:
        await handle_youtube_link(update, context, match.group(0))
# yt_bypass.py ke andar
async def youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /youtube <link>"""
    if not context.args:
        await update.message.reply_text("Bhai, link toh do! Format: /youtube <link>")
        return
    
    url = context.args[0]
    await handle_youtube_link(update, context, url)
