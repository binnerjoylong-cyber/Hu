import asyncio
import yt_dlp
import random
import httpx
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- 1. PROXY ROTATOR (Render IP Block Se Bachne Ke Liye) ---
async def get_working_proxy():
    """Public proxy list se ek random proxy uthata hai."""
    try:
        # Free proxy list API
        proxy_api = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=1000&country=all&ssl=all&anonymity=all"
        async with httpx.AsyncClient() as client:
            res = await client.get(proxy_api)
            if res.status_code == 200:
                proxies = res.text.strip().split('\r\n')
                return random.choice(proxies)
    except:
        return None
    return None

# --- 2. PRIVATE DOWNLOADER (With Advanced Headers) ---
def sync_extract_video(url, proxy=None):
    """Bina download kiye direct stream link nikalta hai."""
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][filesize<=50M]+bestaudio[ext=m4a]/best[ext=mp4][filesize<=50M]',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'proxy': f"http://{proxy}" if proxy else None,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/',
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get('url'), info.get('title', 'Video')

# --- 3. CORE HANDLER (Main Logic) ---
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id=chat_id, text="🛰️ **Laila is bypassing YouTube Firewall...**", parse_mode='Markdown')
    
    # Proxy fetch karo
    proxy = await get_working_proxy()
    
    try:
        # Step 1: Extract Video Link
        # Hum ise thread mein chalayenge taaki bot freeze na ho
        video_url, title = await asyncio.to_thread(sync_extract_video, url, proxy)
        
        if video_url:
            await msg.edit_text(f"📥 **Bypassed!** Sending: `{title[:40]}...`", parse_mode='Markdown')
            
            # Step 2: Upload to Telegram
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_url,
                caption=f"🎥 **{title}**\n\n_Bypassed Render Restriction_ ✅",
                parse_mode='Markdown'
            )
            await msg.delete()
            return
            
    except Exception as e:
        print(f"Bypass Failed: {e}")
        
    # --- FINAL FALLBACK: Agar sab kuch fail ho jaye ---
    ss_url = url.replace("youtube.com", "ssyoutube.com").replace("youtu.be", "ssyoutube.com")
    keyboard = [[InlineKeyboardButton("📥 Direct Download Link", url=ss_url)]]
    
    await msg.edit_text(
        "💀 **YouTube Security is extremely tight!**\n\nDirect file nahi ja rahi, par aap is link se turant download kar sakte hain:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
