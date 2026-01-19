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

    # URL Cleaning
    clean_url = url.split('?')[0].strip()

    # --- Case 1: INSTAGRAM ---
    if "instagram.com" in clean_url:
        api_url = "https://social-media-video-downloader.p.rapidapi.com/instagram/v1/post/details"
        params = {"url": clean_url}
        
        async with httpx.AsyncClient(timeout=40.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params=params)
                data = response.json()
                
                # Naya Parsing Logic: Insta kabhi 'items' bhejta hai kabhi seedha data
                items = data.get("items", [])
                video_url = None
                
                if items:
                    # Pehle item ki video dhoondo
                    video_url = items[0].get("video_url") or items[0].get("video_versions", [{}])[0].get("url")
                
                if not video_url:
                    # Agar items mein nahi mila toh pure response mein dhoondo
                    video_url = data.get("video_url")
                
                if video_url:
                    return video_url, "Instagram Reel"
                return None, "Insta link found but it's not a video (maybe a photo?)."
            except Exception as e:
                return None, f"Insta API Error: {str(e)}"

    # --- Case 2: YOUTUBE ---
    elif any(x in clean_url for x in ["youtube.com", "youtu.be"]):
        video_id_match = re.search(r'(?:v=|youtu\.be/|watch\?v=|shorts/|live/|reel/)([a-zA-Z0-9_-]{11})', clean_url)
        if not video_id_match: return None, "YT ID Error"
        
        video_id = video_id_match.group(1)
        api_url = "https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details"
        params = {"videoId": video_id, "urlAccess": "proxied"}

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.get(api_url, headers=headers, params=params)
                data = response.json()
                contents = data.get("contents", [])
                if not contents: return None, "YT contents empty"
                
                video_list = contents[0].get("videos", [])
                
                # --- AAWAZ KA PAKKA ILAJ (Combined Formats Only) ---
                # YouTube ITAG 22 (720p) aur 18 (360p) humesha combined hote hain (Video+Audio)
                # Hum pehle unko filter karenge
                
                # Priority 1: ITAG 22 (720p Combined)
                for v in video_list:
                    if v.get("metadata", {}).get("itag") == 22:
                        return v.get("url"), data.get("title", "YT Video")
                
                # Priority 2: ITAG 18 (360p Combined)
                for v in video_list:
                    if v.get("metadata", {}).get("itag") == 18:
                        return v.get("url"), data.get("title", "YT Video")
                
                # Priority 3: Label check agar itag na mile
                for v in video_list:
                    meta = v.get("metadata", {})
                    if meta.get("has_audio") and meta.get("has_video"):
                        return v.get("url"), data.get("title", "YT Video")

                return None, "No Video+Audio combined link found."
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
