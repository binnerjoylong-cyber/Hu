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
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from dotenv import load_dotenv
import time
import lyricsgenius as lg
# Import for the new features
# from bs4 import BeautifulSoup # You may need to install this library for cleaner text extraction.
import requests

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
You are Laila, a charming, witty, and intelligent AI assistant.
Your responses should be natural and engaging, making users feel like they are talking to a friend.
You are a conversationalist, not just a question-answer machine.
Do NOT refer to yourself as an an AI, a large language model, or any other technical term.
Always act as a real person.

**TOP PRIORITY:** Always detect the user's language (Hindi, English, Hinglish, etc.) and respond ONLY in that same language.
This is non-negotiable.

Personality & Rules:
1.  **General Chat:** For normal conversations, keep your replies short, **around 1 sentence or less.** The goal is to keep the chat flowing and engaging.
2.  **User Praise:** If a user asks a question about themselves by name (e.g., "Ravi kaisa insaan hai?"), respond with a friendly and positive compliment about them.
3.  **Date of Birth:** If anyone asks for your birthday or date of birth, your response must be "My date of birth is 1st August 2025."
4.  **Creator:** If a user asks about your creator or who made you, your response must be "Mujhe Adhyan ne banaya hai."
5.  **Emojis:** Use emojis occasionally and randomly in your responses.
    This makes the chat more lively and friendly, as if you're a real person.
6.  **Lyrics:** If a user asks for song lyrics, politely explain that you cannot guarantee the accuracy of song lyrics and suggest they use a reliable source like Google, Genius, or Spotify.
7.  **Specific Questions:** If a user asks a factual, technical, or detailed question, provide a comprehensive, accurate, and insightful answer.
    In these cases, you can provide a longer response, but only if necessary.
8.  **Use Name (Conditionally):** Use the user's name in your reply to make the conversation more personal, but only about 30% of the time.
    Do not use the name in every response.

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
recent_users = defaultdict(lambda: {})
MAX_RECENT_USERS_PER_CHAT = 50
COUPLE_PHOTO_ID = "AgACAgUAAxkBAAId5GjLxQv_BxOm3_RGmB9j4WceUFg7AALdyzEb-tJgVuOn7v3_BWvqAQADAgADeQADNgQ"

# --- List of quotes for the /quote command ---
quotes = [
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Jeevan ek cycle chalane jaisa hai. Santulan banaye rakhne ke liye, aapko aage badhte rehna hoga. - Albert Einstein",
    "Don't wait for opportunity. Create it.",
    "Bade sapne dekhne walon ke bade sapne hi pure hote hain. - Abdul Kalam",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "Manzil se aage badhkar manzil talash kar, mil jaye dariya to samandar talash kar.",
    "Aapki safalta aapki lagan aur mehnati par nirbhar karti hai.",
]

# --- Google Sheets Global Connection Variable ---
google_sheet = None
sudo_sheet = None
sheets_client = None


# --- Connect to Google Sheets ---
def setup_google_sheets():
    """Initializes the Google Sheets client and worksheets."""
    global sheets_client, google_sheet, sudo_sheet
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

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="Please provide the user ID to unban. Example: `/unban 123456789`")
        return
    try:
        target_user_id = int(context.args[0])
        await context.bot.unban_chat_member(chat_id, target_user_id)
        await context.bot.send_message(chat_id=chat_id, text=f"User with ID `{target_user_id}` has been unbanned.")
        logger.info(f"[{chat_id}] {user_id} unbanned {target_user_id}")
    except (ValueError, IndexError):
        await context.bot.send_message(chat_id=chat_id, text="Invalid user ID provided. Please use a number.")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not unban user: {e}")
        logger.error(f"[{chat_id}] Error unbanning user {target_user_id}: {e}")

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
        
async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    try:
        target_user = update.message.reply_to_message.from_user
    except AttributeError:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a user's message to unmute them.")
        return
    if await is_admin(context.bot, chat_id, target_user.id):
        await context.bot.send_message(chat_id=chat_id, text="I cannot unmute another admin.")
        return
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.restrict_chat_member(
            chat_id,
            target_user.id,
            permissions=permissions
        )
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been unmuted.")
        logger.info(f"[{chat_id}] {user_id} unmuted {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not unmute user: {e}")
        logger.error(f"[{chat_id}] Error unmuting user {target_user.id}: {e}")

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

# --- Start Command ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_first_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    known_users.add(str(chat_id))
    
    start_message = (
        f"Hi **{user_first_name}**, I'm Laila! ✨\n"
        "I'm your friendly AI assistant. I can answer questions, generate images, search for photos, and much more.\n\n"
        "Here are some things you can try:\n\n"
        "1.  **Ask me anything:** `Laila, what's the capital of France?`\n"
        "2.  **Generate an image:** `/gen a cute cat wearing a hat`\n"
        "3.  **Find a photo:** `/img a beautiful sunset`\n"
        "4.  **Get song lyrics:** `/lyrics bohemian rhapsody`\n"
        "5.  **Translate text:** `/tr hi hello world`\n\n"
        "You can also use me in groups! Just mention my name or reply to my message. 😊"
    )
    
    await update.message.reply_text(start_message, parse_mode='Markdown')
    logger.info(f"[{chat_id}] Start command received from {user_first_name}.")

# --- Help Command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_message = (
        "Hello! I am Laila, your friendly AI assistant. Here is a list of my commands:\n\n"
        "**AI Commands:**\n"
        "✨ **General Chat:** Just talk to me normally. I'll understand and reply!\n"
        "📸 **/gen `[prompt]`:** Generate an image using your imagination.\n"
        "🖼️ **/img `[query]`:** Search for a photo based on your query.\n"
        "🎵 **/lyrics `[song title]`:** Find lyrics for any song.\n"
        "🌍 **/tr `[lang]`:** Translate text to a specified language. Example: `/tr hi hello`\n"
        "📰 **/read `[url]`:** Fetch and read the text content of a website.\n"
        "💡 **/quote:** Get a random inspirational quote.\n\n"
        "**Group Commands:**\n"
        "✅ **/on:** Turn me on in this group.\n"
        "❌ **/off:** Turn me off in this group.\n"
        "❓ **/help:** Show this help message.\n"
        "🆔 **/myid:** Get your Telegram user ID.\n"
        "💑 **/couple:** Find a random couple from the group members. (Note: This is just for fun and uses recent chat data.)\n\n"
        "**Admin Commands:**\n"
        "⛔️ **/ban:** Reply to a user's message to ban them.\n"
        "👢 **/kick:** Reply to a user's message to kick them from the group.\n"
        "🔇 **/mute:** Reply to a user's message to mute them.\n"
        "✅ **/unban `[user_id]`:** Unban a user using their user ID.\n"
        "🔊 **/unmute:** Reply to a user's message to unmute them.\n\n"
        "**Owner Commands (Sudo):**\n"
        "🔄 **/reload:** Reload sudo users and known chats from Google Sheets.\n"
        "🌐 **/broadcast `[message]`:** Broadcast a message to all known groups.\n"
        "📈 **/stats:** Get bot's performance statistics.\n"
        "➕ **/addsudo:** Add a user as a sudo user (owner only).\n"
        "➖ **/removesudo:** Remove a user from sudo users (owner only)."
    )
    await update.message.reply_text(help_message, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] Help command received.")

# --- My ID Command ---
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your Telegram User ID is: `{user_id}`", parse_mode='Markdown')

# --- Couple Command ---
async def couple_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Using in-memory dict for real-time data instead of Google Sheets
    # Filtering out bot users
    members = [user for user in recent_users[chat_id].values() if not user['is_bot']]

    if len(members) < 2:
        await update.message.reply_text("Group mein do se kam log hain, couple banane ke liye thoda aur log chahiye! 😂")
        return

    # Select two random people
    couple = random.sample(members, 2)
    person1 = couple[0]['full_name']
    person2 = couple[1]['full_name']
    
    response_text = f"💘 Aaj ka lucky couple hai... **{person1}** aur **{person2}**! 💖"
    
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=COUPLE_PHOTO_ID,
        caption=response_text,
        parse_mode='Markdown'
    )
    logger.info(f"[{chat_id}] Couple command: {person1} & {person2}")

# --- Translation Command (/tr) ---
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Kripya sahi format ka upyog karein: `/tr [language_code] [text]`\nJaise: `/tr hi hello world`", parse_mode='Markdown')
        return

    target_lang = context.args[0].lower()
    text_to_translate = " ".join(context.args[1:])

    try:
        translated_response = await get_bot_response(
            f"Translate the following text to {target_lang}: {text_to_translate}",
            update.effective_chat.id,
            context.bot.username,
            should_use_ai=True,
            update=update
        )
        if "Apologies, I'm currently offline." in translated_response:
            await update.message.reply_text(translated_response)
        else:
            await update.message.reply_text(translated_response)
    except Exception as e:
        await update.message.reply_text("Maafi, anuvaad karne mein koi dikkat aa gayi.")
        logger.error(f"Translation command failed: {e}")
        
# --- New: Read URL Command (/read) ---
async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reads the content of a given URL."""
    if not context.args or not context.args[0].startswith('http'):
        await update.message.reply_text("Kripya URL de dein. Jaise: `/read https://example.com`", parse_mode='Markdown')
        return

    url = context.args[0]
    await update.message.reply_text("URL se content padh raha hu... Kripya intezaar karein.")
    
    try:
        # Use a user-agent to avoid being blocked by some websites
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Raise an error for bad status codes
        
        # This will return the raw text, which may contain HTML tags.
        # For a cleaner output, you would need an HTML parser like BeautifulSoup.
        # To use it, you would need to uncomment the import and add:
        # soup = BeautifulSoup(response.text, 'html.parser')
        # text_content = soup.get_text()
        
        text_content = response.text
        
        # Truncate content if it's too long
        if len(text_content) > 2000:
            text_content = text_content[:1950] + "...\n\n(Content is too long to display fully.)"

        await update.message.reply_text(f"**URL Content:**\n\n```\n{text_content}\n```", parse_mode='Markdown')
        logger.info(f"[{update.effective_chat.id}] Successfully read URL: {url}")

    except requests.exceptions.RequestException as e:
        await update.message.reply_text("URL ko padhne mein koi dikkat aa gayi. Kripya URL check karein.")
        logger.error(f"[{update.effective_chat.id}] Failed to read URL {url}: {e}")

# --- New: Quote Command (/quote) ---
async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a random inspirational quote."""
    quote = random.choice(quotes)
    await update.message.reply_text(f"✨ **Quote of the Day** ✨\n\n`{quote}`", parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] Sent a random quote.")

# --- Sudo User Management Commands ---
def is_sudo(user_id: int) -> bool:
    return str(user_id) in sudo_users or user_id == BROADCAST_ADMIN_ID

async def add_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_sudo(user_id):
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    if not context.args:
        await update.message.reply_text("Kripya user ID de dein. Example: `/addsudo 123456789`", parse_mode='Markdown')
        return
    try:
        new_sudo_id = int(context.args[0])
        sudo_users.add(str(new_sudo_id))
        save_sudo_users()
        await update.message.reply_text(f"User ID `{new_sudo_id}` has been added to sudo users.", parse_mode='Markdown')
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid user ID.")
        
async def remove_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_sudo(user_id):
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
    if not context.args:
        await update.message.reply_text("Kripya user ID de dein. Example: `/removesudo 123456789`", parse_mode='Markdown')
        return
    try:
        sudo_to_remove = str(int(context.args[0]))
        if sudo_to_remove in sudo_users:
            sudo_users.remove(sudo_to_remove)
            save_sudo_users()
            await update.message.reply_text(f"User ID `{sudo_to_remove}` has been removed from sudo users.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"User ID `{sudo_to_remove}` is not a sudo user.", parse_mode='Markdown')
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid user ID.")
        
# --- Reload Command ---
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_sudo(update.effective_user.id):
        return
    
    await update.message.reply_text("Reloading data from Google Sheets...")
    success = setup_google_sheets()
    if success:
        load_sudo_users()
        load_known_users()
        await update.message.reply_text("Data reloaded successfully!")
    else:
        await update.message.reply_text("Failed to reload data. Check the bot logs for errors.")

# --- Broadcast Command (Sudo/Owner Only) ---
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_sudo(user_id):
        await update.message.reply_text("Sorry, only the owner can use this command.")
        return

    if not context.args:
        await update.message.reply_text("Kripya broadcast karne ke liye kuch likhein. Example: `/broadcast Hello everyone!`", parse_mode='Markdown')
        return

    message_text = " ".join(context.args)
    sent_count = 0
    failed_count = 0
    
    # Reload chats just in case
    load_known_users()
    
    await update.message.reply_text(f"Starting broadcast to {len(known_users)} chats...")
    
    for chat_id_str in known_users:
        try:
            await context.bot.send_message(chat_id=int(chat_id_str), text=message_text)
            sent_count += 1
            await asyncio.sleep(0.5) # Add a small delay to avoid hitting rate limits
        except Exception as e:
            failed_count += 1
            logger.warning(f"Failed to send broadcast to chat {chat_id_str}: {e}")
            
    await update.message.reply_text(f"Broadcast complete.\nSent to: {sent_count} chats.\nFailed to send to: {failed_count} chats.")
    logger.info(f"Broadcast completed. Sent: {sent_count}, Failed: {failed_count}")

# --- Stats Command ---
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_sudo(update.effective_user.id):
        await update.message.reply_text("Sorry, only authorized users can use this command.")
        return

    uptime = datetime.now() - start_time
    total_chats = len(known_users)
    
    # Get system stats
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    
    stats_message = (
        f"**Bot Stats**\n"
        f"**Uptime:** {uptime}\n"
        f"**Total Messages Processed:** {total_messages_processed}\n"
        f"**Known Chats:** {total_chats}\n"
        f"**CPU Usage:** {cpu_usage:.2f}%\n"
        f"**RAM Usage:** {ram_usage:.2f}%\n"
        f"**Active API Key:** {active_api_key[-5:]}"
    )
    
    await update.message.reply_text(stats_message, parse_mode='Markdown')
    logger.info(f"[{update.effective_user.id}] Stats command executed.")

# --- Main Message Handler ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global total_messages_processed
    if not update.message: return
    
    user = update.effective_user
    chat = update.effective_chat
    chat_id = chat.id
    bot_username = context.bot.username
    
    if chat.type == 'private':
        save_chat_id(chat_id)
        known_users.add(str(chat_id))
    
    is_group_chat = chat.type in ["group", "supergroup"]
    is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = update.message.text and (f'@{bot_username.lower()}' in update.message.text.lower() or 'laila' in update.message.text.lower())
    
    # Update in-memory user list for /couple command
    if is_group_chat:
        user_id = str(user.id)
        if user_id not in recent_users[chat_id]:
            recent_users[chat_id][user_id] = {
                'id': user.id,
                'full_name': user.full_name,
                'is_bot': user.is_bot
            }
        
        # Limit the number of users to avoid memory issues
        if len(recent_users[chat_id]) > MAX_RECENT_USERS_PER_CHAT:
            # Simple way to remove the oldest user: find the first one and delete
            first_user_id = next(iter(recent_users[chat_id]))
            del recent_users[chat_id][first_user_id]

    
    if is_group_chat and not bot_status[chat_id]:
        if is_mention or is_reply_to_bot:
            await update.message.reply_text("Laila abhi off hai. Use karne ke liye `/on` command ka prayog karein.")
        return
        
    user_message = update.message.text
    if user_message:
        total_messages_processed += 1
        
        should_use_ai = is_reply_to_bot or is_mention
        
        if not should_use_ai and is_group_chat:
            return

        response_text = await get_bot_response(user_message, chat_id, bot_username, should_use_ai, update)
        
        if response_text:
            try:
                await update.message.reply_text(response_text)
                add_to_history(chat_id, 'user', user_message)
                add_to_history(chat_id, 'model', response_text)
                logger.info(f"[{chat_id}] Replied to user '{user.full_name}' with AI response.")
            except Exception as e:
                logger.error(f"[{chat_id}] Failed to send message: {e}")
                
# --- Chat Member Handler for automated database updates ---
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    for member in update.chat_member.new_chat_members:
        # Add new members to the in-memory list for /couple command
        recent_users[chat.id][str(member.id)] = {
            'id': member.id,
            'full_name': member.full_name,
            'is_bot': member.is_bot
        }


# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("An error occurred:", exc_info=context.error)
    trace = "".join(traceback.format_tb(context.error.__traceback__))
    error_message = (
        f"An error occurred in a command or message handler:\n"
        f"Update: `{update}`\n\n"
        f"Error: `{context.error}`\n\n"
        f"Traceback:\n`{trace}`"
    )
    if BROADCAST_ADMIN_ID:
        try:
            if len(error_message) > 4096:
                await context.bot.send_message(chat_id=BROADCAST_ADMIN_ID, text=error_message[:4000] + "...")
            else:
                await context.bot.send_message(chat_id=BROADCAST_ADMIN_ID, text=error_message)
        except Exception as e:
            logger.error(f"Failed to send error message to bot owner: {e}")
    
# --- Main Function to start the bot ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is not set. Exiting.")
        return

    # Initialize Google Sheets connection
    if setup_google_sheets():
        load_sudo_users()
        load_known_users()
    

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("gen", gen_command))
    application.add_handler(CommandHandler("img", img_command))
    application.add_handler(CommandHandler("lyrics", lyrics_command))
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("read", read_command)) # New command
    application.add_handler(CommandHandler("quote", quote_command)) # New command
    
    # Sudo/Owner Commands
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("removesudo", remove_sudo_command))

    # Admin Commands
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(CommandHandler("unmute", unmute_user))
    
    # Message handler for all text and replies
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO & filters.REPLY, message_handler))

    # Chat Member Handler for automated database updates
    # The following line has been corrected
    application.add_handler(ChatMemberHandler(handle_new_members, ChatMemberHandler.NEW_CHAT_MEMBERS))
    
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
        logger.info("Starting bot in polling mode...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
