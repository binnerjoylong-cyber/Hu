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
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from dotenv import load_dotenv
import time
import lyricsgenius as lg
import sqlite3

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

# --- Global Stats Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()

# --- Sudo User Management ---
sudo_users = set()
SUDO_SHEET_TITLE = "sudo_users"
CHATS_SHEET_TITLE = "chats"
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
current_api_key_index = 0
active_api_key = GEMINI_API_KEYS[current_api_key_index]
key_cooldown_until = defaultdict(lambda: 0)
genai.configure(api_key=active_api_key)
model_name = 'gemini-2.5-flash-lite'
model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)

# --- Fallback Responses (Static Memory) ---
fallback_responses = {
    "hello": "Hello! Laila is here. How are you?",
    "hi": "Hi there! Laila is ready to help you.",
    "how are you": "I'm doing great! Just ready to assist you with anything you need.",
    "who are you": "I am Laila, your friendly AI assistant! You can ask me anything you want.",
}

# --- In-memory store for recent messages to select couples ---
recent_users = defaultdict(list)
MAX_RECENT_USERS = 50
COUPLE_PHOTO_ID = "AgACAgUAAxkBAAId5GjLxQv_BxOm3_RGmB9j4WceUFg7AALdyzEb-tJgVuOn7v3_BWvqAQADAgADeQADNgQ"

# --- Google Sheets Global Connection Variable ---
google_sheet = None
sudo_sheet = None
sheets_client = None
couple_sheet = None

# --- SQLite Database Setup ---
conn = None
def setup_database():
    global conn
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT,
                joined_date TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS group_members (
                member_id INTEGER,
                group_id INTEGER,
                full_name TEXT,
                username TEXT,
                is_bot INTEGER,
                last_active TEXT,
                PRIMARY KEY (member_id, group_id)
            )
        ''')
        conn.commit()
        logger.info("Successfully connected to SQLite database.")
    except Exception as e:
        logger.error(f"Error setting up SQLite database: {e}")
        conn = None

def get_db_connection():
    if not conn:
        setup_database()
    return conn

# --- Database Functions for Group and Members ---
def get_group_members_from_db(group_id):
    conn = get_db_connection()
    if not conn: return []
    c = conn.cursor()
    c.execute("SELECT member_id, full_name, username, is_bot FROM group_members WHERE group_id = ?", (group_id,))
    members = c.fetchall()
    member_objects = []
    for member in members:
        member_objects.append({
            'id': member[0],
            'full_name': member[1],
            'username': member[2],
            'is_bot': bool(member[3])
        })
    return member_objects

def add_member_to_db(group_id, user):
    conn = get_db_connection()
    if not conn: return
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO group_members (member_id, group_id, full_name, username, is_bot, last_active)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user.id, group_id, user.full_name, user.username, user.is_bot, datetime.now().isoformat()))
    conn.commit()
    
def remove_member_from_db(group_id, user_id):
    conn = get_db_connection()
    if not conn: return
    c = conn.cursor()
    c.execute("DELETE FROM group_members WHERE group_id = ? AND member_id = ?", (group_id, user_id))
    conn.commit()

# --- Connect to Google Sheets ---
def setup_google_sheets():
    """Initializes the Google Sheets client and worksheets."""
    global sheets_client, google_sheet, sudo_sheet, couple_sheet
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        logger.error("GOOGLE_SHEETS_CREDENTIALS not found in environment variables. Google Sheets will not work.")
        return False
    try:
        creds_dict = json.loads(creds_json)
        sheets_client = gspread.service_account_from_dict(creds_dict)
        spreadsheet = sheets_client.open_by_url(SUDO_SHEET_URL)
        
        try:
            google_sheet = spreadsheet.worksheet(CHATS_SHEET_TITLE)
        except WorksheetNotFound:
            google_sheet = spreadsheet.add_worksheet(CHATS_SHEET_TITLE, rows="1000", cols="2")
            google_sheet.append_row(["ChatID", "JoinedDate"])
        
        try:
            sudo_sheet = spreadsheet.worksheet(SUDO_SHEET_TITLE)
        except WorksheetNotFound:
            sudo_sheet = spreadsheet.add_worksheet(SUDO_SHEET_TITLE, rows="100", cols="1")
            sudo_sheet.append_row(["SudoUserID"])
            
        try:
            couple_sheet = spreadsheet.worksheet("couple_members")
        except WorksheetNotFound:
            couple_sheet = spreadsheet.add_worksheet("couple_members", rows="10000", cols="4")
            couple_sheet.append_row(["ChatID", "UserID", "FullName", "IsBot"])
        
        logger.info("Successfully connected to Google Sheets and worksheets.")
        return True
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return False

# --- Function to clean message before logging ---
def clean_message_for_logging(message: str, bot_username: str) -> str:
    cleaned_message = message.lower()
    cleaned_message = cleaned_message.replace(f"@{bot_username.lower()}", "")
    cleaned_message = re.sub(r'laila\s*(ko|ka|se|ne|)\s*', '', cleaned_message, flags=re.IGNORECASE)
    cleaned_message = re.sub(r'\s+', ' ', cleaned_message).strip()
    return cleaned_message

# --- Function to save a chat ID to Google Sheets ---
def save_chat_id(chat_id):
    if not google_sheet:
        logger.error("Google Sheets not initialized. Cannot save chat ID.")
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
    if not google_sheet:
        logger.error("Google Sheets not initialized. Cannot load known users.")
        return
    try:
        chat_ids = google_sheet.col_values(1)[1:]
        known_users = set(chat_ids)
        logger.info(f"Loaded {len(known_users)} chats from Google Sheets.")
    except Exception as e:
        logger.error(f"Error loading known users from Google Sheet: {e}")

# --- Function to load sudo users from Google Sheets ---
def load_sudo_users():
    global sudo_users
    if not sudo_sheet:
        logger.error("Google Sheets not initialized. Cannot load sudo users.")
        return
    try:
        sudo_user_ids = sudo_sheet.col_values(1)[1:]
        sudo_users = {user_id for user_id in sudo_user_ids if user_id.isdigit()}
        logger.info(f"Loaded {len(sudo_users)} sudo users from Google Sheets.")
    except Exception as e:
        logger.error(f"Error loading sudo users from Google Sheet: {e}")
        
# --- Function to save sudo users to Google Sheets ---
def save_sudo_users():
    if not sudo_sheet:
        logger.error("Google Sheets not initialized. Cannot save sudo users.")
        return
    try:
        # Clear existing data except header
        sudo_sheet.resize(rows=1)
        sudo_sheet.resize(rows=len(sudo_users) + 1)
        sudo_sheet.update('A2', [[user_id] for user_id in sorted(list(sudo_users))])
        logger.info(f"Saved {len(sudo_users)} sudo users to Google Sheets.")
    except Exception as e:
        logger.error(f"Error saving sudo users to Google Sheet: {e}")
        
# --- Google Sheets Functions for Couple Command ---
def add_member_to_sheet(chat_id, user):
    if not couple_sheet: return
    try:
        # Check if the member already exists for this chat
        rows = couple_sheet.get_all_values()
        for row_index, row in enumerate(rows):
            if row[0] == str(chat_id) and row[1] == str(user.id):
                # Update existing row
                couple_sheet.update(f'A{row_index+1}:D{row_index+1}', [[str(chat_id), str(user.id), user.full_name, int(user.is_bot)]])
                return
        # If not found, append a new row
        couple_sheet.append_row([str(chat_id), str(user.id), user.full_name, int(user.is_bot)])
    except Exception as e:
        logger.error(f"Error adding member {user.id} to couple sheet: {e}")
        
def get_members_from_sheet(chat_id):
    if not couple_sheet: return []
    try:
        data = couple_sheet.get_all_values()
        members = []
        for row in data:
            if row[0] == str(chat_id) and row[3] == '0':
                members.append({
                    'id': int(row[1]),
                    'full_name': row[2]
                })
        return members
    except Exception as e:
        logger.error(f"Error getting members for chat {chat_id} from couple sheet: {e}")
        return []

def remove_member_from_sheet(chat_id, user_id):
    if not couple_sheet: return
    try:
        rows = couple_sheet.get_all_values()
        for row_index, row in enumerate(rows):
            if row[0] == str(chat_id) and row[1] == str(user_id):
                couple_sheet.delete_rows(row_index + 1)
                return
    except Exception as e:
        logger.error(f"Error removing member {user_id} from couple sheet: {e}")

# --- AI Response Function with Fallback to Google Sheets and Gemma ---
async def get_bot_response(user_message: str, chat_id: int, bot_username: str, should_use_ai: bool, update: Update) -> str:
    global current_api_key_index, active_api_key, model
    user_message_lower = user_message.lower()
    
    # --- Handle Date/Time Queries
    kolkata_tz = pytz.timezone('Asia/Kolkata')
    date_time_patterns = [
        r'time kya hai', r'what is the time', r'samay kya hai', r'kitne baje hain',
        r'aaj ki date kya hai', r'aaj kya tarikh hai', r'what is the date',
        r'laila abhi ka time batao', r'laila abhi ka time batao'
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
    if should_use_ai or (update.effective_chat and update.effective_chat.type == 'private'):
        max_retries = len(GEMINI_API_KEYS)
        retries = 0
        while retries < max_retries:
            if time.time() < key_cooldown_until[active_api_key]:
                current_api_key_index = (current_api_key_index + 1) % len(GEMINI_API_KEYS)
                active_api_key = GEMINI_API_KEYS[current_api_key_index]
                retries += 1
                genai.configure(api_key=active_api_key)
                model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)
                continue
            try:
                genai.configure(api_key=active_api_key)
                model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)
                
                user_first_name = update.effective_user.first_name
                user_username = update.effective_user.username
                user_id = update.effective_user.id
                
                confidence_score = 0
                
                if user_first_name and len(user_first_name) > 1:
                    confidence_score += 0.3
                if user_first_name and user_first_name.lower() in user_message_lower:
                    confidence_score += 0.2
                
                if user_username and f"@{user_username.lower()}" in user_message_lower:
                    confidence_score += 0.2
                
                if update.message.reply_to_message and update.message.reply_to_message.from_user.id == user_id:
                    confidence_score += 0.1
                
                user_name_confidence = defaultdict(lambda: {'score': 0, 'last_seen': 0})
                if user_id in user_name_confidence and (time.time() - user_name_confidence[user_id]['last_seen']) < 3600:
                    confidence_score += user_name_confidence[user_id]['score'] * 0.2
                
                should_use_name = confidence_score >= 0.7
                
                user_name_confidence[user_id]['score'] = confidence_score
                user_name_confidence[user_id]['last_seen'] = time.time()
                
                if should_use_name:
                    full_prompt = f"The user's name is '{user_first_name}'. Please use their name in your reply to make it personal. User says: {user_message}"
                else:
                    full_prompt = f"User says: {user_message}"
                
                chat_session = model.start_chat(history=chat_histories[chat_id])
                is_detailed_query = len(user_message.split()) > 5 or '?' in user_message or 'how to' in user_message_lower
                response = chat_session.send_message(
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=350 if is_detailed_query else 100,
                        temperature=0.7,
                    )
                )
                ai_text_response = response.text
                return ai_text_response
            except genai.types.BlockedPromptException as e:
                logger.warning(f"[{chat_id}] Gemini blocked prompt: {e}")
                return "Apologies, I can't discuss that topic."
            except Exception as e:
                error_str = str(e)
                if "429 Quota exceeded" in error_str or "You exceeded your current quota" in error_str or "500" in error_str:
                    logger.warning(f"[{chat_id}] API key {active_api_key[-5:]} failed with retryable error: {e}. Shifting to next key.")
                    key_cooldown_until[active_api_key] = time.time() + (1 * 60 * 60)
                    current_api_key_index = (current_api_key_index + 1) % len(GEMINI_API_KEYS)
                    active_api_key = GEMINI_API_KEYS[current_api_key_index]
                    retries += 1
                    continue
                else:
                    logger.error(f"[{chat_id}] General, non-retryable error with API key {active_api_key[-5:]}: {e}", exc_info=True)
                    break
        if GEMMA_API_KEY:
            try:
                genai.configure(api_key=GEMMA_API_KEY)
                gemma_model = genai.GenerativeModel('gemma-7b-it', system_instruction=LAILA_SYSTEM_PROMPT)
                gemma_response = gemma_model.generate_content(user_message)
                ai_text_response = gemma_response.text
                logger.info(f"[{chat_id}] All Gemini keys failed. Successfully used dedicated Gemma key.")
                return ai_text_response
            except Exception as e:
                logger.error(f"[{chat_id}] Gemma model with dedicated key also failed: {e}", exc_info=True)
                return "Apologies, I'm currently offline. Please try again later."
        else:
            logger.critical(f"[{chat_id}] All Gemini keys and Gemma key are missing or failed.")
            return "Apologies, I'm currently offline. Please try again later."
    return None

# --- Image Generation Command (renamed to /gen) ---
async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates an image using Stable Horde API."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Kripya image generate karne ke liye kuch likhein. Jaise: `/gen a black cat in space`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not STABLE_HORDE_API_KEY:
        await update.message.reply_text("Maafi, image generator API key set nahi hai. Kripya bot owner se contact karein.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        headers = {
            "apikey": STABLE_HORDE_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": query,
            "params": {
                "n": 1,
                "width": 512,
                "height": 512,
                "cfg_scale": 10,
                "steps": 30
            },
            "negative_prompt": "blurry, low quality, bad anatomy, deformed, worst quality, text, watermark"
        }
        
        response = requests.post("https://stablehorde.net/api/v2/generate/async", headers=headers, json=payload)
        response.raise_for_status()
        
        generation_id = response.json()["id"]

        await update.message.reply_text("Image generate ho rahi hai. Kripya thoda intezaar karein...")
        while True:
            await asyncio.sleep(5)
            check_response = requests.get(f"https://stablehorde.net/api/v2/generate/check/{generation_id}")
            check_response.raise_for_status()
            
            if check_response.json()["done"]:
                break
        
        result_response = requests.get(f"https://stablehorde.net/api/v2/generate/status/{generation_id}")
        result_response.raise_for_status()
        
        image_url = result_response.json()["generations"][0]["img"]

        if image_url:
            await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=f"Yahan aapki image hai: **{query}**")
            logger.info(f"[{chat_id}] Generated and sent image for query: {query}")
        else:
            await update.message.reply_text("Maafi, image generate nahi ho paayi.")
            logger.warning(f"[{chat_id}] Failed to generate image for query: {query}")

    except Exception as e:
        await update.message.reply_text("Image generate karne mein koi dikkat aa gayi.")
        logger.error(f"[{chat_id}] Error with Stable Horde API: {e}")

# --- Image Retrieval Command (/img) ---
async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieves an image from Pexels API."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Kripya search karne ke liye kuch likhein. Jaise: `/img mountains`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not PEXELS_API_KEY:
        await update.message.reply_text("Maafi, Pexels API key set nahi hai. Kripya bot owner se contact karein.")
        return
        
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        headers = {
            "Authorization": PEXELS_API_KEY
        }
        params = {
            "query": query,
            "per_page": 10,
            "orientation": "landscape"
        }
        
        response = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
        response.raise_for_status()
        
        photos = response.json().get("photos", [])

        if photos:
            photo_url = random.choice(photos)["src"]["medium"]
            await context.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=f"Yahan aapki photo hai: **{query}**")
            logger.info(f"[{chat_id}] Retrieved and sent image for query: {query}")
        else:
            await update.message.reply_text("Maafi, is search ke liye koi photo nahi mili.")
            logger.warning(f"[{chat_id}] Pexels search failed for query: {query}")

    except Exception as e:
        await update.message.reply_text("Photo search karne mein koi dikkat aa gayi.")
        logger.error(f"[{chat_id}] Error with Pexels API: {e}")

# <--- Lyrics Command (/lyrics) --->
async def lyrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches and displays lyrics from Genius API."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Kripya song ka naam likhein. Jaise: `/lyrics Shape of You`", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not GENIUS_ACCESS_TOKEN:
        await update.message.reply_text("Maafi, Genius API key set nahi hai. Kripya bot owner se contact karein.")
        return
        
    try:
        # Initialize Genius client without the 'headers' argument
        genius = lg.Genius(GENIUS_ACCESS_TOKEN, verbose=False, timeout=15, retries=3)
        
        # Define a header to mimic a web browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        
        # Search for the song, passing the custom headers to the search method
        await update.message.reply_text(f"Searching for lyrics for **{query}**...")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        song = genius.search_song(query, _client_headers=headers)

        if song:
            lyrics = song.lyrics
            lyrics_lines = lyrics.split('\n')
            if lyrics_lines and 'Lyrics' in lyrics_lines[0]:
                lyrics_lines.pop(0)
                if lyrics_lines and lyrics_lines[0].strip() == '':
                    lyrics_lines.pop(0)
            clean_lyrics = '\n'.join(lyrics_lines)
            
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
        
# --- Name query handler (Dedicated and error-free) ---
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
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=10
            )
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
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=10
            )
        )
        return "yes" in response.text.lower()
    except Exception as e:
        logger.error(f"Error checking if message is for Laila: {e}")
        return False

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# --- Error-Handled Admin Commands ---
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
        await context.bot.unban_chat_member(chat_id, target_user.id)
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
        await context.bot.restrict_chat_member(
            chat_id,
            target_user.id,
            permissions=None
        )
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been muted.")
        logger.info(f"[{chat_id}] {user_id} muted {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not mute user: {e}")
        logger.error(f"[{chat_id}] Error muting user {target_user.id}: {e}")

# --- ON/OFF for everyone ---
async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    global global_bot_status
    if not global_bot_status:
        await context.bot.send_message(chat_id=chat_id, text="The bot is globally powered off by the owner and cannot be turned on in this group.")
        return
    bot_status[chat_id] = True
    await context.bot.send_message(chat_id=chat_id, text="Laila is now ON for this group.")

async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    bot_status[chat_id] = False
    await context.bot.send_message(chat_id=chat_id, text="Laila is now OFF for this group.")

# --- Reboot command for everyone (same as /on) ---
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await on_command(update, context)

# --- Translate command for everyone ---
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Check if the user replied to a message
    if update.message.reply_to_message:
        target_language = " ".join(context.args).strip()
        text_to_translate = update.message.reply_to_message.text
        
        if not target_language:
            await update.message.reply_text("Kripya reply ke saath bhasha ka naam likhein. Jaise: `/tr <bhasha ka naam>`", parse_mode='Markdown')
            return
        if not text_to_translate:
            await update.message.reply_text("Is message mein koi text nahi hai jise translate kiya jaa sake.")
            return
    # Or if the user provided text in the command itself
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
        if response and "Apologies, I'm currently offline." not in response:
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

# --- POWERON/POWEROFF for Owner only ---
async def poweron_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    global global_bot_status
    if global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered on.")
        return
    global_bot_status = True
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered ON. It will now process messages again.")
    logger.info(f"[{update.effective_chat.id}] Global power ON command used by owner.")

async def poweroff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    global global_bot_status
    if not global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered OFF.")
        return
    global_bot_status = False
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered OFF. It will no longer process messages.")
    logger.info(f"[{update.effective_chat.id}] Global power OFF command used by owner.")

# --- UPDATED BROADCAST FUNCTIONALITY (from paid_broadcast) ---
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
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
    
    # Reload known users from sheet to get the latest list
    load_known_users()
    
    logger.info(f"Starting broadcast with ID {broadcast_id}...")
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
                    members_count = await context.bot.get_chat_member_count(chat_id_int)
                    total_group_members += members_count
                except Exception:
                    pass
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

# --- Command to get a photo's file ID ---
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
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
    
    # Bot ko group mein jodne ke liye URL
    add_to_group_url = f"https://t.me/Laila_Gemibot?startgroup=true"
    
    # Inline Keyboard button banana
    keyboard = [[
        InlineKeyboardButton("➕ Add Me To Your Group ➕", url=add_to_group_url)
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        f"Hey there! 😉\n\n"
        f"I'm Laila, your friendly AI assistant. 🤖\n"
        f"I'm here to chat, answer your questions, and help you with anything you need. 😘\n\n"
        f"You can use `/help` to see all the commands.\n"
        f"Let's get started, `{user_name}`! 💖"
    )
    # UPDATED with your provided photo ID
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
    global start_time
    ping_start = time.time()
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
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
        "✨ by AdhyanXlive ✨"
    )
    # UPDATED with your provided photo ID
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
    user_id = update.effective_user.id
    ping_start = time.time()
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
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
    
    sheets_connection_status = "✅ Connected" if sheets_client else "❌ Failed"
    env_vars_status = "✅ All set"
    if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEYS[0], BROADCAST_ADMIN_ID, WEBHOOK_URL]):
        env_vars_status = "⚠️ Missing key variables"
    
    render_status = "✅ Active" if os.getenv("RENDER_EXTERNAL_URL") else "⚠️ Local/Unknown"
    
    api_key_status_text = ""
    for i, key in enumerate(GEMINI_API_KEYS):
        if key:
            key_short = key[-5:]
            status = "Active" if key == active_api_key else "Inactive"
            if time.time() < key_cooldown_until[key]:
                cooldown_remaining = int(key_cooldown_until[key] - time.time())
                status = f"Cooldown ({cooldown_remaining}s)"
            api_key_status_text += f"Key {i+1} (`...{key_short}`): {status}\n"
        else:
            api_key_status_text += f"Key {i+1}: ❌ Missing\n"
    
    if GEMMA_API_KEY:
        api_key_status_text += f"\nDedicated Gemma Key: ✅ Present (`...{GEMMA_API_KEY[-5:]}`)"
    else:
        api_key_status_text += "\nDedicated Gemma Key: ❌ Missing"
    
    if STABLE_HORDE_API_KEY:
        api_key_status_text += f"\nStable Horde Key: ✅ Present (`...{STABLE_HORDE_API_KEY[-5:]}`)"
    else:
        api_key_status_text += "\nLaila is now OFF for this group."
    
    if PEXELS_API_KEY:
        api_key_status_text += f"\nPexels Key: ✅ Present (`...{PEXELS_API_KEY[-5:]}`)"
    else:
        api_key_status_text += "\nLaila is now OFF for this group."
    
    if GENIUS_ACCESS_TOKEN:
        api_key_status_text += f"\nGenius Key: ✅ Present (`...{GENIUS_ACCESS_TOKEN[-5:]}`)"
    else:
        api_key_status_text += "\nGenius Key: ❌ Missing"
    
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
        f" Render Status: `{render_status}`\n\n"
        "**Bot Stats**\n"
        f" Total Chats: `{len(known_users)}`\n"
        f" Total Messages: `{total_messages_processed}`\n\n"
        "**API Status**\n"
        f"{api_key_status_text}"
        "\n✨ by AdhyanXlive ✨"
    )
    await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='Markdown')
    logger.info(f"[{chat_id}] /adminstats command used by admin.")

# --- UPDATED: Show all known chats with links and member count for groups ---
async def show_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    global known_users
    
    load_known_users()
    
    known_chats = list(known_users)
    if not known_chats:
        await context.bot.send_message(chat_id=chat_id, text="The bot is not in any groups or private chats yet.")
        return
    
    chat_details = []
    for chat_id_str in known_chats:
        try:
            chat = await context.bot.get_chat(chat_id_str)
            if chat.type == 'private':
                chat_details.append(f"• **User**: `{chat.full_name}` (ID: `{chat_id_str}`)")
            else:
                members_count = "Count not available"
                try:
                    members_count = await context.bot.get_chat_member_count(chat_id_str)
                except Exception:
                    pass
                chat_details.append(
                    f"• **Group**: `{chat.title}` (ID: `{chat_id_str}`)\n"
                    f"  Members: `{members_count}`\n"
                    f"  Link: [t.me/{chat.username}](https://t.me/{chat.username})" if chat.username else f"  *No username found.*"
                )
        except Exception:
            chat_details.append(f"• **Unknown Chat**: ID: `{chat_id_str}` (Bot may have been removed)")
        await asyncio.sleep(0.1)
    
    response_text = "✨ **Laila's Chats** ✨\n\n" + "\n\n".join(chat_details)
    
    await context.bot.send_message(chat_id=user_id, text=response_text, parse_mode='Markdown')
    logger.info(f"[{chat_id}] /show_chats command used by admin. Response sent privately to {user_id}.")

# --- UPDATED process_message function with keyword-based name saving and DM fix ---
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global total_messages_processed
    global_bot_enabled = global_bot_status
    chat_enabled = bot_status[update.effective_chat.id]
    is_private_chat = update.effective_chat.type == 'private'
    user_id = str(update.effective_user.id)
    
    # Store recent users for the couple command
    chat_id = update.effective_chat.id
    user = update.effective_user
    if user:
        add_member_to_sheet(chat_id, user)

    # NEW: Ignore messages that start with a command character '/'
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"[{update.effective_chat.id}] Ignoring message as it's a command: {update.message.text}")
        return
    
    if not global_bot_enabled or (not is_private_chat and not chat_enabled):
        return
        
    bot_username = (await context.bot.get_me()).username
    user_message = update.message.text or update.message.caption
    
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
    
    if not user_message:
        return
    
    # --- NEW: AI-based check for name queries ---
    if await is_name_query_ai(user_message):
        await handle_name_query(update, context)
        return
        
    is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = f"@{bot_username.lower()}" in user_message.lower() or f"laila" in user_message.lower()
    
    should_use_ai = is_private_chat or is_reply_to_bot or is_mention
    if not should_use_ai:
        if await is_message_for_laila(user_message):
            should_use_ai = True
        else:
            logger.info(f"[{chat_id}] Message was not directed at Laila. Ignoring.")
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
                logger.info(f"[{chat_id}] Sent response to {user_id}: {response_text}")
        except Exception as e:
            logger.error(f"Error processing message for chat {chat_id}: {e}", exc_info=True)
            try:
                await update.message.reply_text("An unexpected error occurred. Please try again later.")
            except Exception as reply_e:
                logger.error(f"Failed to send error reply: {reply_e}")
    else:
        logger.info(f"[{chat_id}] Ignoring group message from {user_id}: {user_message}")

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
        "`/tr` - **Text ko translate karein.** Aap ya toh `/tr <bhasha ka naam> <text>` likhein, ya kisi message ko reply karke `/tr <bhasha ka naam>` likhein.\n"
        "`/reboot` - **Bot ko group ke liye firse chalu karein.**\n"
        "`/gen` - **Text se AI image banayein.** Jaise: `/gen a cat with wings`\n"
        "`/img` - **Pexels se photo search karein.** Jaise: `/img sunset on the beach`\n"
        "`/lyrics` - **Gaane ke lyrics dhoondein.** Jaise: `/lyrics Shape of You`\n"
        "`/couple` - **Har baar ek naya couple dekhein.**\n\n"
        "🔒 **Admin Commands (For Group Admins)**\n"
        "`/on` - Laila ko group mein on karein.\n"
        "`/off` - Laila ko group mein off karein.\n"
        "`/reset` - Chat history clear karein.\n"
        "`/ban` - Kisi user ko ban karein (Reply to user's message).\n"
        "`/kick` - Kisi user ko kick karein (Reply to user's message).\n"
        "`/mute` - Kisi user ko mute karein (Reply to user's message).\n\n"
        "✨ by AdhyanXlive ✨"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /help command used.")

# --- ABOUT Command ---
async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = (
        "❤️ **About Laila** ❤️\n\n"
        "I am Laila, an AI assistant created by AdhyanXlive. My purpose is to chat with you and provide answers to your questions.\n\n"
        "My intelligence comes from a family of large language models, allowing me to provide helpful and accurate responses.\n\n"
        "✨ **Creator**: @AdhyanXlive\n"
        "✨ **Version**: 1.0\n\n"
    )
    await update.message.reply_text(about_text, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /about command used.")

# --- Couple Command (UPDATED) ---
async def couple_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text("यह कमांड सिर्फ़ ग्रुप्स में काम करती है।")
        return
    
    # Get members from the Google Sheet
    members_from_sheet = get_members_from_sheet(chat_id)
    active_users = [member for member in members_from_sheet if not member['is_bot']]

    if len(active_users) < 2:
        await update.message.reply_text("इस ग्रुप में कम से कम 2 लोग नहीं हैं कपल बनाने के लिए। 😅")
        return
        
    couple = random.sample(active_users, 2)
    user1 = couple[0]
    user2 = couple[1]
    
    user1_mention = f"[{user1['full_name']}](tg://user?id={user1['id']})"
    user2_mention = f"[{user2['full_name']}](tg://user?id={user2['id']})"
    
    message_text = (
        "💖 **Today's Couple** 💖\n\n"
        f"**{user1_mention}** aur **{user2_mention}** ek naya couple hain! ❤️‍🔥\n\n"
        "Congratulations! 🎉"
    )
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=COUPLE_PHOTO_ID,
        caption=message_text,
        parse_mode='Markdown'
    )
    logger.info(f"[{chat_id}] A new couple was selected with photo: {user1['full_name']} & {user2['full_name']}")

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the admin."""
    logger.error("An error occurred:", exc_info=context.error)
    
    if BROADCAST_ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=BROADCAST_ADMIN_ID,
                text=f"An error occurred in the bot:\n\n`{traceback.format_exc()}`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send error notification to admin: {e}")

# --- Sudo Commands
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
            return await handler(update, context)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is restricted to sudo users only.")
            logger.warning(f"Unauthorized access to restricted command by user {user_id} in chat {update.effective_chat.id}")
    return wrapper
    
# --- Message handler for all text and replies with recent users logic ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Store recent users for the couple command
    user = update.effective_user
    if user:
        add_member_to_sheet(chat_id, user)

    # Pass the message to the main processing function
    await process_message(update, context)

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    for member in update.effective_message.new_chat_members:
        add_member_to_sheet(chat_id, member)
        logger.info(f"[{chat_id}] New member added to sheet: {member.full_name}")

async def handle_left_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_message.left_chat_member
    if user:
        remove_member_from_sheet(chat_id, user.id)
        logger.info(f"[{chat_id}] Member removed from sheet: {user.full_name}")

# --- Main function ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # setup_database() # Commented out as we are using Google Sheets
    
    # Load data from Google Sheets on startup
    if setup_google_sheets():
        load_known_users()
        load_sudo_users()
    else:
        logger.critical("Failed to connect to Google Sheets. Broadcast and sudo functions will not work correctly.")
    
    # Regular Commands (NO sudo check)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("id", get_id_command))
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("reboot", reboot_command))
    application.add_handler(CommandHandler("gen", gen_command))
    application.add_handler(CommandHandler("img", img_command))
    
    # Naya Command Handler
    application.add_handler(CommandHandler("lyrics", lyrics_command))
    application.add_handler(CommandHandler("couple", couple_command))

    # Owner-Only Commands (Now accessible to Sudo Users via the wrapper)
    application.add_handler(CommandHandler("poweron", check_sudo_wrapper(poweron_command)))
    application.add_handler(CommandHandler("poweroff", check_sudo_wrapper(poweroff_command)))
    application.add_handler(CommandHandler("broadcast", check_sudo_wrapper(broadcast_command)))
    application.add_handler(CommandHandler("get_photo_id", check_sudo_wrapper(get_photo_id)))
    application.add_handler(CommandHandler("adminstats", check_sudo_wrapper(admin_stats_command)))
    application.add_handler(CommandHandler("show_chats", check_sudo_wrapper(show_chats_command)))
    
    # Sudo Management Commands (For the owner only, as per security best practices)
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("removesudo", remove_sudo_command))

    # Admin Commands
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("mute", mute_user))
    
    # Message handler for all text and replies
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO & filters.REPLY, message_handler))

    # Chat Member Handler for automated database updates
    application.add_handler(ChatMemberHandler(handle_new_members, filters.ChatMember.MEMBER))
    application.add_handler(ChatMemberHandler(handle_left_member, filters.ChatMember.LEFT))
    
    # Add the error handler
    application.add_error_handler(error_handler)
    
    # To run with webhook
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8000"))
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=f"/{TELEGRAM_BOT_TOKEN}",
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        )
        logger.info(f"Bot started with webhook on port {PORT}")
    # To run in polling mode
    else:
        logger.info("Starting bot in polling mode.")
        application.run_polling()

if __name__ == '__main__':
    main()
