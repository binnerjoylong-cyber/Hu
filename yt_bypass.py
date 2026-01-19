import httpx
import re
from telegram import Update
from telegram.ext import ContextTypes

# --- CONFIGURATION ---
RAPID_API_KEY = "37c6bbf0b8msh8958361d209856ep1583d8jsnb0a351252afd"
API_HOST = "social-media-video-downloader.p.rapidapi.com"

import asyncio

# Sabse powerfull function jo JSON mein kahin bhi video link dhoond lega
def find_video_url(obj):
    if isinstance(obj, dict):
        # Agar direct 'video_url' mil jaye
        if obj.get('video_url'): return obj['video_url']
        # YouTube ke liye itag 22 (720p with audio) best hai
        if obj.get('itag') == 22 and obj.get('url'): return obj['url']
        # Baaki sab ke liye recursively dhoondo
        for k, v in obj.items():
            res = find_video_url(v)
            if res: return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_video_url(item)
            if res: return res
    return None

async def get_video_data(url: str):
    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": API_HOST
    }
    clean_url = url.split('?')[0].strip()

    # --- INSTAGRAM ---
    if "instagram.com" in clean_url:
        api_url = "https://social-media-video-downloader.p.rapidapi.com/instagram/v1/post/details"
        async with httpx.AsyncClient(timeout=40.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params={"url": clean_url})
                data = response.json()
                
                # Deep search for video URL
                video_url = find_video_url(data)
                if video_url:
                    return video_url, "Instagram Reel"
                return None, "Video URL hidden deep in Insta API."
            except Exception as e:
                return None, f"Insta API Error: {str(e)}"

    # --- YOUTUBE ---
    elif any(x in clean_url for x in ["youtube.com", "youtu.be"]):
        video_id = re.search(r'(?:v=|youtu\.be/|watch\?v=|shorts/|reel/)([a-zA-Z0-9_-]{11})', clean_url).group(1)
        api_url = "https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details"
        
        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params={"videoId": video_id, "urlAccess": "proxied"})
                data = response.json()
                
                # YouTube Audio Fix: Filter for itag 22 or 18 (Combined Audio/Video)
                contents = data.get("contents", [{}])[0].get("videos", [])
                
                # 1. First priority: ITAG 22 (720p + Audio)
                for v in contents:
                    if v.get("metadata", {}).get("itag") == 22:
                        return v.get("url"), data.get("title", "YT Video")
                
                # 2. Second priority: ITAG 18 (360p + Audio)
                for v in contents:
                    if v.get("metadata", {}).get("itag") == 18:
                        return v.get("url"), data.get("title", "YT Video")
                
                # 3. Last Resort: Any link with video+audio flags
                for v in contents:
                    m = v.get("metadata", {})
                    if m.get("has_audio") and m.get("has_video"):
                        return v.get("url"), data.get("title", "YT Video")

                return None, "Could not find a combined Video+Audio link."
            except Exception as e:
                return None, f"YT API Error: {str(e)}"

    return None, "Platform not supported."
            
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
