import httpx
import re
from telegram import Update
from telegram.ext import ContextTypes

# --- CONFIGURATION ---
RAPID_API_KEY = "37c6bbf0b8msh8958361d209856ep1583d8jsnb0a351252afd"
API_HOST = "social-media-video-downloader.p.rapidapi.com"

async def get_video_data(url: str):
    regex = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    video_id_match = re.search(regex, url)
    
    if not video_id_match:
        return None, "Invalid URL"
    
    video_id = video_id_match.group(1)
    api_url = "https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details"
    
    # Renderable formats ko badal kar dekhte hain
    params = {
        "videoId": video_id,
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
            
            # Debugging ke liye title print karte hain
            title = data.get("title", "YouTube Video")
            print(f"DEBUG: Processing -> {title}")

            # Sabse pehle 'formats' check karo
            formats = data.get("formats", [])
            # Phir 'adaptiveFormats' bhi check karo (Video + Audio)
            adaptive = data.get("adaptiveFormats", [])
            
            # Combine both lists to search everywhere
            all_formats = formats + adaptive
            
            # Hum sirf wo links chahiye jisme 'url' ho aur jo MP4 type ho
            for f in all_formats:
                link = f.get("url")
                if link:
                    # Agar link mil gaya toh wahi return kar do
                    return link, title
            
            return None, "API didn't provide a valid MP4 link."
        except Exception as e:
            return None, f"Error: {str(e)}"
            
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
