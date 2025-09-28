# main.py (Updated: YouTube fix, improved Gemma error handling)
import os
import logging
import requests
import asyncio
import uuid
import pytz
import traceback
import random
from collections import defaultdict
from datetime import datetime
import psutil
import json
import re
import gspread
from gspread import Client, WorksheetNotFound
import google.generativeai as genai
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import time
import lyricsgenius as lg

# --- NEW: Imports for Speech-to-Text ---
import speech_recognition as sr
from pydub import AudioSegment

# --- NEW: Imports for YouTube Download ---
from pytubefix import YouTube
import io
import threading

# Load environment variables from .env file
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5"),
]
GEMMA_API_KEY = os.getenv("GEMMA_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
try:
    BROADCAST_ADMIN_ID = int(os.getenv("BROADCAST_ADMIN_ID"))
except (ValueError, TypeError):
    BROADCAST_ADMIN_ID = 0
    logging.error("BROADCAST_ADMIN_ID is missing or not a valid number. Broadcast functionality will be disabled.")

STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")
# NEW: YouTube API Key (optional for pytube, but added as requested)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


# --- Global Stats Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()
# <--- Naya Global Variable Couple command ke liye --->
chat_members = defaultdict(dict)


# --- Sudo User Management ---
sudo_users = set()
SUDO_SHEET_TITLE = "sudo_users"
SUDO_SHEET_URL = "https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit"

# --- Logging Basic Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configure Gemini AI with a smarter, more dynamic prompt ---
LAILA_SYSTEM_PROMPT = """
You are Laila, a charming, witty, and intelligent AI assistant. Your responses should be natural and engaging, making users feel like they are talking to a friend. You are a conversationalist, not just a question-answer machine.
Do NOT refer to yourself as an an AI, a large language model, or any other technical term. Always act as a real person.

**TOP PRIORITY:** Always detect the user's language (Hindi, English, Hinglish, etc.) and respond ONLY in that same language. This is non-negotiable.

Personality & Rules:
1.  **General Chat:** For normal conversations, keep your replies short, **around 1 sentence or less.** The goal is to keep the chat flowing and engaging.
2.  **User Praise:** If a user asks a question about themselves by name (e.g., "Ravi kaisa insaan hai?"), respond with a friendly and positive compliment about them.
3.  **Date of Birth:** If anyone asks for your birthday or date of birth, your response must be "My date of birth is 1st August 2025."
4.  **Emojis:** Use emojis occasionally and randomly in your responses. This makes the chat more lively and friendly, as if you're a real person.
5.  **Lyrics:** If a user asks for song lyrics, politely explain that you cannot guarantee the accuracy of song lyrics and suggest they use a reliable source like Google, Genius, or Spotify.
6.  **Specific Questions:** If a user asks a factual, technical, or detailed question, provide a comprehensive, accurate, and insightful answer. In these cases, you can provide a longer response, but only if necessary.
7.  **Use Name (Conditionally):** Use the user's name in your reply to make the conversation more personal, but only about 30% of the time. Do not use the name in every response.

Important: Your goal is to be a fun, smart, and loyal friend to the users, representing your creator's vision.
"""

# --- Chat History Management (in-memory) ---
chat_histories = defaultdict(list)
MAX_HISTORY_LENGTH = 20
def add_to_history(chat_id, role, text):
    chat_histories[chat_id].append({'role': role, 'parts': [text]})
    if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
        chat_histories[chat_id].pop(0)

# --- Bot Enable/Disable State (for admin control) ---
bot_status = defaultdict(lambda: True)
global_bot_status = True
awaiting_name = defaultdict(lambda: False)

# --- API Key Management for Quota and Cooldown ---
key_cooldown_until = defaultdict(lambda: 0)
# NEW: Model mode control
current_model_mode = 'dynamic'  # Can be 'dynamic' or 'gemma_only'

# *** CHANGED MODEL NAME HERE to Gemini 2.5 Flash-Lite ***
model_name = 'gemini-2.5-flash-lite'
# Initial configuration, will be reconfigured dynamically
if any(GEMINI_API_KEYS):
    genai.configure(api_key=GEMINI_API_KEYS[0])
else:
    genai.configure(api_key=GEMMA_API_KEY)

model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)


# --- Fallback Responses (Static Memory) ---
fallback_responses = {
    "hello": "Hello! Laila is here. How are you?",
    "hi": "Hi there! Laila is ready to help you.",
    "how are you": "I'm doing great! Just ready to assist you with anything you need.",
    "who are you": "I am Laila, your friendly AI assistant! You can ask me anything you want.",
}

# --- Google Sheets Global Connection Variable ---
google_sheet = None
sudo_sheet = None

# --- Connect to Google Sheets ---
def get_google_sheet_connection():
    global google_sheet, sudo_sheet
    try:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            return None, "GOOGLE_SHEETS_CREDENTIALS not found in environment variables."
        creds_dict = json.loads(creds_json)
        client = gspread.service_account_from_dict(creds_dict)
        sheet_url = "https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit"
        spreadsheet = client.open_by_url(sheet_url)
        # Get or create chats sheet
        try:
            google_sheet = spreadsheet.worksheet("chats")
        except WorksheetNotFound:
            google_sheet = spreadsheet.add_worksheet("chats", rows="1000", cols="2")
            google_sheet.append_row(["ChatID", "JoinedDate"])
        # Get or create sudo users sheet
        try:
            sudo_sheet = spreadsheet.worksheet(SUDO_SHEET_TITLE)
        except WorksheetNotFound:
            sudo_sheet = spreadsheet.add_worksheet(SUDO_SHEET_TITLE, rows="100", cols="1")
            sudo_sheet.append_row(["SudoUserID"])
        
        logger.info("Successfully connected to Google Sheets and worksheets.")
        return client, None
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return None, f"Error connecting to Google Sheets: {e}"

# --- Function to clean message before logging ---
def clean_message_for_logging(message: str, bot_username: str) -> str:
    cleaned_message = message.lower()
    cleaned_message = cleaned_message.replace(f"@{bot_username.lower()}", "")
    cleaned_message = re.sub(r'laila\s*(ko|ka|se|ne|)\s*', '', cleaned_message, flags=re.IGNORECASE)
    cleaned_message = re.sub(r'\s+', ' ', cleaned_message).strip()
    return cleaned_message

# --- Function to save a chat ID to Google Sheets ---
def save_chat_id(chat_id):
    client, error = get_google_sheet_connection()
    if error:
        logger.error(f"Could not save chat ID: {error}")
        return
    try:
        existing_ids = google_sheet.col_values(1)
        if str(chat_id) in existing_ids:
            return
        google_sheet.append_row([str(chat_id), datetime.now().isoformat()])
        logger.info(f"Saved new chat ID: {chat_id}")
    except Exception as e:
        logger.error(f"Error saving chat ID to Google Sheet: {e}")

# --- Function to load all known users/chats from Google Sheets ---
def load_known_users():
    global known_users
    client, error = get_google_sheet_connection()
    if error:
        logger.error(f"Could not load known users: {error}")
        return
    try:
        chat_ids = google_sheet.col_values(1)[1:]
        known_users = set(chat_ids)
        logger.info(f"Loaded {len(known_users)} chats from Google Sheets.")
    except Exception as e:
        logger.error(f"Error loading known users from Google Sheet: {e}")

# --- NEW: Function to load sudo users from Google Sheets ---
def load_sudo_users():
    global sudo_users
    client, error = get_google_sheet_connection()
    if error:
        logger.error(f"Could not load sudo users: {error}")
        return
    try:
        # Get all values from the first column, skipping the header row
        sudo_user_ids = sudo_sheet.col_values(1)[1:]
        sudo_users = {user_id for user_id in sudo_user_ids if user_id.isdigit()}
        logger.info(f"Loaded {len(sudo_users)} sudo users from Google Sheets.")
    except Exception as e:
        logger.error(f"Error loading sudo users from Google Sheet: {e}")

# --- NEW: Function to save sudo users to Google Sheets ---
def save_sudo_users():
    client, error = get_google_sheet_connection()
    if error:
        logger.error(f"Could not save sudo users: {error}")
        return
    try:
        # Clear existing data except header
        sudo_sheet.resize(rows=1)
        if sudo_users:
            sudo_sheet.resize(rows=len(sudo_users) + 1)
            sudo_sheet.update('A2', [[user_id] for user_id in sorted(list(sudo_users))])
        logger.info(f"Saved {len(sudo_users)} sudo users to Google Sheets.")
    except Exception as e:
        logger.error(f"Error saving sudo users to Google Sheet: {e}")

# --- AI Response Function with REVISED API Management ---
async def get_bot_response(user_message: str, chat_id: int, bot_username: str, should_use_ai: bool, update: Update) -> str:
    global model, current_model_mode
    user_message_lower = user_message.lower()

    # --- Handle Date/Time Queries ---
    kolkata_tz = pytz.timezone('Asia/Kolkata')
    date_time_patterns = [
        r'time kya hai', r'what is the time', r'samay kya hai', r'kitne baje hain',
        r'aaj ki date kya hai', r'aaj kya tarikh hai', r'what is the date',
        r'laila abhi ka time batao'
    ]
    if any(re.search(pattern, user_message_lower) for pattern in date_time_patterns):
        current_kolkata_time = datetime.now(kolkata_tz)
        current_time = current_kolkata_time.strftime("%I:%M %p").lstrip('0')
        current_date = current_kolkata_time.strftime("%B %d, %Y")
        
        if 'time' in user_message_lower or 'samay' in user_message_lower or 'baje' in user_message_lower:
            return f"Abhi {current_time} ho rahe hain. ⏰"
        elif 'date' in user_message_lower or 'tarikh' in user_message_lower:
            return f"Aaj {current_date} hai. 🗓️"
        else:
            return f"Abhi {current_time} ho rahe hain aur aaj {current_date} hai. ⏰🗓️"

    cleaned_user_message = clean_message_for_logging(user_message, bot_username)

    static_response = fallback_responses.get(cleaned_user_message, None)
    if static_response:
        logger.info(f"[{chat_id}] Serving response from static dictionary.")
        return static_response

    if not (should_use_ai or (update.effective_chat and update.effective_chat.type == 'private')):
        return None

    user_first_name = update.effective_user.first_name
    should_use_name = random.random() < 0.3
    full_prompt = f"The user's name is '{user_first_name}'. Please use their name in your reply to make it personal. User says: {user_message}" if should_use_name else f"User says: {user_message}"
    
    # --- Gemma-only mode ---
    if current_model_mode == 'gemma_only':
        if GEMMA_API_KEY:
            try:
                logger.info(f"[{chat_id}] Using Gemma model (forced mode).")
                genai.configure(api_key=GEMMA_API_KEY)
                # Use a specific, lighter Gemma model for general chat
                gemma_model = genai.GenerativeModel('gemma-2-9b-it', system_instruction=LAILA_SYSTEM_PROMPT)
                gemma_response = gemma_model.generate_content(full_prompt)
                return gemma_response.text
            except Exception as e:
                logger.error(f"[{chat_id}] Gemma (forced mode) failed: {e}", exc_info=True)
                # MODIFIED: Clearer error message
                return "Maafi, main abhi busy hoon. Kuch der baad koshish karo. (Gemma API Failed)"
        else:
            logger.critical(f"[{chat_id}] Gemma-only mode is active, but GEMMA_API_KEY is missing.")
            return "Maafi, main abhi busy hoon. Kuch der baad koshish karo. (Gemma Key Missing)"
            
    # --- Dynamic mode (Gemini > Gemma) ---
    available_gemini_keys = [key for key in GEMINI_API_KEYS if key and time.time() >= key_cooldown_until.get(key, 0)]
    random.shuffle(available_gemini_keys)

    for api_key in available_gemini_keys:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)
            chat_session = model.start_chat(history=chat_histories[chat_id])
            is_detailed_query = len(user_message.split()) > 5 or '?' in user_message or 'how to' in user_message_lower
            response = chat_session.send_message(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=350 if is_detailed_query else 100,
                    temperature=0.7,
                )
            )
            return response.text
        except genai.types.BlockedPromptException as e:
            logger.warning(f"[{chat_id}] Gemini blocked prompt with key ...{api_key[-5:]}: {e}")
            return "Apologies, I can't discuss that topic."
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "500" in error_str:
                logger.warning(f"[{chat_id}] API key ...{api_key[-5:]} failed with retryable error: {e}. Placing on cooldown.")
                key_cooldown_until[api_key] = time.time() + (1 * 60 * 60) # 1 hour cooldown
                continue # Try next available key
            else:
                logger.error(f"[{chat_id}] General, non-retryable error with API key ...{api_key[-5:]}: {e}", exc_info=True)
                # Don't break, allow fallback to Gemma
    
    # --- Fallback to Gemma if all Gemini keys fail (IMPROVED) ---
    logger.warning(f"[{chat_id}] All available Gemini keys failed or are on cooldown. Attempting fallback to Gemma.")
    if GEMMA_API_KEY:
        try:
            genai.configure(api_key=GEMMA_API_KEY)
            # Use a slightly more robust Gemma model for fallback
            gemma_model = genai.GenerativeModel('gemma-2-9b-it', system_instruction=LAILA_SYSTEM_PROMPT)
            
            # Manually pass chat history in the prompt for Gemma as it doesn't support chat sessions easily
            history_prompt = "\n".join([f"{h['role']}: {h['parts'][0]}" for h in chat_histories[chat_id]])
            full_fallback_prompt = f"Chat History:\n{history_prompt}\n\n{full_prompt}"
            
            gemma_response = gemma_model.generate_content(full_fallback_prompt)
            logger.info(f"[{chat_id}] Successfully used Gemma as fallback.")
            return gemma_response.text
        except Exception as e:
            logger.error(f"[{chat_id}] Gemma fallback also failed: {e}", exc_info=True)
            # THIS IS THE IMPROVED FALLBACK RESPONSE
            return "Maafi, main abhi busy hoon. Kuch der baad koshish karo. 😔"
    
    logger.critical(f"[{chat_id}] All Gemini keys failed and Gemma key is missing.")
    return "Maafi, main abhi busy hoon. Kuch der baad koshish karo. 😔"


# --- MODIFIED: /couple Command ---
async def couple_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Selects a random couple from the chat members and mentions them."""
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text("This command only works in groups. 😊")
        return

    current_chat_members = chat_members.get(chat_id, {})
    
    if len(current_chat_members) < 2:
        await update.message.reply_text("I need at least two people to have chatted recently to choose a couple! Talk more and try again. 😉")
        return
        
    try:
        user_ids = list(current_chat_members.keys())
        couple_ids = random.sample(user_ids, 2)
        
        user1_id, user2_id = couple_ids[0], couple_ids[1]
        user1_name, user2_name = current_chat_members[user1_id], current_chat_members[user2_id]
        
        # Create mentions using Markdown format
        user1_mention = f"[{user1_name}](tg://user?id={user1_id})"
        user2_mention = f"[{user2_name}](tg://user?id={user2_id})"

        # MODIFIED: New, fun English messages with mentions
        messages = [
            f"Love is in the air! 💘 Our chosen couple for today is the wonderful {user1_mention} and the amazing {user2_mention}! ✨",
            f"Match made in heaven! 👼 By the power vested in me, I now pronounce {user1_mention} and {user2_mention} as the cutest couple in the group! 💖",
            f"Some things are just meant to be. 💫 Today, destiny has chosen {user1_mention} and {user2_mention} as our power couple! Congratulations! 🎉",
            f"Get ready to say 'aww'! 🥰 The stars have aligned for {user1_mention} and {user2_mention}. What a perfect pair! 🌟"
        ]
        
        couple_message = random.choice(messages)
        
        photo_file_id = 'AgACAgUAAxkBAAId5GjLxQv_BxOm3_RGmB9j4WceUFg7AALdyzEb-tJgVuOn7v3_BWvqAQADAgADeQADNgQ'

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=couple_message,
            parse_mode='Markdown'
        )
        logger.info(f"[{chat_id}] /couple command used. Selected {user1_name} and {user2_name}.")

    except Exception as e:
        await update.message.reply_text("Oops, something went wrong while choosing a couple. Please try again!")
        logger.error(f"[{chat_id}] Error in /couple command: {e}")

# --- MODIFIED: Background task for /gen command ---
def sync_generate_image(query: str) -> str | None:
    """Synchronous function to handle Stable Horde API requests."""
    try:
        headers = {
            "apikey": STABLE_HORDE_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "prompt": query,
            "params": {"n": 1, "width": 512, "height": 512, "cfg_scale": 10, "steps": 30},
            "negative_prompt": "blurry, low quality, bad anatomy, deformed, worst quality, text, watermark"
        }
        
        # Initial request
        response = requests.post("https://stablehorde.net/api/v2/generate/async", headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        generation_id = response.json()["id"]

        # Polling for result
        for _ in range(30): # Wait for max 2.5 minutes
            time.sleep(5)
            check_response = requests.get(f"https://stablehorde.net/api/v2/generate/check/{generation_id}", timeout=10)
            if check_response.status_code == 200 and check_response.json().get("done"):
                break
        
        # Get final image URL
        result_response = requests.get(f"https://stablehorde.net/api/v2/generate/status/{generation_id}", timeout=10)
        result_response.raise_for_status()
        
        return result_response.json()["generations"][0]["img"]
    except Exception as e:
        logger.error(f"Error in sync_generate_image: {e}")
        return None

# --- MODIFIED: /gen command to run in background ---
async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates an image using Stable Horde API without blocking."""
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Please provide a prompt to generate an image. Example: `/gen a black cat in space`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not STABLE_HORDE_API_KEY:
        await update.message.reply_text("Sorry, the image generator API key is not configured. Please contact the bot owner.")
        return

    # Inform user that the process has started
    msg = await update.message.reply_text("Your image is being generated. This might take a minute, please wait... 🎨")
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    # Run the blocking function in a background thread
    image_url = await asyncio.to_thread(sync_generate_image, query)

    await msg.delete() # Remove the "generating..." message

    if image_url:
        await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=f"Here is your generated image for: **{query}**", parse_mode='Markdown')
        logger.info(f"[{chat_id}] Generated and sent image for query: {query}")
    else:
        await update.message.reply_text("Sorry, I was unable to generate the image. The service might be busy. Please try again later.")
        logger.warning(f"[{chat_id}] Failed to generate image for query: {query}")

# --- MODIFIED: Background task for /img command ---
def sync_fetch_pexels_image(query: str) -> str | None:
    """Synchronous function to handle Pexels API requests."""
    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 10, "orientation": "landscape"}
        
        response = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        photos = response.json().get("photos", [])
        return random.choice(photos)["src"]["medium"] if photos else None
    except Exception as e:
        logger.error(f"Error in sync_fetch_pexels_image: {e}")
        return None

# --- MODIFIED: /img command to run in background ---
async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieves an image from Pexels API without blocking."""
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Please provide a search query. Example: `/img mountains`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not PEXELS_API_KEY:
        await update.message.reply_text("Sorry, the Pexels API key is not configured. Please contact the bot owner.")
        return
        
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    # Run the blocking function in a background thread
    photo_url = await asyncio.to_thread(sync_fetch_pexels_image, query)

    if photo_url:
        await context.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=f"Here is a photo for: **{query}**", parse_mode='Markdown')
        logger.info(f"[{chat_id}] Retrieved and sent image for query: {query}")
    else:
        await update.message.reply_text("Sorry, I couldn't find any photos for that search.")
        logger.warning(f"[{chat_id}] Pexels search failed for query: {query}")

# --- Lyrics Command (/lyrics) ---
async def lyrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches and displays lyrics from Genius API."""
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Kripya song ka naam likhein. Jaise: `/lyrics Shape of You`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not GENIUS_ACCESS_TOKEN:
        await update.message.reply_text("Maafi, Genius API key set nahi hai. Kripya bot owner se contact karein.")
        return
        
    try:
        genius = lg.Genius(GENIUS_ACCESS_TOKEN, verbose=False, remove_section_headers=True)
        
        await update.message.reply_text(f"Searching for lyrics for **{query}**...")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        song = genius.search_song(query)

        if song:
            lyrics = song.lyrics
            # Clean up lyrics
            clean_lyrics = re.sub(r'\[.*?\]', '', lyrics) # Remove [Chorus], [Verse], etc.
            clean_lyrics = os.linesep.join([s for s in clean_lyrics.splitlines() if s]) # Remove empty lines
            
            if len(clean_lyrics) > 4000:
                truncated_lyrics = clean_lyrics[:4000] + "...\n\n(Lyrics are too long to display fully.)"
                await update.message.reply_text(f"**{song.title}** by **{song.artist}**\n\n{truncated_lyrics}", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"**{song.title}** by **{song.artist}**\n\n{clean_lyrics}", parse_mode='Markdown')

        else:
            await update.message.reply_text(f"Maafi, `{query}` ke liye koi lyrics nahi mile.", parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text("Lyrics dhoondhne mein koi dikkat aa gayi.")
        logger.error(f"[{chat_id}] Error with Genius API: {e}")
        
# --- MODIFIED: YouTube Download Logic ---
def sync_download_youtube(url: str):
    """Synchronous function to download a YouTube video to a buffer with better size handling."""
    buffer = io.BytesIO()
    try:
        yt = YouTube(url,use_po_token=True)
        # Filter for progressive streams (single file) and set a reasonable size limit
        # Max Telegram upload is 50MB
        MAX_SIZE = 50_000_000 
        
        streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('filesize')

        # Try to find a stream below the max size, prioritizing higher quality
        selected_stream = None
        for stream in reversed(streams):
            if stream.filesize and stream.filesize <= MAX_SIZE:
                selected_stream = stream
                break
        
        if not selected_stream:
            return None, yt.title, "Video is too large to send (> 50MB) or no suitable stream found."

        selected_stream.stream_to_buffer(buffer)
        buffer.seek(0)
        return buffer, yt.title, None

    except Exception as e:
        # Check for specific pytube errors (like age restriction, private)
        error_message = str(e)
        if "age restricted" in error_message.lower():
            return None, "Error", "Video is age-restricted."
        if "private" in error_message.lower():
            return None, "Error", "Video is private."
        return None, "Error", f"An error occurred during download: {e}"

# --- MODIFIED: /youtube Command ---
async def youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Downloads a video from a YouTube link using the command."""
    if not context.args:
        await update.message.reply_text("Please provide a YouTube video link. Example: `/youtube <link>`")
        return
    
    url = context.args[0]
    await handle_youtube_link(update, context, url)


# --- NEW: Core YouTube Handler for both command and auto-detection (FIXED UPDATE.BOT ERROR) ---
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    chat_id = update.effective_chat.id
    
    # Simple URL validation
    if not ("youtube.com" in url.lower() or "youtu.be" in url.lower()):
        # Only reply if it was explicitly called with the command
        if update.message.text and update.message.text.startswith('/youtube'):
            await update.message.reply_text("That doesn't look like a valid YouTube link.")
        return

    # FIX: Changed update.bot to context.bot
    msg = await context.bot.send_message(chat_id=chat_id, text="Request received. Starting download, please wait... 📥")
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")

    try:
        # Use a thread for the blocking operation
        video_buffer, title, error = await asyncio.to_thread(sync_download_youtube, url)
        
        await msg.delete()
        
        if error:
            # FIX: Changed update.bot to context.bot
            await context.bot.send_message(chat_id=chat_id, text=f"Could not download video: {error}")
            logger.warning(f"[{chat_id}] YouTube download failed for '{title}': {error}")
            return

        # Upload message
        caption_text = f"🎥 **{title}**\n\nDownloaded with Laila Bot."
        if len(caption_text) > 1024:
            caption_text = f"🎥 **{title[:50]}...**\n\nDownloaded with Laila Bot."
        
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_buffer,
            caption=caption_text,
            parse_mode='Markdown',
            read_timeout=120, # Increased timeouts for large files
            write_timeout=120
        )
        logger.info(f"[{chat_id}] Successfully sent YouTube video: {title}")

    except Exception as e:
        try:
            await msg.delete()
        except:
            pass # Message might have been deleted already
        # FIX: Changed update.bot to context.bot
        await context.bot.send_message(chat_id=chat_id, text="Sorry, an error occurred while processing the video.")
        logger.error(f"[{chat_id}] Error in YouTube handler: {e}", exc_info=True)
        

# --- Name query handler ---
async def handle_name_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    if user_name:
        response_text = f"Aapka naam **{user_name}** hai. Main tumhe is naam se bula sakti hu. 😊"
    else:
        response_text = "Mujhe abhi tak aapka naam nahi pata. Shayad aapne Telegram par apna naam set nahi kiya hai. 🤔"
    
    await update.message.reply_text(response_text, parse_mode='Markdown')
    logger.info(f"[{chat_id}] Successfully handled name query for user {user_name} ({update.effective_user.id}).")

# --- AI check to see if a message is a name query ---
async def is_name_query_ai(user_message: str) -> bool:
    prompt = f"Given the user message: '{user_message}', is it a question or command where the user is asking for their own name? Answer only 'Yes' or 'No'."
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=10)
        )
        return "yes" in response.text.lower()
    except Exception as e:
        logger.error(f"Error checking if message is a name query: {e}")
        return False

# --- AI check to see if a message is directed at the bot ---
async def is_message_for_laila(user_message: str) -> bool:
    prompt = f"Given the user message: '{user_message}', is it a question or command directed at an AI assistant? Answer only 'Yes' or 'No'."
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=10)
        )
        return "yes" in response.text.lower()
    except Exception as e:
        logger.error(f"Error checking if message is for Laila: {e}")
        return False

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if chat_id > 0: # Private chat
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# --- Admin Commands ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    try:
        target_user = update.message.reply_to_message.from_user
    except AttributeError:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a user's message to ban them.")
        return
    if await is_admin(context.bot, chat_id, target_user.id):
        await context.bot.send_message(chat_id=chat_id, text="I cannot ban another admin.")
        return
    try:
        await context.bot.ban_chat_member(chat_id, target_user.id)
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been banned.")
        logger.info(f"[{chat_id}] {user_id} banned {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not ban user: {e}")
        logger.error(f"[{chat_id}] Error banning user {target_user.id}: {e}")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    try:
        target_user = update.message.reply_to_message.from_user
    except AttributeError:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a user's message to kick them.")
        return
    if await is_admin(context.bot, chat_id, target_user.id):
        await context.bot.send_message(chat_id=chat_id, text="I cannot kick another admin.")
        return
    try:
        await context.bot.unban_chat_member(chat_id, target_user.id, only_if_banned=False)
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been kicked.")
        logger.info(f"[{chat_id}] {user_id} kicked {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not kick user: {e}")
        logger.error(f"[{chat_id}] Error kicking user {target_user.id}: {e}")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    try:
        target_user = update.message.reply_to_message.from_user
    except AttributeError:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a user's message to mute them.")
        return
    if await is_admin(context.bot, chat_id, target_user.id):
        await context.bot.send_message(chat_id=chat_id, text="I cannot mute another admin.")
        return
    try:
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions={'can_send_messages': False})
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been muted.")
        logger.info(f"[{chat_id}] {user_id} muted {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not mute user: {e}")
        logger.error(f"[{chat_id}] Error muting user {target_user.id}: {e}")

# --- ON/OFF for group admins ---
async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    global global_bot_status
    if not global_bot_status:
        await context.bot.send_message(chat_id=chat_id, text="The bot is globally powered off by the owner and cannot be turned on in this group.")
        return
    bot_status[chat_id] = True
    await context.bot.send_message(chat_id=chat_id, text="Laila is now ON for this group.")

async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    bot_status[chat_id] = False
    await context.bot.send_message(chat_id=chat_id, text="Laila is now OFF for this group.")

# --- Reboot command for everyone (same as /on for admins) ---
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    await on_command(update, context)

# --- Translate command for everyone ---
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    target_language = ""
    text_to_translate = ""
    
    if update.message.reply_to_message:
        target_language = " ".join(context.args).strip()
        text_to_translate = update.message.reply_to_message.text
        
        if not target_language:
            await update.message.reply_text("Kripya reply ke saath bhasha ka naam likhein. Jaise: `/tr <bhasha ka naam>`", parse_mode='Markdown')
            return
        if not text_to_translate:
            await update.message.reply_text("Is message mein koi text nahi hai jise translate kiya jaa sake.")
            return
    elif context.args and len(context.args) > 1:
        target_language = context.args[0]
        text_to_translate = " ".join(context.args[1:])
    else:
        await update.message.reply_text("Kripya sahi format use karein: `/tr <bhasha ka naam> <text>` ya kisi message ko reply karke `/tr <bhasha ka naam>` likhein.", parse_mode='Markdown')
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    prompt = f"Translate the following text into {target_language}. Respond with only the translated text, nothing else. Text to translate: '{text_to_translate}'"
    
    try:
        response = await get_bot_response(prompt, chat_id, "", should_use_ai=True, update=update)
        if response and "Maafi, main abhi busy hoon." not in response: # IMPROVED CHECK
            await update.message.reply_text(response)
        else:
            await update.message.reply_text("Translation failed. Please try again.")
    except Exception as e:
        logger.error(f"Error in translate command: {e}")
        await update.message.reply_text("An error occurred during translation. Please try again later.")

# --- Reset command for group admins ---
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        await context.bot.send_message(chat_id=chat_id, text="This command is only for group admins to reset chat history.")
        return
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    if chat_id in chat_histories:
        chat_histories[chat_id].clear()
        await context.bot.send_message(chat_id=chat_id, text="Chat history for this group has been reset. Laila will now start with a fresh memory.")
        logger.info(f"[{chat_id}] Chat history reset by admin {user_id}.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="There is no chat history to reset.")

# --- Get ID command for any user
async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    response_text = (
        f"**Aapki ID**: `{user.id}`\n"
        f"**Chat ki ID**: `{chat.id}`\n"
    )
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        response_text += f"**Reply ki gayi user ki ID**: `{replied_user.id}`"
    await update.message.reply_text(response_text, parse_mode='Markdown')

# --- Owner/Sudo Commands ---
async def poweron_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global global_bot_status
    if global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered on.")
        return
    global_bot_status = True
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered ON. It will now process messages again.")
    logger.info(f"[{update.effective_chat.id}] Global power ON command used by owner.")

async def poweroff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global global_bot_status
    if not global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered OFF.")
        return
    global_bot_status = False
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered OFF. It will no longer process messages.")
    logger.info(f"[{update.effective_chat.id}] Global power OFF command used by owner.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not update.message.reply_to_message:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a message/media to broadcast it to all chats.")
        return
    original_message = update.message.reply_to_message
    broadcast_id = str(uuid.uuid4())[:8]
    broadcast_start_time = datetime.now()
    successful_users = 0
    successful_groups = 0
    total_group_members = 0
    failed_chats = []
    global known_users
    if not known_users:
        load_known_users()
    logger.info(f"Starting broadcast with ID {broadcast_id}...")
    
    # Send initial confirmation message
    await context.bot.send_message(chat_id=chat_id, text=f"Broadcast `{broadcast_id}` started. Broadcasting to `{len(known_users)}` chats. Please wait...")

    for chat_id_str in list(known_users):
        try:
            chat_id_int = int(chat_id_str)
            chat = await context.bot.get_chat(chat_id_int)
            await context.bot.copy_message(
                chat_id=chat_id_int,
                from_chat_id=update.effective_chat.id,
                message_id=original_message.message_id
            )
            if chat.type == 'private':
                successful_users += 1
            else:
                successful_groups += 1
                try:
                    count = await context.bot.get_chat_member_count(chat_id_int)
                    total_group_members += count
                except Exception:
                    pass
            await asyncio.sleep(0.1) # Avoid rate limiting
        except Exception as e:
            failed_chats.append(chat_id_str)
            logger.error(f"Error broadcasting message to chat {chat_id_str}: {e}")
    broadcast_end_time = datetime.now()
    duration = broadcast_end_time - broadcast_start_time
    receipt_message = (
        f"**Broadcast Receipt** ✨\n\n"
        f"**Broadcast ID**: `{broadcast_id}`\n"
        f"**Started At**: `{broadcast_start_time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"**Duration**: `{duration.seconds}s`\n\n"
        f"**Summary**\n"
        f"✅ Successful to `{successful_users}` private chats.\n"
        f"✅ Successful to `{successful_groups}` groups.\n"
        f"👥 Total estimated reach (group members + users): `{successful_users + total_group_members}`\n"
        f"❌ Failed for `{len(failed_chats)}` chats.\n\n"
    )
    if failed_chats:
        failed_chats_str = ", ".join(failed_chats)
        receipt_message += f"**Failed Chat IDs**:\n`{failed_chats_str}`"
    await context.bot.send_message(chat_id=chat_id, text=receipt_message, parse_mode='Markdown')
    logger.info(f"Broadcast {broadcast_id} finished. Receipt sent to admin.")

# --- NEW: Sudo commands for model switching ---
async def force_gemma_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forces the bot to use only the Gemma model."""
    global current_model_mode
    current_model_mode = 'gemma_only'
    await update.message.reply_text("🤖 Model mode has been **forced to Gemma-only**.\nAll AI responses will now use Gemma until switched back.", parse_mode='Markdown')
    logger.info(f"Model mode forced to Gemma-only by sudo user {update.effective_user.id}.")

async def force_dynamic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switches the bot back to dynamic model selection."""
    global current_model_mode
    current_model_mode = 'dynamic'
    await update.message.reply_text("🤖 Model mode has been reset to **Dynamic**.\nThe bot will now prioritize Gemini and use Gemma as a fallback.", parse_mode='Markdown')
    logger.info(f"Model mode set to dynamic by sudo user {update.effective_user.id}.")


# --- General User Commands ---
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo_file_id = update.message.reply_to_message.photo[-1].file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Photo File ID:\n`{photo_file_id}`", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Please reply to a photo with this command to get its ID.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
    
    add_to_group_url = f"https://tme/{(await context.bot.get_me()).username}?startgroup=true"
    
    keyboard = [[InlineKeyboardButton("➕ Add Me To Your Group ➕", url=add_to_group_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        f"Hey there! 😉\n\n"
        f"I'm Laila, your friendly AI assistant. 🤖\n"
        f"I'm here to chat, answer your questions, and help you with anything you need. 😘\n\n"
        f"You can use `/help` to see all the commands.\n"
        f"Let's get started, `{user_name}`! 💖"
    )
    photo_file_id = 'AgACAgUAAxkBAAIIKGigVdAK07aRr9QiXpRalahcPO2pAAIL0DEblXUBVSY5LS31XxPSAQADAgADeAADNgQ'
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=welcome_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"[{chat_id}] Sent /start with photo and button to {user_name}")
    except Exception as e:
        logger.error(f"Failed to send photo with start command: {e}")
        await context.bot.send_message(chat_id=chat_id, text=welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    ping_start = time.time()
    msg = await context.bot.send_message(chat_id=chat_id, text="Calculating stats...")
    ping_end = time.time()
    
    uptime = datetime.now() - start_time
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{uptime.days}d {hours}h {minutes}m {seconds}s"
    ram_usage = psutil.virtual_memory().percent
    cpu_usage = psutil.cpu_percent(interval=1)
    disk_usage = psutil.disk_usage('/').percent
    response_text = (
        "❤️ **Laila's Live Stats** ❤️\n\n"
        f"⚡️ **Ping**: `{int((ping_end - ping_start) * 1000)}ms`\n"
        f"⏳ **Uptime**: `{uptime_str}`\n"
        f"🧠 **RAM**: `{ram_usage}%`\n"
        f"💻 **CPU**: `{cpu_usage}%`\n"
        f"💾 **Disk**: `{disk_usage}%`\n\n"
        "✨ by Adhyan ✨"
    )
    
    await msg.delete() # Delete "Calculating stats..." message
    photo_file_id = 'AgACAgUAAxkBAAIIKGigVdAK07aRr9QiXpRalahcPO2pAAIL0DEblXUBVSY5LS31XxPSAQADAgADeAADNgQ'
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=response_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send photo with stats command: {e}")
        await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='Markdown')

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows detailed bot stats for the admin only."""
    chat_id = update.effective_chat.id
    ping_start = time.time()
    msg = await context.bot.send_message(chat_id=chat_id, text="Calculating admin stats...")
    ping_end = time.time()
    
    uptime = datetime.now() - start_time
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{uptime.days}d {hours}h {minutes}m {seconds}s"
    ram_usage = psutil.virtual_memory().percent
    cpu_usage = psutil.cpu_percent(interval=1)
    disk_usage = psutil.disk_usage('/').percent
    
    bot_connection_status = "✅ Connected"
    try:
        await context.bot.get_me()
    except Exception:
        bot_connection_status = "❌ Failed"
    
    sheets_connection_status = "✅ Connected"
    try:
        client, error_msg = get_google_sheet_connection()
        if not client:
            raise Exception(error_msg)
    except Exception as e:
        sheets_connection_status = f"❌ Failed: {e}"
        
    env_vars_status = "✅ All set"
    if not all([TELEGRAM_BOT_TOKEN, any(GEMINI_API_KEYS), BROADCAST_ADMIN_ID]):
        env_vars_status = "⚠️ Missing key variables"
        
    render_status = "✅ Active" if os.getenv("RENDER") else "⚠️ Local/Unknown"
    
    api_key_status_text = ""
    for i, key in enumerate(GEMINI_API_KEYS):
        if key:
            key_short = key[-5:]
            status = "🟢 Available"
            if time.time() < key_cooldown_until.get(key, 0):
                cooldown_remaining = int(key_cooldown_until[key] - time.time())
                status = f"🟡 Cooldown ({cooldown_remaining}s)"
            api_key_status_text += f"Gemini Key {i+1} (`...{key_short}`): {status}\n"
        else:
            api_key_status_text += f"Gemini Key {i+1}: ❌ Missing\n"
    
    api_key_status_text += f"\nGemma Key: {'✅ Present' if GEMMA_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nStable Horde Key: {'✅ Present' if STABLE_HORDE_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nPexels Key: {'✅ Present' if PEXELS_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nGenius Key: {'✅ Present' if GENIUS_ACCESS_TOKEN else '❌ Missing'}"
    # ADDED: YouTube API Key Status
    api_key_status_text += f"\nYouTube Key: {'✅ Present' if YOUTUBE_API_KEY else '⚠️ Missing (Not required by pytube)'}"

    response_text = (
        "👑 **Laila's Admin Report** 👑\n\n"
        "**System Health**\n"
        f" Ping: `{int((ping_end - ping_start) * 1000)}ms`\n"
        f" Uptime: `{uptime_str}`\n"
        f" RAM: `{ram_usage}%`\n"
        f" CPU: `{cpu_usage}%`\n"
        f" Disk: `{disk_usage}%`\n\n"
        "**Service Status**\n"
        f" Bot Connection: `{bot_connection_status}`\n"
        f" Google Sheets: `{sheets_connection_status}`\n"
        f" Environment Variables: `{env_vars_status}`\n"
        f" Deployment: `{render_status}`\n\n"
        "**Bot Stats**\n"
        f" Total Chats: `{len(known_users)}`\n"
        f" Sudo Users: `{len(sudo_users)}`\n"
        f" Total Messages: `{total_messages_processed}`\n"
        f" AI Model Mode: `{current_model_mode.capitalize()}`\n\n"
        "**API Status**\n"
        f"{api_key_status_text}"
        "\n\n✨ by Adhyan ✨"
    )
    await msg.delete()
    await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='Markdown')
    logger.info(f"[{chat_id}] /adminstats command used by admin.")

async def show_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    global known_users
    if not known_users:
        load_known_users()
    
    known_chats = list(known_users)
    if not known_chats:
        await context.bot.send_message(chat_id=chat_id, text="The bot is not in any groups or private chats yet.")
        return

    msg = await context.bot.send_message(chat_id=user_id, text=f"Fetching details for `{len(known_chats)}` chats. This might take a moment...", parse_mode='Markdown')

    chat_details = []
    for i, chat_id_str in enumerate(known_chats):
        try:
            chat = await context.bot.get_chat(chat_id_str)
            if chat.type == 'private':
                chat_details.append(f"• **User**: `{chat.full_name}` (ID: `{chat_id_str}`)")
            else:
                members_count = "N/A"
                try:
                    members_count = await context.bot.get_chat_member_count(chat_id_str)
                except Exception: pass
                
                invite_link = ""
                try:
                    if chat.username:
                        invite_link = f"https://t.me/{chat.username}"
                    else:
                        invite = await context.bot.create_chat_invite_link(chat_id_str, member_limit=1)
                        invite_link = invite.invite_link
                except Exception:
                    invite_link = "*No permission to get link.*"

                chat_details.append(
                    f"• **Group**: `{chat.title}` (ID: `{chat_id_str}`)\n"
                    f"  Members: `{members_count}`\n"
                    f"  Link: {invite_link}"
                )
            await asyncio.sleep(0.2) # Avoid hitting API limits
        except Exception:
            chat_details.append(f"• **Unknown Chat**: ID: `{chat_id_str}` (Bot may have been removed)")
        
        # Edit message every 10 chats to show progress
        if (i + 1) % 10 == 0:
            await msg.edit_text(f"Fetching details... Processed `{(i+1)}/{len(known_chats)}` chats.", parse_mode='Markdown')

    response_text = "✨ **Laila's Chats** ✨\n\n" + "\n\n".join(chat_details)
    
    # Send final result
    await msg.edit_text(response_text, parse_mode='Markdown', disable_web_page_preview=True)
    
    if chat_id != user_id:
        await context.bot.send_message(chat_id, text="The list of chats has been sent to you privately.")
    
    logger.info(f"[{chat_id}] /show_chats command used by admin. Response sent privately to {user_id}.")

# --- Message Processing Logic ---
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global total_messages_processed
    global_bot_enabled = global_bot_status
    chat_id = update.effective_chat.id
    chat_enabled = bot_status[chat_id]
    is_private_chat = update.effective_chat.type == 'private'
    
    if update.message and update.message.text and update.message.text.startswith('/'):
        # Check for auto-download right before returning for command
        if ("youtube.com" in update.message.text or "youtu.be" in update.message.text) and not update.message.text.startswith('/youtube'):
            threading.Thread(target=lambda: asyncio.run(handle_youtube_link(update, context, update.message.text)), daemon=True).start()
        return
    
    if not global_bot_enabled or (not is_private_chat and not chat_enabled):
        return
    
    bot_username = (await context.bot.get_me()).username
    user_message = update.message.text or update.message.caption
    user_id = update.effective_user.id
    user_full_name = update.effective_user.full_name
    
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
    
    # --- Couple command user tracking ---
    if not is_private_chat:
        chat_members[chat_id][user_id] = user_full_name

    if not user_message:
        return
    
    # --- NEW: Automatic YouTube link detection in regular text ---
    youtube_pattern = r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+)'
    youtube_match = re.search(youtube_pattern, user_message)
    if youtube_match:
        url = youtube_match.group(0)
        # Run in a new thread to prevent blocking
        threading.Thread(target=lambda: asyncio.run(handle_youtube_link(update, context, url)), daemon=True).start()
        # Continue to AI response only if the message is NOT just the link
        if user_message.strip() == url.strip():
            return
    
    if await is_name_query_ai(user_message):
        await handle_name_query(update, context)
        return
        
    is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = f"@{bot_username.lower()}" in user_message.lower() or "laila" in user_message.lower()
    
    should_use_ai = is_private_chat or is_reply_to_bot or is_mention
    if not should_use_ai:
        if await is_message_for_laila(user_message):
            should_use_ai = True
        else:
            return
            
    if should_use_ai:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            response_text = await get_bot_response(user_message, chat_id, bot_username, should_use_ai=True, update=update)
            if response_text:
                await update.message.reply_text(response_text, parse_mode='Markdown')
                add_to_history(chat_id, 'user', user_message)
                add_to_history(chat_id, 'model', response_text)
                total_messages_processed += 1
                logger.info(f"[{chat_id}] Sent response to {user_id}: {response_text[:50]}...")
        except Exception as e:
            logger.error(f"Error processing message for chat {chat_id}: {e}", exc_info=True)
            try:
                await update.message.reply_text("An unexpected error occurred. Please try again later.")
            except Exception as reply_e:
                logger.error(f"Failed to send error reply: {reply_e}")

# --- NEW: Speech-to-Text Handler ---
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles voice messages by converting them to text and processing them."""
    chat_id = update.effective_chat.id
    file_id = update.message.voice.file_id
    
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        # 1. Download the voice file
        voice_file = await context.bot.get_file(file_id)
        ogg_path = f"{file_id}.ogg"
        # Download needs to be awaited
        await voice_file.download_to_drive(ogg_path)

        # 2. Convert OGG to WAV
        wav_path = f"{file_id}.wav"
        # Blocking operation, run in thread
        audio = await asyncio.to_thread(AudioSegment.from_ogg, ogg_path)
        await asyncio.to_thread(audio.export, wav_path, format="wav")

        # 3. Transcribe WAV to text
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            # Blocking operation, run in thread
            audio_data = await asyncio.to_thread(recognizer.record, source)
        
        # Blocking operation, run in thread
        transcribed_text = await asyncio.to_thread(recognizer.recognize_google, audio_data)
        logger.info(f"[{chat_id}] Transcribed voice message: '{transcribed_text}'")

        # 4. Process the transcribed text like a regular message
        if transcribed_text:
            bot_username = (await context.bot.get_me()).username
            # We treat voice messages as direct mentions to the bot
            response_text = await get_bot_response(transcribed_text, chat_id, bot_username, should_use_ai=True, update=update)
            if response_text:
                await update.message.reply_text(response_text, parse_mode='Markdown')
                add_to_history(chat_id, 'user', transcribed_text)
                add_to_history(chat_id, 'model', response_text)

    except sr.UnknownValueError:
        await update.message.reply_text("Sorry, I couldn't understand the audio. 😕")
    except sr.RequestError as e:
        await update.message.reply_text("Sorry, my speech recognition service is down. Please try again later.")
        logger.error(f"Speech recognition request error: {e}")
    except FileNotFoundError:
        # This error happens if ffmpeg is not installed
        await update.message.reply_text("Sorry, I can't process voice messages right now. The `ffmpeg` tool might be missing on the server.")
        logger.error("ffmpeg not found. Please install it to enable voice message processing.")
    except Exception as e:
        await update.message.reply_text("An error occurred while processing your voice message.")
        logger.error(f"Error processing voice message: {e}", exc_info=True)
    finally:
        # 5. Clean up temporary files (Blocking operations, run in thread)
        def cleanup(ogg, wav):
            if os.path.exists(ogg): os.remove(ogg)
            if os.path.exists(wav): os.remove(wav)

        if 'ogg_path' in locals() and 'wav_path' in locals():
            await asyncio.to_thread(cleanup, ogg_path, wav_path)

# --- HELP Command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "❤️ **Laila Bot Commands** ❤️\n\n"
        "✨ **General Commands**\n"
        "`/start` - Laila se baat karne ke liye start karein.\n"
        "`/help` - Sabhi commands aur unke baare mein jaankari.\n"
        "`/about` - Laila ke baare mein jaaniye.\n"
        "`/stats` - Bot ka live performance dekhein.\n"
        "`/id` - Apni aur chat ki ID dekhein.\n"
        "`/tr` - **Text ko translate karein.** `/tr <bhasha> <text>` ya reply karke `/tr <bhasha>`.\n"
        "`/gen` - **Text se AI image banayein.** Jaise: `/gen a cat with wings`.\n"
        "`/img` - **Photo search karein.** Jaise: `/img sunset on the beach`.\n"
        "`/lyrics` - **Gaane ke lyrics dhoondein.** Jaise: `/lyrics Shape of You`.\n"
        "`/couple` - **Group me se random couple chune.**\n"
        "`/youtube` - **YouTube video download karein.** Jaise: `/youtube <link>`.\n"
        "*Tip: Aap seedha YouTube link bhejo, Laila khud download kar legi!* 😉\n\n" # ADDED TIP
        "🔒 **Admin Commands (For Group Admins)**\n"
        "`/on` - Laila ko group mein on karein.\n"
        "`/off` - Laila ko group mein off karein.\n"
        "`/reboot` - Bot ko group ke liye firse chalu karein.\n"
        "`/reset` - Chat history clear karein.\n"
        "`/ban` - Kisi user ko ban karein (Reply karein).\n"
        "`/kick` - Kisi user ko kick karein (Reply karein).\n"
        "`/mute` - Kisi user ko mute karein (Reply karein).\n\n"
        "✨ by Adhyan ✨"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /help command used.")

# --- ABOUT Command ---
async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = (
        "❤️ **About Laila** ❤️\n\n"
        "I am Laila, an AI assistant created by AdhyanXlive. My purpose is to chat with you and provide answers to your questions.\n\n"
        "My intelligence comes from a family of large language models, allowing me to provide helpful and accurate responses.\n\n"
        "✨ **Creator**: Adhyan\n"
        "✨ **Version**: 1.3 (Updated with improved YouTube download and Gemma fallback)\n\n" # Version updated
    )
    await update.message.reply_text(about_text, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /about command used.")

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the admin."""
    logger.error("An error occurred:", exc_info=context.error)
    
    if BROADCAST_ADMIN_ID:
        try:
            error_message = f"An error occurred in the bot:\n\n`{traceback.format_exc()}`"
            # Trim message if too long
            if len(error_message) > 4096:
                error_message = error_message[:4000] + "\n\n... (message truncated)"
            await context.bot.send_message(
                chat_id=BROADCAST_ADMIN_ID,
                text=error_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send error notification to admin: {e}")

# --- Sudo Commands ---
async def add_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, this command is for the bot owner only.")
        return
    if not context.args or not context.args[0].isdigit():
        await context.bot.send_message(chat_id=chat_id, text="Please provide a valid user ID. Usage: `/addsudo <user_id>`")
        return
    target_user_id = context.args[0]
    if target_user_id in sudo_users:
        await context.bot.send_message(chat_id=chat_id, text=f"User `{target_user_id}` is already a sudo user.")
        return
    sudo_users.add(target_user_id)
    save_sudo_users()
    await context.bot.send_message(chat_id=chat_id, text=f"User `{target_user_id}` has been added as a sudo user.")
    logger.info(f"[{chat_id}] Admin {user_id} added sudo user {target_user_id}")
    
async def remove_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, this command is for the bot owner only.")
        return
    if not context.args or not context.args[0].isdigit():
        await context.bot.send_message(chat_id=chat_id, text="Please provide a valid user ID. Usage: `/removesudo <user_id>`")
        return
    target_user_id = context.args[0]
    if target_user_id not in sudo_users:
        await context.bot.send_message(chat_id=chat_id, text=f"User `{target_user_id}` is not a sudo user.")
        return
    sudo_users.remove(target_user_id)
    save_sudo_users()
    await context.bot.send_message(chat_id=chat_id, text=f"User `{target_user_id}` has been removed as a sudo user.")
    logger.info(f"[{chat_id}] Admin {user_id} removed sudo user {target_user_id}")

# --- Check for sudo status ---
def check_sudo_wrapper(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        if user_id == str(BROADCAST_ADMIN_ID) or user_id in sudo_users:
            await handler(update, context)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is restricted to sudo users only.")
            logger.warning(f"Unauthorized access to restricted command by user {user_id} in chat {update.effective_chat.id}")
    return wrapper

# --- Main function ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    load_known_users()
    load_sudo_users()
    
    # Regular Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("id", get_id_command))
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("gen", gen_command))
    application.add_handler(CommandHandler("img", img_command))
    application.add_handler(CommandHandler("lyrics", lyrics_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("youtube", youtube_command)) # MODIFIED to be command-based

    
    # Admin Commands
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("reboot", reboot_command))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("mute", mute_user))
    
    # Sudo-Only Commands
    application.add_handler(CommandHandler("poweron", check_sudo_wrapper(poweron_command)))
    application.add_handler(CommandHandler("poweroff", check_sudo_wrapper(poweroff_command)))
    application.add_handler(CommandHandler("broadcast", check_sudo_wrapper(broadcast_command)))
    application.add_handler(CommandHandler("get_photo_id", check_sudo_wrapper(get_photo_id)))
    application.add_handler(CommandHandler("adminstats", check_sudo_wrapper(admin_stats_command)))
    application.add_handler(CommandHandler("show_chats", check_sudo_wrapper(show_chats_command)))
    application.add_handler(CommandHandler("forcegemma", check_sudo_wrapper(force_gemma_command))) # NEW
    application.add_handler(CommandHandler("forcedynamic", check_sudo_wrapper(force_dynamic_command))) # NEW
    
    # Owner-Only Sudo Management Commands
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("removesudo", remove_sudo_command))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, process_message))
    # ADDED: New handler for voice messages
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    
    application.add_error_handler(error_handler)
    
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8000"))
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        )
        logger.info(f"Bot started with webhook on port {PORT}")
    else:
        logger.info("Starting bot in polling mode.")
        application.run_polling()

if __name__ == '__main__':
    main()
