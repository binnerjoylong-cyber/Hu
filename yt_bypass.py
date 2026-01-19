import httpx
import re
from telegram import Update
from telegram.ext import ContextTypes

# --- CONFIGURATION ---
RAPID_API_KEY = "37c6bbf0b8msh8958361d209856ep1583d8jsnb0a351252afd"
API_HOST = "social-media-video-downloader.p.rapidapi.com"

async def get_video_data(url: str):
    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": API_HOST
    }

    # 1. URL Cleaning (Kachra saaf karo)
    # Isse ?igsh=... jaise tracking parameters hat jayenge
    clean_url = url.split('?')[0].strip()
    print(f"DEBUG: Cleaning URL -> {clean_url}")

    # 2. Platform Detection
    is_insta = "instagram.com" in clean_url
    is_youtube = any(x in clean_url for x in ["youtube.com", "youtu.be"])

    # --- Case 1: INSTAGRAM ---
    if is_insta:
        api_url = "https://social-media-video-downloader.p.rapidapi.com/instagram/v1/post/details"
        params = {"url": clean_url}
        
        async with httpx.AsyncClient(timeout=40.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params=params)
                data = response.json()
                
                # Insta response check
                items = data.get("items", [])
                if items:
                    video_url = items[0].get("video_url")
                    return video_url, "Instagram Reel"
                return None, "Insta video link not found."
            except Exception as e:
                return None, f"Insta API Error: {str(e)}"

    # --- Case 2: YOUTUBE ---
    elif is_youtube:
        video_id_match = re.search(r'(?:v=|youtu\.be/|watch\?v=|shorts/|live/|reel/)([a-zA-Z0-9_-]{11})', clean_url)
        if not video_id_match: 
            return None, "YouTube ID not found."
        
        video_id = video_id_match.group(1)
        api_url = "https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details"
        params = {"videoId": video_id, "urlAccess": "proxied"}

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params=params)
                data = response.json()
                contents = data.get("contents", [])
                if not contents: return None, "YT contents empty."
                
                video_list = contents[0].get("videos", [])
                
                # Audio + Video Combined Fix
                for v in video_list:
                    meta = v.get("metadata", {})
                    if (meta.get("has_audio") and meta.get("has_video")) or v.get("label") in ["720p", "360p"]:
                        return v.get("url"), data.get("title", "YouTube Video")
                
                if video_list:
                    return video_list[0].get("url"), data.get("title", "YouTube Video")
            except Exception as e:
                return None, f"YouTube API Error: {str(e)}"

    return None, f"Platform not supported! Clean URL: {clean_url}"
            
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
async def social_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    
    # YouTube aur Instagram dono ke liye check:
    match = re.search(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com)/[^\s]+', text)
    
    if match:
        url = match.group(0)
        await handle_youtube_link(update, context, url) # Naam wahi rehne do, kaam ho jayega
# yt_bypass.py ke andar
async def youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /youtube <link>"""
    if not context.args:
        await update.message.reply_text("Bhai, link toh do! Format: /youtube <link>")
        return
    
    url = context.args[0]
    await handle_youtube_link(update, context, url)
