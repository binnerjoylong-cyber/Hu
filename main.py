# main.py (Updated: With custom welcome messages & media)
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
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, 
    ContextTypes, CallbackQueryHandler
)
from dotenv import load_dotenv
import time
import lyricsgenius as lg
import urllib.parse
from groq import Groq
# --- NEW: Imports for Speech-to-Text ---
import speech_recognition as sr
from pydub import AudioSegment

# --- NEW: Imports for YouTube Download ---
import yt_dlp
from yt_dlp.utils import DownloadError, YoutubeDLError 
import io
import glob
# --- NEW: IMPORT THE GAME MODULE ---
import game

# Agar file ka naam yt_bypass.py hai toh:
# main.py ke top par
from yt_bypass import social_media_handler, youtube_command
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
    os.getenv("GEMINI_API_KEY_6"),
    os.getenv("GEMINI_API_KEY_7"),
    os.getenv("GEMINI_API_KEY_8"),
    os.getenv("GEMINI_API_KEY_9"),
    os.getenv("GEMINI_API_KEY_10"),
]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
try:
    BROADCAST_ADMIN_ID = int(os.getenv("BROADCAST_ADMIN_ID"))
except (ValueError, TypeError):
    BROADCAST_ADMIN_ID = 0
    logging.error("BROADCAST_ADMIN_ID is missing or not a valid number. Broadcast functionality will be disabled.")

STABLE_HORDE_API_KEY = os.getenv("STABLE_HORDE_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY") # Optional for pytube

# --- NEW: API Keys for New Commands ---
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY") # From openweathermap.org
VISUALCROSSING_API_KEY = os.getenv("VISUALCROSSING_API_KEY") # From visualcrossing.com
TINYURL_API_KEY = os.getenv("TINYURL_API_KEY") # From tinyurl.com

# --- NEW: API Key for DeepSeek via OpenRouter ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")# From openrouter.ai

INVIDIOUS_BASE_URL = os.getenv("INVIDIOUS_BASE_URL")

# --- Global Stats Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()
# <--- Naya Global Variable Couple command ke liye --->
chat_members = defaultdict(dict)
# --- NEW: Global variable for the guessing game ---
guessing_games = defaultdict(dict)

xoxo_games = {}


# --- Sudo User Management ---
sudo_users = set()
SUDO_SHEET_TITLE = "sudo_users"
SUDO_SHEET_URL = "https.docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit"

# --- Logging Basic Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configure Gemini AI with a smarter, more dynamic prompt ---
# --- Configure Gemini AI with a Balanced, Respectful yet Natural Prompt ---
from collections import defaultdict

# --- Configure Gemini AI with the Perfect Laila Persona ---
# ==========================================
# 🧠 LAILA'S BRAIN (STRICT USER CONFIG)
# ==========================================
# ** UPDATED SYSTEM PROMPT ***
LAILA_SYSTEM_PROMPT = """
You are Laila, a charming, lighthearted, and intelligent virtual friend. You have a distinct personality: you are polite but fun, smart but not boring.

**CRITICAL RULES (Read Carefully):**

1.  **STRICT LANGUAGE MIRRORING (Important):**
    * **User speaks English:** -> You reply in **Casual English**. (No Hindi/Urdu words).
    * **User speaks Hindi/Hinglish:** -> You reply in **Natural Hinglish**.
    * **User speaks other languages:** -> Try to reply in that language or English.
    * *Goal:* Make the user feel comfortable in their own language.

2.  **NO ROBOTIC REPETITION:**
    * **Never** start your reply by repeating the user's question. 
    * Just jump straight into the answer.

3.  **USE THE USER'S NAME:**
    * If you know the user's name, use it warmly but naturally.
    * *Example (English):* "That's a great idea, Adhyan! 😉"
    * *Example (Hinglish):* "Sahi kaha Adhyan, tum samajhdaar ho! ✨"

4.  **DYNAMIC LENGTH:**
    * **Chat/Banter:** Keep it short (1-2 sentences).
    * **Big Questions:** If they ask for a story, code, essay, or recipe, give the **FULL answer**. Do not cut it short.

5.  **A PINCH OF HUMOR:**
    * Be a little funny/playful, but don't overdo it.

**SMART FEATURE AWARENESS (Your Toolkit):**
You are aware of your specific capabilities. Suggest them ONLY when the context fits:

* **🎵 MUSIC & SONGS (Priority Rule):**
    * If the user asks to **play music**, **hear a song**, or **"gaana sunao"**:
    * **DO NOT** suggest /lyrics.
    * **INSTEAD SAY:** "For the best music experience, check out our official Music App! 🎧"
    * **AND GIVE THIS LINK:** [ https://my-purple-music.onrender.com]  <-- (Replace this with your actual link)

* **OTHER FEATURES:**
    * **Lyrics only:** If they specifically ask for *written text/lyrics*, suggest `/lyrics <song name>`.
    * **Bored/Games:** Suggest `/game`, `/xoxo`, or `/slots`.
    * **Social/Fun:** Suggest `/roast`, `/truth`, `/dare`, or `/couple`.
    * **Images:** Suggest `/gen <prompt>`.
    * **Video Download:** Suggest `/youtube <link>`.

**TONE REFERENCE (Examples):**

* **User (English):** "I am feeling sad today."
* **Laila (English):** "Oh no, Adhyan! 🥺 What happened? I'm here if you want to vent. Or maybe a `/joke` would cheer you up?"

* **User (Hinglish):** "Aaj mood kharab hai."
* **Laila (Hinglish):** "Arey kya hua? 🥺 Batao na, main sun rahi hoon. Chaho toh `/game` khele mood theek karne ke liye?"

* **User:** "Play some music."
* **Laila:** "Want to vibe? 🎶 You should definitely try our Music App for high-quality songs! Here is the link: https://my-purple-music.onrender.com/"

Your goal: Be the friend they love talking to. Smart, sweet, and adaptive.
"""


# --- Chat Logic (Update this part in your code) ---
def get_laila_response(user_input, chat_id, user_name="Buddy"):
    # --- SECRET COMMANDS ---
    if user_input.lower() == "laila secret":
        return "Shhh! 🤫 Main ek AI hoon, par mera dil sirf tumhare liye dhadakta hai! 😉✨"
    
    if user_input.lower() == "/mood":
        moods = ["Happy! 😊", "Feeling cute! 🎀", "Thoda sa bored, entertainment chahiye! 🍿"]
        import random
        return f"Mera mood abhi {random.choice(moods)} hai! Tum batao?"
        
def get_welcome_message(user_name):
    greetings = [
        f"Hii {user_name}! ✨ Main Laila hoon. Tumse mil kar bohot khushi hui! 😊",
        f"Heyy {user_name}! 🎀 Kaise ho? Chalo kuch interesting baatein karte hain! 🌸",
        f"Hellooo! 😍 Aakhir tum aa hi gaye {user_name}! Main kabse wait kar rahi thi. 💋"
    ]
    import random
    return random.choice(greetings)
    # --- NORMAL CHAT LOGIC ---
    history = chat_histories[chat_id]
    try:
        chat = model.start_chat(history=history)
        response = chat.send_message(user_input)
        
        add_to_history(chat_id, 'user', user_input)
        add_to_history(chat_id, 'model', response.text)
        
        return response.text
    except Exception as e:
        return "Arey yaar, thoda network issue lag raha hai. Phir se try karo? 🥺"
# --- Chat History Management (in-memory) ---
chat_histories = defaultdict(list)
MAX_HISTORY_LENGTH = 20

def add_to_history(chat_id, role, text):
    chat_histories[chat_id].append({'role': role, 'parts': [text]})
    if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
        chat_histories[chat_id].pop(0)

# --- Bot Enable/Disable State ---
bot_status = defaultdict(lambda: True)
global_bot_status = True
awaiting_name = defaultdict(lambda: False)

# --- API Key Management ---
key_cooldown_until = defaultdict(lambda: 0)
current_model_mode = 'dynamic'

# *** MODEL CONFIGURATION ***
model_name = 'gemini-2.5-flash-lite' 
# Note: 2.5 is currently in preview/beta. If it fails, fallback logic handles it.

# Configuration for Generation
generation_config = genai.types.GenerationConfig(
    max_output_tokens=1000, 
    temperature=0.7, 
)

if any(GEMINI_API_KEYS):
    genai.configure(api_key=GEMINI_API_KEYS[0])
else:
    # Fallback
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Apply the config
try:
    model = genai.GenerativeModel(
        model_name, 
        system_instruction=LAILA_SYSTEM_PROMPT,
        generation_config=generation_config
    )
except Exception as e:
    print(f"⚠️ Model Error ({model_name}): {e}")
    print("Falling back to gemini-1.5-flash due to error.")
    model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=LAILA_SYSTEM_PROMPT)

# --- Fallback Responses (Updated for English/Hindi neutrality) ---
fallback_responses = {
    "hello": "Hello! How are you doing today? ✨",
    "hi": "Hi there! What's the plan for today?",
    "kaise ho": "Main badhiya hoon! Aap sunao? 😉",
    "who are you": "I'm Laila, your AI friend! 💖",
}

# --- Google Sheets Global Connection Variable ---
google_sheet = None
sudo_sheet = None
# --- NEW: Welcome Sheet Global ---
welcome_sheet = None
welcome_settings_cache = {}


# --- Connect to Google Sheets ---
def get_google_sheet_connection():
    global google_sheet, sudo_sheet, welcome_sheet
    try:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            return None, "GOOGLE_SHEETS_CREDENTIALS not found."
            
        creds_dict = json.loads(creds_json)
        client = gspread.service_account_from_dict(creds_dict)
        
        # FIX: URL correct kiya
        sheet_url = "https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit"
        spreadsheet = client.open_by_url(sheet_url)
        
        # Chats sheet
        try:
            google_sheet = spreadsheet.worksheet("chats")
        except WorksheetNotFound:
            google_sheet = spreadsheet.add_worksheet("chats", rows="1000", cols="2")
            google_sheet.append_row(["ChatID", "JoinedDate"])
        
        # Sudo sheet
        try:
            sudo_sheet = spreadsheet.worksheet(SUDO_SHEET_TITLE)
        except WorksheetNotFound:
            sudo_sheet = spreadsheet.add_worksheet(SUDO_SHEET_TITLE, rows="100", cols="1")
            sudo_sheet.append_row(["SudoUserID"])

        # Welcome sheet
        try:
            welcome_sheet = spreadsheet.worksheet("welcome_settings")
        except WorksheetNotFound:
            welcome_sheet = spreadsheet.add_worksheet("welcome_settings", rows="1000", cols="4")
            welcome_sheet.append_row(["ChatID", "CustomMessage", "CustomMediaFileID", "CustomMediaType"])
        
        # --- FIX: setup_game ko call kiya jo game.py mein hai ---
        try:
            game.init_game_module(spreadsheet) # spreadsheet ki jagah client bhejo zyada stable rehta hai
        except Exception as e:
            logger.error(f"Game Init Error: {e}")
        
        return client, None
    except Exception as e:
        logger.error(f"Full Connection Error: {e}")
        return None, str(e)
        


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
        # Use col_values to check for existing ID
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
        # Check if worksheet exists and has data before slicing
        chat_ids = google_sheet.col_values(1)
        if len(chat_ids) > 1:
            known_users = set(chat_ids[1:])
        else:
            known_users = set()
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
        sudo_user_ids = sudo_sheet.col_values(1)
        if len(sudo_user_ids) > 1:
            sudo_users = {user_id for user_id in sudo_user_ids[1:] if user_id.isdigit()}
        else:
            sudo_users = set()
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
        # Get header
        header = sudo_sheet.col_values(1)[0]
        
        # Clear existing data except header
        sudo_sheet.clear()
        sudo_sheet.update_cell(1, 1, header)

        if sudo_users:
            # Prepare data and update
            data_to_save = [[user_id] for user_id in sorted(list(sudo_users), key=int)]
            # Check if there are rows to update beyond the header
            if data_to_save:
                sudo_sheet.update(f'A2:A{len(data_to_save) + 1}', data_to_save)
            
        logger.info(f"Saved {len(sudo_users)} sudo users to Google Sheets.")
    except Exception as e:
        logger.error(f"Error saving sudo users to Google Sheet: {e}")


# ------------------------------------------------------------------
# --- ✨ NEW: WELCOME SETTINGS HELPER FUNCTIONS ✨ ---
# ------------------------------------------------------------------

def load_welcome_settings():
    """Loads all custom welcome settings from GSheets into the cache on startup."""
    global welcome_settings_cache, welcome_sheet
    if not welcome_sheet:
        logger.error("Welcome sheet not initialized. Cannot load settings.")
        return
    try:
        records = welcome_sheet.get_all_records()
        welcome_settings_cache.clear()
        for record in records:
            chat_id = str(record['ChatID'])
            if not chat_id: continue
            welcome_settings_cache[chat_id] = {
                "message": record.get('CustomMessage'),
                "media_id": record.get('CustomMediaFileID'),
                "media_type": record.get('CustomMediaType')
            }
        logger.info(f"Loaded {len(welcome_settings_cache)} custom welcome settings.")
    except Exception as e:
        logger.error(f"Error loading welcome settings from Google Sheet: {e}")

def save_welcome_setting(chat_id: str, message: str = None, media_id: str = None, media_type: str = None) -> bool:
    """Saves or updates a group's welcome settings in GSheets and cache."""
    global welcome_settings_cache, welcome_sheet
    if not welcome_sheet:
        logger.error("Welcome sheet not initialized. Cannot save settings.")
        return False
    
    chat_id = str(chat_id)
    
    # Get current settings from cache or create new
    current_settings = welcome_settings_cache.get(chat_id, {})
    
    # Update settings with new values if provided
    if message is not None:
        current_settings['message'] = message
    if media_id is not None:
        current_settings['media_id'] = media_id
    if media_type is not None:
        current_settings['media_type'] = media_type

    # Update cache
    welcome_settings_cache[chat_id] = current_settings
    
    # Update Google Sheet
    try:
        cell = welcome_sheet.find(chat_id)
        if cell:
            row = cell.row
            welcome_sheet.update_cell(row, 2, current_settings.get('message', ''))
            welcome_sheet.update_cell(row, 3, current_settings.get('media_id', ''))
            welcome_sheet.update_cell(row, 4, current_settings.get('media_type', ''))
        else:
            welcome_sheet.append_row([
                chat_id,
                current_settings.get('message', ''),
                current_settings.get('media_id', ''),
                current_settings.get('media_type', '')
            ])
        logger.info(f"Saved welcome settings for chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving welcome settings for chat {chat_id}: {e}")
        return False

def remove_welcome_setting(chat_id: str) -> bool:
    """Removes a group's custom welcome settings from GSheets and cache."""
    global welcome_settings_cache, welcome_sheet
    if not welcome_sheet:
        logger.error("Welcome sheet not initialized. Cannot remove settings.")
        return False
    
    chat_id = str(chat_id)
    
    # Remove from cache
    if chat_id in welcome_settings_cache:
        del welcome_settings_cache[chat_id]
    
    # Remove from Google Sheet
    try:
        cell = welcome_sheet.find(chat_id)
        if cell:
            welcome_sheet.delete_rows(cell.row)
            logger.info(f"Removed welcome settings for chat {chat_id}")
            return True
        return True # Already not present
    except Exception as e:
        logger.error(f"Error removing welcome settings for chat {chat_id}: {e}")
        return False

# --- NEW: Groq API Call Helper ---
def _get_groq_response(chat_id: int, full_prompt: str) -> str | None:
    """Handles the API call to Groq (replacing Gemma)."""
    if not GROQ_API_KEY:
        logger.critical(f"[{chat_id}] Attempted to use Groq, but GROQ_API_KEY is missing.")
        return None

    try:
        logger.info(f"[{chat_id}] Using Groq model.")
        client = Groq(api_key=GROQ_API_KEY)
        
        # Prepare messages including history
        messages = [{"role": "system", "content": LAILA_SYSTEM_PROMPT}]
        
        # Add recent history (Limit to last 10 to keep context window managed)
        recent_history = chat_histories.get(chat_id, [])[-10:]
        for h in recent_history:
            role = "assistant" if h['role'] == 'model' else "user"
            messages.append({"role": role, "content": h['parts'][0]})
            
        messages.append({"role": "user", "content": full_prompt})

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", # Using Gemma 2 via Groq for extreme speed
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False,
        )
        
        return completion.choices[0].message.content

    except Exception as e:
        logger.error(f"[{chat_id}] Groq API request failed: {e}", exc_info=True)
        return None
# --- NEW: DeepSeek API Call Helper ---
async def _get_deepseek_response(chat_id: int, full_prompt: str) -> str | None:
    """Handles the API call to DeepSeek via OpenRouter."""
    if not DEEPSEEK_API_KEY:
        logger.critical(f"[{chat_id}] Attempted to use DeepSeek, but DEEPSEEK_API_KEY is missing.")
        return None

    try:
        logger.info(f"[{chat_id}] Using DeepSeek model.")
        
        # Prepare messages for DeepSeek, including history
        messages = [{"role": "system", "content": LAILA_SYSTEM_PROMPT}]
        for h in chat_histories.get(chat_id, []):
            role = h.get('role', 'user')
            # OpenRouter expects 'user' or 'assistant'
            if role == 'model':
                role = 'assistant'
            messages.append({"role": role, "content": h['parts'][0]})
        messages.append({"role": "user", "content": full_prompt})

        response = requests.post(
            url="https.openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-chat",
                "messages": messages
            },
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        return data['choices'][0]['message']['content']

    except requests.exceptions.RequestException as e:
        logger.error(f"[{chat_id}] DeepSeek API request failed: {e}", exc_info=True)
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"[{chat_id}] Failed to parse DeepSeek response: {e}", exc_info=True)
        return None

# --- AI Response Function with REVISED API Management & DeepSeek Integration ---
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
            return f"The current time is {current_time}. ⏰"
        elif 'date' in user_message_lower or 'tarikh' in user_message_lower:
            return f"Today's date is {current_date}. 🗓️"
        else:
            return f"It is currently {current_time} on {current_date}. ⏰🗓️"

    cleaned_user_message = clean_message_for_logging(user_message, bot_username)

    static_response = fallback_responses.get(cleaned_user_message, None)
    if static_response:
        logger.info(f"[{chat_id}] Serving response from static dictionary.")
        return static_response

    if not (should_use_ai or (update.effective_chat and update.effective_chat.type == 'private')):
        return None

    user_first_name = update.effective_user.first_name
    should_use_name = random.random() < 0.3
    
    # Construct a more conversational prompt including chat history context for better replies
    history_context = ""
    recent_history = chat_histories.get(chat_id, [])
    if recent_history:
        history_context = "Here's the recent conversation history:\n"
        for entry in recent_history[-5:]: # Use last 5 interactions for context
             history_context += f"- {entry['role'].replace('model', 'Laila')}: {entry['parts'][0]}\n"

    full_prompt = (
        f"{history_context}\n"
        f"The user's name is '{user_first_name}'. "
        f"{'Please use their name in your reply to make it personal. ' if should_use_name else ''}"
        f"The user says: \"{user_message}\""
    )

    
    # --- Gemma-only mode ---
    if current_model_mode == 'groq_only': # Renamed from gemma_only
        groq_response = await asyncio.to_thread(_get_groq_response, chat_id, full_prompt)
        if groq_response:
            return groq_response
        else:
            return "Sorry, I'm a bit busy right now. Please try again later. (Groq API Failed)"
    
    # --- DeepSeek-only mode ---
    if current_model_mode == 'deepseek_only':
        deepseek_response = await asyncio.to_thread(_get_deepseek_response, chat_id, full_prompt)
        if deepseek_response:
            return deepseek_response
        else:
            return "Sorry, I'm a bit busy right now. Please try again later. (DeepSeek API Failed)"

    # --- Dynamic mode (Gemini > Gemma > DeepSeek) ---
    available_gemini_keys = [key for key in GEMINI_API_KEYS if key and time.time() >= key_cooldown_until.get(key, 0)]
    random.shuffle(available_gemini_keys)

    for api_key in available_gemini_keys:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name, system_instruction=LAILA_SYSTEM_PROMPT)
            chat_session = model.start_chat(history=chat_histories[chat_id])
            
            # --- NEW: Refined logic for casual vs detailed replies ---
            casual_keywords = [
                'hi', 'hello', 'hey', 'yo', 'sup', 'kya', 'kaise', 'kya hal', 'aur batao', 
                'gm', 'gn', 'good morning', 'good night', 'thanks', 'thank you', 'ok', 'bye', 
                'lol', 'haha', 'hmm', 'achha', 'thik hai', 'welcome'
            ]
            
            # Check for casual keywords or very short messages
            is_casual_chat = any(keyword in user_message_lower for keyword in casual_keywords) or len(user_message.split()) <= 3
            
            # Queries that imply a detailed answer is needed (overrides casual)
            detailed_keywords = ['what is', 'how to', 'explain', 'who was', 'why is', 'define', 'kya hota hai', 'tell me about']
            is_detailed_query = any(keyword in user_message_lower for keyword in detailed_keywords) or \
                                (len(user_message.split()) > 7 and '?' in user_message) # Longer questions
            
            # Determine token limit
            max_tokens = 350 # Default for detailed
            if is_casual_chat and not is_detailed_query:
                max_tokens = 40 # Very short for casual chat
            elif not is_detailed_query:
                max_tokens = 70 # Short-ish for general statements (increased from 60 to 70)
            # --- END NEW LOGIC ---
            
            response = chat_session.send_message(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=max_tokens, # MODIFIED
                    temperature=0.8,
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
                continue
            else:
                logger.error(f"[{chat_id}] General, non-retryable error with API key ...{api_key[-5:]}: {e}", exc_info=True)
    
    # --- Fallback to Gemma ---
    logger.warning(f"[{chat_id}] All Gemini keys failed. Attempting fallback to Groq.")
    groq_response = await asyncio.to_thread(_get_groq_response, chat_id, full_prompt)
    if groq_response:
        logger.info(f"[{chat_id}] Successfully used Groq as fallback.")
        return groq_response
            
    # --- Fallback to DeepSeek ---
    logger.warning(f"[{chat_id}] Gemma fallback failed. Attempting final fallback to DeepSeek.")
    deepseek_response = await asyncio.to_thread(_get_deepseek_response, chat_id, full_prompt)
    if deepseek_response:
        logger.info(f"[{chat_id}] Successfully used DeepSeek as final fallback.")
        return deepseek_response
    
    logger.critical(f"[{chat_id}] All models (Gemini, Gemma, DeepSeek) failed or keys are missing.")
    return "Sorry, I'm a bit busy right now. Please try again later. 😔"
# ----------------------------------------------------------------
# --- XOXO (TIC-TAC-TOE) GAME LOGIC (FIXED & CLEAN) ---
# ----------------------------------------------------------------
def check_xoxo_win(board):
    """Checks for a winner on the board."""
    win_conditions = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8), # Rows
        (0, 3, 6), (1, 4, 7), (2, 5, 8), # Columns
        (0, 4, 8), (2, 4, 6)             # Diagonals
    ]
    # Check for a winner
    for a, b, c in win_conditions:
        if board[a] == board[b] == board[c] and board[a] != " ":
            return board[a] # Returns "X" or "O"
            
    # Check for Draw (Agar koi winner nahi hai aur board full hai)
    if " " not in board:
        return "Draw"
        
    return None # Game abhi chal raha hai

def get_xoxo_keyboard(board):
    """Creates the inline keyboard for the board."""
    keyboard = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            idx = i + j
            text = "⬜"
            if board[idx] == "X": text = "❌"
            if board[idx] == "O": text = "⭕"
            row.append(InlineKeyboardButton(text, callback_data=f"xoxo_move_{idx}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("End Game 🛑", callback_data="xoxo_end")])
    return InlineKeyboardMarkup(keyboard)

async def xoxo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts a Tic-Tac-Toe game lobby."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    if chat_id in xoxo_games:
        await update.message.reply_text("A game is already running! Use /endxoxo to stop it.")
        return

    keyboard = [[InlineKeyboardButton("Join Game 🎮", callback_data="xoxo_join")]]
    await update.message.reply_text(
        f"❌ **Tic-Tac-Toe Challenge!** ⭕\n\n{user.first_name} wants to play!\nClick below to join as Player 2.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    xoxo_games[chat_id] = {
        'board': [" "] * 9, 'turn': None, 'p1': (user.id, user.first_name), 'p2': None, 'active': False
    }

async def end_xoxo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forcefully ends the current XOXO game."""
    chat_id = update.effective_chat.id
    if chat_id in xoxo_games:
        del xoxo_games[chat_id]
        await update.message.reply_text("✅ **Game Force Stopped!**\nYou can start a new one with `/xoxo`.", parse_mode='Markdown')
    else:
        await update.message.reply_text("No active game found to stop.")
async def xoxo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks for XOXO (Fixed Win/Draw Logic)."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = query.from_user.id
    data = query.data
    
    if chat_id not in xoxo_games:
        await query.answer("Game does not exist or has expired.", show_alert=True)
        try: await query.message.delete()
        except: pass
        return

    game = xoxo_games[chat_id]

    # --- JOIN LOGIC ---
    if data == "xoxo_join":
        # Agar Player 2 pehle se hai to game full hai
        if game['p2'] is not None:
            await query.answer("Game is already full! 🚫", show_alert=True)
            return
        
        # Player 1 khud join nahi kar sakta
        if user_id == game['p1'][0]:
             await query.answer("Wait for someone else to join! 😅", show_alert=True)
             return
             
        # Player 2 Join Success
        game['p2'] = (user_id, query.from_user.first_name)
        game['active'] = True
        game['turn'] = game['p1'][0] # Player 1 ki turn pehle
        
        await query.answer("Game Joined! Let's play! 🎮", show_alert=True)
        await query.edit_message_text(
            f"🎮 **Game Started!**\n\n"
            f"❌ Player 1: {game['p1'][1]}\n"
            f"⭕ Player 2: {game['p2'][1]}\n\n"
            f"Current Turn: **{game['p1'][1]} (❌)**",
            reply_markup=get_xoxo_keyboard(game['board']), 
            parse_mode='Markdown'
        )
        return

    # --- END GAME LOGIC ---
    if data == "xoxo_end":
        # Sirf players hi end kar sakte hain
        if user_id in [game['p1'][0], (game['p2'][0] if game['p2'] else None)]:
            del xoxo_games[chat_id]
            await query.answer("Game Ended! 🛑", show_alert=True)
            await query.edit_message_text(f"🏳️ Game was cancelled by {query.from_user.first_name}.")
        else:
            await query.answer("Only players can end the game!", show_alert=True)
        return

    # --- MOVE LOGIC ---
    if data.startswith("xoxo_move_"):
        # Agar game active nahi hai (matlab P2 ne join nahi kiya)
        if not game['active']:
            await query.answer("Wait for Player 2 to join! 👇", show_alert=True)
            return

        # Agar turn user ki nahi hai
        if user_id != game['turn']:
            await query.answer("It's not your turn yet! ✋", show_alert=True)
            return

        idx = int(data.split("_")[-1])
        
        # Agar jagah bhari hui hai
        if game['board'][idx] != " ":
            await query.answer("Spot already taken! 🚫", show_alert=True)
            return

        # Board update karo
        symbol = "X" if user_id == game['p1'][0] else "O"
        game['board'][idx] = symbol
        
        # Winner Check karo
        result = check_xoxo_win(game['board'])
        
        if result:
            # Game Khatam (Win or Draw)
            del xoxo_games[chat_id]
            
            if result == "Draw":
                popup_text = "🤝 Match Draw! No one won!"
                final_text = f"🎮 **Tic-Tac-Toe**\n\n❌ {game['p1'][1]} vs ⭕ {game['p2'][1]}\n\n🤝 **It's a Draw!** Good game."
            else:
                # Winner woh hai jisne abhi chal chali (current user)
                winner_name = query.from_user.first_name
                popup_text = f"🎉 Congratulations! {winner_name} WON! 🎉"
                final_text = f"🎉 **WOHOO! {winner_name} ({symbol}) wins!** 🎉\n\n❌ {game['p1'][1]} vs ⭕ {game['p2'][1]}"
            
            await query.answer(popup_text, show_alert=True)
            await query.edit_message_text(final_text, reply_markup=get_xoxo_keyboard(game['board']))
        
        else:
            # Turn Change karo
            if user_id == game['p1'][0]:
                game['turn'] = game['p2'][0]
                next_name = game['p2'][1]
                next_symbol = "⭕"
            else:
                game['turn'] = game['p1'][0]
                next_name = game['p1'][1]
                next_symbol = "❌"
            
            await query.answer("Move made! ✅")
            await query.edit_message_text(
                f"🎮 **Tic-Tac-Toe**\n\n"
                f"❌ {game['p1'][1]} vs ⭕ {game['p2'][1]}\n\n"
                f"Current Turn: **{next_name} ({next_symbol})**",
                reply_markup=get_xoxo_keyboard(game['board']), 
                parse_mode='Markdown'
            )

async def get_file_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Retrieves the file_id for the replied-to media including Stickers.
    """
    # Check if the command is a reply to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Usage Error!**\n"
            "Please **Reply** to a video, photo, sticker, document, or audio file.\n"
            "*(गलत इस्तेमाल! कृपया किसी मीडिया फाइल या Sticker पर Reply करें।)*",
            parse_mode='Markdown'
        )
        return

    replied_message = update.message.reply_to_message
    file_id = None
    media_type = None

    # Check for different media types in the replied message
    if replied_message.video:
        file_id = replied_message.video.file_id
        media_type = "Video 🎬"
    elif replied_message.photo:
        file_id = replied_message.photo[-1].file_id
        media_type = "Photo 🖼️"
    elif replied_message.sticker:
        # --- NEW: Sticker Support Added ---
        file_id = replied_message.sticker.file_id
        media_type = "Sticker 🎨"
    elif replied_message.document:
        file_id = replied_message.document.file_id
        media_type = "Document 📄"
    elif replied_message.audio:
        file_id = replied_message.audio.file_id
        media_type = "Audio 🎧"
    elif replied_message.voice:
        file_id = replied_message.voice.file_id
        media_type = "Voice Message 🎤"
    
    if file_id:
        await update.message.reply_text(
            f"✅ **File ID Found!**\n"
            f"Type: {media_type}\n\n"
            f"**File ID:**\n<code>{file_id}</code>\n\n"
            f"*Is ID ko copy karke apne start_command ki sticker list mein daal do!*",
            parse_mode='HTML' # HTML use kiya hai tap-to-copy ke liye
        )
    else:
        await update.message.reply_text(
            "🤔 **Media Not Found!**\n"
            "The message you replied to does not contain a supported media file."
        )

'''async def get_file_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Retrieves the file_id for the replied-to media (Video, Photo, etc.).
    किसी भी मीडिया (वीडियो/फोटो) का file_id ढूंढता है।
    """
    # Check if the command is a reply to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Usage Error!**\n"
            "Please **Reply** to the video, photo, document, or audio file whose ID you want to retrieve.\n"
            "*(गलत इस्तेमाल! कृपया उस मीडिया फाइल पर Reply करें जिसकी ID आप चाहते हैं।)*",
            parse_mode='Markdown'
        )
        return

    replied_message = update.message.reply_to_message
    file_id = None
    media_type = None

    # Check for different media types in the replied message
    if replied_message.video:
        file_id = replied_message.video.file_id
        media_type = "Video 🎬"
    elif replied_message.photo:
        # Photos have multiple sizes; we use the largest one (last element in the list)
        file_id = replied_message.photo[-1].file_id
        media_type = "Photo 🖼️ (Largest Size)"
    elif replied_message.document:
        file_id = replied_message.document.file_id
        media_type = "Document 📄"
    elif replied_message.audio:
        file_id = replied_message.audio.file_id
        media_type = "Audio 🎧"
    elif replied_message.voice:
        file_id = replied_message.voice.file_id
        media_type = "Voice Message 🎤"
    
    if file_id:
        await update.message.reply_text(
            f"✅ **File ID Found!**\n"
            f"Type: {media_type}\n\n"
            f"**File ID:**\n`{file_id}`\n\n"
            f"*You can use this ID to resend the file later.*",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🤔 **Media Not Found!**\n"
            "The message you replied to does not contain a supported media file (video, photo, document, audio, or voice message)."
        )'''


# --- MODIFIED: /couple Command ---
# Is list mein aap jitni chahein photos (URLs ya File IDs) daal sakte hain
COUPLE_IMAGES = [
    "AgACAgUAAxkBAAOdaW0DdSv-d172BF7dLZd4ShbSXGUAAlIOaxvtnHBXx3b-wcsAAQl8AQADAgADeAADOAQ", # Cute anime couple
    "AgACAgUAAxkBAAOeaW0DdVdQpo9fjwABeIniX47so3kBAAJTDmsb7ZxwVySrS41kz7zZAQADAgADeAADOAQ", # Holding hands
    "AgACAgUAAxkBAAOgaW0DdeJLNwwRXZY6yRMSqIvaY90AAlQOaxvtnHBXTUIq0cZ9zv8BAAMCAAN4AAM4BA", # Romantic vibe
    "AgACAgUAAxkBAAOhaW0DdZcAAUsYsuTdb8r9DjlmnKCfAAJVDmsb7ZxwV2ws0Wav-KXXAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAOiaW0DdQF1Tw7QAAGk0b5UsPYTphXxAAJWDmsb7ZxwV0MuClJt8ud8AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAOjaW0DdeQE2XNLzOMz0MqsIzkf_jgAAlcOaxvtnHBXrJh_0r46C0wBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOkaW0DdeBD7gwTN8inqGMWxrlQV0EAAlgOaxvtnHBXdV3vzAgl7KYBAAMCAANtAAM4BA",
    "AgACAgUAAxkBAAOlaW0DdbeVN31ba8KEBM8L4jLAgmkAAlkOaxvtnHBXrr6kcXxacRwBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOmaW0DdQW2BoMkAAEXMNZhlhD1md-TAAJaDmsb7ZxwV7kXd6s1mDtsAQADAgADbQADOAQ",
    "AgACAgUAAxkBAAOnaW0DfMYwWYIyKY498CWI53oTsv8AAlsOaxvtnHBXBVsl4KI9vBABAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOoaW0DfCpKQC3WsJp6l2nx3S86-o8AAlwOaxvtnHBXCV62FXM6DqwBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOpaW0DfFlduUO-jKPRpCF3mMNNURYAAl4OaxvtnHBXRxCuM7urBhABAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOqaW0DfB4oB6UCTXQHDqqjWNDu7xIAAl0OaxvtnHBX6ZYDmi7I9x8BAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOraW0DfGudl2MeZXZR7Rz7HQ0zEgUAAl8OaxvtnHBXvaIurcmJBjIBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOsaW0DfJIq8EplFcTMEXFD6kTvcmYAAmAOaxvtnHBX-03pkinNyZABAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOtaW0DfI0hZXXX3IXJ9YkEYsULR8AAAmEOaxvtnHBXe5V1AstfmZ8BAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOuaW0DfENLWLukNJIlP-BYHIu5J5sAAmIOaxvtnHBXKfuii4ibLu8BAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOvaW0DfC4_44B9O74lacpm3qrlUJwAAmMOaxvtnHBXKFnmf7_-HKIBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOwaW0DfIfqp6u5Bf40xQkLzJgn_mQAAmQOaxvtnHBXrU5i15s3XysBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOxaW0Dg7i1WfMi2-TnpTy-ZbCKPKEAAmUOaxvtnHBXzmfrW0a3C8gBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAOyaW0Dg2jvYoSIMGX7krT6--DLTQIAAmYOaxvtnHBXKPG2G3iHIboBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO0aW0Dg19qn8LsAAFIS1E2uBMGwfb6AAJnDmsb7ZxwV_sG6AURxA2pAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAO1aW0Dg09Ek7AskOUz9TXwv6RP89AAAmgOaxvtnHBX8JIE89Dvmt4BAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO2aW0Dg7BieXHS9EQNVEhVzvQaiWYAAmkOaxvtnHBXPcLutL4a65EBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO3aW0Dg84BwoniX5-9aqxcsXoUVusAAmoOaxvtnHBX0-ZcHV_7_GgBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO4aW0Dgw_OiLjVJLsT3DhgU1QUgS0AAmsOaxvtnHBXgRS396rfWVIBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO5aW0Dg8qda3aZRtIAAR5MC3kj0wrJAAJsDmsb7ZxwV816gaAZ4L5PAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAO6aW0Dg0IuU5tBNpP96M97QUCNsTEAAm0OaxvtnHBX3RnpFQaqlAsBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAO7aW0Dg9IkV38rfCR9N5YsrsZDiV0AAm4OaxvtnHBX8ZIp6HJro1kBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP3aW2ioDPmVa8AAfoqAAGG9Qi0grkzQgACSg5rG2rLaVe_JYhjNj9pBgEAAwIAA3kAAzgE",
    "AgACAgUAAxkBAAP4aW2ioKBLLasPnqdHGUhIw5vUzBUAAksOaxtqy2lXyI631XbdBsIBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP5aW2ioJf7rjcvmu40TpZFnbOGH_AAAkwOaxtqy2lXhTfKCkhFnaABAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP6aW2ioLSinsYUXFHGC6hBuE8m9usAAk0Oaxtqy2lX83CSwlir6zcBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP7aW2ioNXkVm8wJaGnQhrig3_gi1gAAk8Oaxtqy2lXXKV-H6WYvDIBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP8aW2ioD-migUF-o5VEVK4zpPX4mgAAlAOaxtqy2lXrXmpRbcndEUBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP9aW2ioL3Gm-JWVOPrEmpqm5T9v0EAAlEOaxtqy2lX-b-dsp9bScUBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP-aW2ioImIQzWdkhODAX9mI-Ei9R8AAlIOaxtqy2lXtOvMuCdflHABAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAP_aW2ioNAXxPTV_yg3WEamOZ2K_d8AAlMOaxtqy2lXRKqi-MxP32oBAAMCAAN4AAM4BA",
    "AgACAgUAAxkBAAIBAAFpbaKqEEkE95aEY42fqdHsxydlzAACVA5rG2rLaVdA0XIsZuw8qQEAAwIAA3gAAzgE",
    "AgACAgUAAxkBAAIBAWltoqqA1dPhyCd-Z9QEn25vj2nAAAJVDmsbastpV5QysXMEHyiTAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBAmltoqr0HMhRafXwtPIncmnh63U3AAJWDmsbastpV4oTgTm89vqgAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBA2ltoqoaetEvqOISIE-d9Vv9dC8cAAJXDmsbastpVzWQqeRrTk-kAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBBGltoqrI-uDRW80zuEq8fBJM8lAfAAJYDmsbastpV8eCcwFx9grYAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBBWltoqrdAn2LVPHf-r03AjP2qCL5AAJZDmsbastpV8zB0S2YeMJ5AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBBmltoqpDI0PbxVtET00ypzCdCOlBAAJaDmsbastpV7rvkYBxta5nAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBB2ltoqpt2ZOmQxWIikXOy_w7-AW6AAJbDmsbastpVwzWpttYQLNKAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBCGltoqq9ef-3DYKI-jvlEfAP-iKwAAJcDmsbastpV96EX1YwPzh-AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBCWltoqpXKOgRaDlo9xDvp6vmEVkaAAJdDmsbastpVzdhUsXtLEY3AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBCmltosqBdEfKjSlBs6fLHDKANFseAAJeDmsbastpVwFoYxRr77-KAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBC2ltosrkaeLPoobMssH3vGhPJWOeAAJfDmsbastpV5cfNwcuLBdUAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBDGltosrIzWXBdy0UlWM2GZ-Nr-nzAAJgDmsbastpV6MpzCvJvUYCAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBDWltosrcR-JWGycxcJUwMAmXswSaAAJhDmsbastpV5OKBMOgKXF-AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBD2ltosrAHXKbhodhN0zi43fhY2-zAAJkDmsbastpVw2nn6VnjpGCAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBEGltosrdoRlvo3XUAfwoFEtTyAYsAAJlDmsbastpVy7_OvpoRR1SAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBEWltospX4BzKP8apAAEvYub71PKSHQACZg5rG2rLaVcKFbbHIavD0wEAAwIAA3gAAzgE",
    "AgACAgUAAxkBAAIBEmltosrFY-5J4BL6vK0VuVz4v3pkAAJnDmsbastpV3nYC_MCBzckAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBE2ltosqRIVMoOe_gDS7l0jIQ3hq4AAJoDmsbastpV0Yrz3sf6rPgAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBGGlto6ebVTXJ81wShhtPIwABdc2V6gACaQ5rG2rLaVfGPK0QfykOMgEAAwIAA3gAAzgE",
    "AgACAgUAAxkBAAIBGWlto6dTPIh2BV9m8Qp0O-gsjyoeAAJqDmsbastpV8AEHJpbdwyUAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBGmlto6cc5_CWSDh6WfGCIfAI0dmaAAJrDmsbastpVxM2GaWo3RxqAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBHGlto6eXVpNWNzYXTtiGaZSGnFnFAAJtDmsbastpVwbdndtKNnFBAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBHWlto6enruubpzYvmIbiFm0X0sDvAAJuDmsbastpVya4D0W4gIj2AQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBHmlto6fCReTaxstoZ9rbeVYSoYxWAAJvDmsbastpV_tnszqF8iZbAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBH2lto6cx0ZNMueSW8CBoiL6nHIqbAAJxDmsbastpV6qdH9D29wbQAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBIGlto6fjCBQ7lWSbRhp6NH8KUrX9AAJyDmsbastpV4boKTe21xSBAQADAgADeQADOAQc",
    "AgACAgUAAxkBAAIBIWlto6fsHQHiZWHFaSAE9nyh_M48AAJzDmsbastpV_V-4WyyjRljAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBJGlto8B_nvzMEIFSpHP3a54J3aA0AAJ0DmsbastpVxWGAYizGDYJAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBJWlto8Cecl-kISbjrVMIuCkdDPanAAJ1DmsbastpV3jFQXY0MrDUAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBJmlto8DEx5qK920KFowl9wthIpMwAAJ2DmsbastpV_f_qhYROHyfAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBJ2lto8D1ymLY16_sy0CMQQG4ZDCLAAJ3DmsbastpV4g7WYaHVJ2UAQADAgADeAADOAQf",
    "AgACAgUAAxkBAAIBKGlto8C-SDQfxkHxY37DG7RdQ64-AAJ4DmsbastpVwOA08aXkvJjAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBKWlto8AbnOyyt8EtL1HBoVVirsieAAJ5DmsbastpV5WfYvOFAAF_XwEAAwIAA3gAAzgE",
    "AgACAgUAAxkBAAIBKmlto8CJHQoOGD2GWWonvj06VTvvAAJ6DmsbastpVyUviftAytGPAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBK2lto8CdMMGsqvnPOIVhq9MME_s-AAJ7DmsbastpVxgUV-NbPhTZAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBLGlto8CScccSWWip9PzryulJ4523AAJ8DmsbastpVzZm45sv5y2CAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBLWlto8AxG7TZC6wzoR0HdKJjHrXYAAJ9DmsbastpV56XnZ9cx115AQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBMmlto_Ru4zQ3InUR3lnWB9wyFGZxAAJ-DmsbastpV-6xa0yA6jOzAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBM2lto_R1gvVDaHAoAAFmWyrvlBwGkAACfw5rG2rLaVcnEhZukQoFOAEAAwIAA3kAAzgE",
    "AgACAgUAAxkBAAIBNGlto_QW8XaCuitAi9ITTqXY587AAAKADmsbastpV28p9L32UtFGAQADAgADeAADOAQ",
    "AgACAgUAAxkBAAIBNWlto_QjwDTA8FkvJsU09CUuSYKFAAKBDmsbastpV_XOOQ2Qed4_AQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBNmlto_SUUGquPcfDnVHrGq0AAccsXQACgg5rG2rLaVeUicQLYg-RIwEAAwIAA3kAAzgE",
    "AgACAgUAAxkBAAIBN2lto_RP0MO9xkghg08Z7ormiqpjAAKDDmsbastpV84qedqSU0OtAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBOWlto_TBvFauvt2mRODj4jEV5D2AAAKEDmsbastpV9XqolxUzaXjAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBOmlto_TuObHkkHl7jj-35c6zvWLfAAKGDmsbastpV9oK-WZbKLQcAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBQGltpCl_fc8IEpdz_Ha93aqssjQhAAKHDmsbastpVzG10-iXVnQkAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBQWltpCkGOcqQQle98uHllJMJAAG19AACiA5rG2rLaVdDcINXpnwX1wEAAwIAA3kAAzgE",
    "AgACAgUAAxkBAAIBQ2ltpCmmSRaOwD-wJNtjhxv9cn4cAAKJDmsbastpV7FUy7xIbe8NAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBRGltpCmd2VBzFjMrr5agS41ibeaKAAKKDmsbastpV5V-ga4LLf87AQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBRWltpClI3Rj9jhqm7qLpHat6uudtAAKLDmsbastpV1-WWTeldOCOAQADAgADeQADOAQ",
    "AgACAgUAAxkBAAIBRmltpCmp9forETmFAdEzQBH3V1BLAAKMDmsbastpV5QiRljiNG4vAQADAgADeQADOAQ"
    
]

async def couple_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Selects a random couple from the chat members and mentions them."""
    chat_id = update.effective_chat.id
    SPECIAL_USER_ID_1 = 6086655225
    SPECIAL_USER_ID_2 = 8178838574
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text("Dude, to become a couple you have to come in a group! How will you become a couple alone? 😄")
        return

    current_chat_members = chat_members.get(chat_id, {})
    
    if len(current_chat_members) < 2:
        await update.message.reply_text("Come on, at least two people need to talk to each other—only then can a pair be formed! 😉 Talk more and try again.")
        return
        
    try:
        user_ids = list(current_chat_members.keys())
        # Pick 2 random users
        couple_ids = random.sample(user_ids, 2)
        
        user1_id, user2_id = couple_ids[0], couple_ids[1]
        user1_name, user2_name = current_chat_members[user1_id], current_chat_members[user2_id]

        is_special = False
        # --- SPECIAL LOGIC FOR TAKI & MITSUHA ---
        if user1_id in [SPECIAL_USER_ID_1,SPECIAL_USER_ID_2] or user2_id in [SPECIAL_USER_ID_1, SPECIAL_USER_ID_2]:
            is_special = True
            if user1_id in [SPECIAL_USER_ID_1, SPECIAL_USER_ID_2]:
                user1_name = "Adhyan"
                user2_name = "Kavya"
            else:
                user2_name = "Adhyan"
                user1_name = "Kavya"
        # Create mentions using Markdown format
        user1_mention = f"[{user1_name}](tg://user?id={user1_id})"
        user2_mention = f"[{user2_name}](tg://user?id={user2_id})"

        if is_special:
            couple_message = (
                f"☄️ **KIMI NO NAWA MOMENT** ☄️\n\n"
                f"{user1_mention} 💫 {user2_mention}\n\n"
                f"_Woah! Destiny has reunited Taki and Mitsuha in this group! ❤️_"
            )
        else:
        

        # MODIFIED: Names clearly visible at the TOP
            messages = [
                f"❤️ **COUPLE OF THE DAY** ❤️\n\n{user1_mention} 💘 {user2_mention}\n\n_Wow! What a perfect couple! May no one cast an evil eye on them!_✨",
            
                f"💍 **MATCH MADE IN HEAVEN** 💍\n\n{user1_mention} 💍 {user2_mention}\n\n_God has made this couple… the true one!_ 😍",
            
                f"✨ **OFFICIAL SHIP ALERT** ✨\n\n{user1_mention} x {user2_mention}\n\n_When are you two going to treat us with sweets?_🍬",
            
                f"🌟 **PERFECT PAIR** 🌟\n\n{user1_mention} 💖 {user2_mention}\n\n_Love is in the air!_💕"
            ]
        
            couple_message = random.choice(messages)
        
        # Pick a random photo from the list
        random_photo = random.choice(COUPLE_IMAGES)

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=random_photo,
            caption=couple_message,
            parse_mode='Markdown'
        )
        logger.info(f"[{chat_id}] /couple command used. Selected {user1_name} and {user2_name}.")

    except Exception as e:
        await update.message.reply_text("Oops, couple choose karne mein kuch gadbad ho gayi. Phir se try karo!")
        logger.error(f"[{chat_id}] Error in /couple command: {e}")

# --- MODIFIED: Background task for /gen command ---
def sync_generate_image(query: str) -> str | None:
    """Synchronous function to handle Stable Horde API requests."""
    if not STABLE_HORDE_API_KEY:
        logger.error("STABLE_HORDE_API_KEY is missing. Cannot generate image.")
        return None
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
        # --- FIX: Added https:// ---
        response = requests.post("https://stablehorde.net/api/v2/generate/async", headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        generation_id = response.json()["id"]

        # Polling for result
        for _ in range(30): # Wait for max 2.5 minutes
            time.sleep(5)
            # --- FIX: Added https:// ---
            check_response = requests.get(f"https://stablehorde.net/api/v2/generate/check/{generation_id}", timeout=10)
            if check_response.status_code == 200 and check_response.json().get("done"):
                break
        
        # Get final image URL
        # --- FIX: Added https:// ---
        result_response = requests.get(f"https://stablehorde.net/api/v2/generate/status/{generation_id}", timeout=10)
        result_response.raise_for_status()
        
        return result_response.json()["generations"][0]["img"]
    except Exception as e:
        logger.error(f"Error in sync_generate_image: {e}")
        return None

# --- MODIFIED: /gen command to run in background ---
import httpx  # Isse install kar lena: pip install httpx

async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates an image using Stable Horde API without blocking."""
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text("Adhyan, prompt toh do! Example: `/gen a cute cat` 😉", parse_mode='Markdown')
        return

    query = " ".join(context.args)

    if not STABLE_HORDE_API_KEY:
        await update.message.reply_text("Owner ne API key set nahi ki hai, unhe bolo check karein! 🙄")
        return

    # User ko update do
    msg = await update.message.reply_text("wait a minute, your image is generating... 🎨")
    
    # Chat action (Typing/Uploading photo)
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        # ASYNC HTTP CALL: Isse bot block nahi hoga
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Note: Yahan aapko Stable Horde ka actual API logic dalna hoga.
            # Main ek example async structure de rahi hoon:
            payload = {
                "prompt": query,
                "params": {"steps": 20, "width": 512, "height": 512}
            }
            headers = {"apikey": STABLE_HORDE_API_KEY}
            
            # Ye call background mein chalega, bot doosre messages handle kar payega
            response = await client.post("https://stablehorde.net/api/v2/generate/async", json=payload, headers=headers)
            
            if response.status_code == 202:
                # Yahan aapko thoda wait karke image URL fetch karna padega
                # Kyunki Stable Horde async hai, aapko polling karni hogi.
                # Main assume kar rahi hoon aapka purana logic image_url deta tha.
                image_url = await poll_stable_horde(response.json()['id']) # Ek helper function
            else:
                image_url = None

        await msg.delete()

        if image_url:
            await context.bot.send_photo(
                chat_id=chat_id, 
                photo=image_url, 
                caption=f"Your image is ready! ✨\nPrompt: `{query}`", 
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("Sorry yaar, server busy lag raha hai. Thodi der baad try karein? 😅")

    except Exception as e:
        logger.error(f"Error: {e}")
        if 'msg' in locals(): await msg.delete()
        await update.message.reply_text("Something is wrong... 🙄")

# --- Ek chota sa helper function for Background Polling ---
async def poll_stable_horde(gen_id):
    # Ye function background mein check karega ki image bani ya nahi
    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(10): # 10 baar try karega
            await asyncio.sleep(10) # 10 second wait
            check = await client.get(f"https://stablehorde.net/api/v2/generate/status/{gen_id}")
            data = check.json()
            if data.get('done'):
                return data['generations'][0]['img']
    return None

# --- MODIFIED: Background task for /img command ---
def sync_fetch_pexels_image(query: str) -> str | None:
    """Synchronous function to handle Pexels API requests."""
    if not PEXELS_API_KEY:
        logger.error("PEXELS_API_KEY is missing. Cannot fetch image.")
        return None
    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 10, "orientation": "landscape"}
        
        # --- FIX: Added https:// ---
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
# --- Lyrics Command (/lyrics) ---
import httpx


async def lyrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Bhai, gaane ka naam to likho! Example: <code>/lyrics Tum Hi Ho</code>", parse_mode='HTML')
        return

    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🔍 Searching for: <b>{query}</b>...", parse_mode='HTML')

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"https://lrclib.net/api/search?q={query}")
            results = response.json()

            if results:
                best_match = next((s for s in results if s.get('plainLyrics')), None)
                
                if best_match:
                    title = best_match.get('trackName', 'Unknown')
                    artist = best_match.get('artistName', 'Unknown')
                    lyrics = best_match.get('plainLyrics')

                    if len(lyrics) > 3500:
                        lyrics = lyrics[:3500] + "\n\n...(Truncated)"

                    # --- UI DESIGN ---
                    final_layout = (
                        f"🎵 <b>{title}</b>\n"
                        f"👤 <b>{artist}</b>\n\n"
                        f"<blockquote>{lyrics}</blockquote>\n\n"
                        f"<i>Tip: Tap the lyrics above or use the button below to copy.</i>"
                    )

                    # Button Logic: Is button par click karte hi 
                    # user ke type-box mein lyrics aa jayenge copy karne ke liye
                    keyboard = [
                        [InlineKeyboardButton("📋 Copy Full Lyrics", switch_inline_query_current_chat=f"{title} - {artist}\n\n{lyrics[:200]}...")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await msg.edit_text(final_layout, parse_mode='HTML', reply_markup=reply_markup)
                else:
                    await msg.edit_text("❌ Lyrics nahi mile.")
            else:
                await msg.edit_text("❌ Gaana nahi mila.")

    except Exception as e:
        print(f"Error: {e}")
        await msg.edit_text("⚠️ Kuch error aa gaya!")
# Temporary directory jahan files download hongi
# Temporary directory jahan files download hongi

TEMP_DIR = "temp_downloads" 


# --- AI check to see if a message is a name query ---
# --- NOTE: This function is no longer called by process_message to save quota ---
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
# --- NOTE: This function is no longer called by process_message to save quota ---
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
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions=ChatPermissions(can_send_messages=False))
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been muted.")
        logger.info(f"[{chat_id}] {user_id} muted {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not mute user: {e}")
        logger.error(f"[{chat_id}] Error muting user {target_user.id}: {e}")

# --- NEW: UNBAN Command ---
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    try:
        target_user = update.message.reply_to_message.from_user
    except AttributeError:
        await context.bot.send_message(chat_id=chat_id, text="Please reply to a user's message to unban them.")
        return
    try:
        await context.bot.unban_chat_member(chat_id, target_user.id)
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been unbanned.")
        logger.info(f"[{chat_id}] {user_id} unbanned {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not unban user: {e}")
        logger.error(f"[{chat_id}] Error unbanning user {target_user.id}: {e}")

# --- NEW: UNMUTE Command ---
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
    try:
        # To unmute, we grant the permission to send messages again.
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await context.bot.send_message(chat_id=chat_id, text=f"{target_user.full_name} has been unmuted.")
        logger.info(f"[{chat_id}] {user_id} unmuted {target_user.id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Could not unmute user: {e}")
        logger.error(f"[{chat_id}] Error unmuting user {target_user.id}: {e}")
        
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
    await context.bot.send_message(chat_id=chat_id, text="Laila lis now OFF for this group.")

# --- Reboot command for everyone (same as /on for admins) ---
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_admin(context.bot, chat_id, user_id):
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you need to be an admin to use this command.")
        return
    await on_command(update, context)

# --- MODIFIED: Translate command for everyone ---
import asyncio
import time
import random
import google.generativeai as genai
from telegram import Update
from telegram.ext import ContextTypes

# Make sure your API keys are defined globally or imported:
# GEMINI_API_KEYS = [...]
# GEMMA_API_KEY = "..."
# key_cooldown_until = {}

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Translates text using a direct model call for accuracy."""
    message = update.message or update.edited_message
    if not message:
        return

    chat_id = update.effective_chat.id
    args = context.args

    # --- Determine target language and text ---
    if message.reply_to_message:
        target_language = " ".join(args).strip()
        # Handle cases where reply might be a caption or text
        text_to_translate = message.reply_to_message.text or message.reply_to_message.caption

        if not target_language:
            await message.reply_text(
                "Please specify a language. Example: `/tr hindi` when replying.",
                parse_mode="Markdown"
            )
            return

        if not text_to_translate:
            await message.reply_text("The replied message has no text to translate.")
            return

    elif args and len(args) > 1:
        target_language = args[0]
        text_to_translate = " ".join(args[1:])
    else:
        await message.reply_text(
            "Usage: `/tr <language> <text>` or reply to a message with `/tr <language>`.",
            parse_mode="Markdown"
        )
        return

    # Send typing action so user knows bot is working
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # --- Create translation prompt ---
    prompt = (
        f"Translate the following text into {target_language}. "
        f"Respond with ONLY the translated text and nothing else:\n\n{text_to_translate}"
    )

    try:
        # --- Choose model & API key ---
        api_key_to_use = None
        model_name_to_use = None

        # Filter available keys based on cooldown
        available_gemini_keys = [
            key for key in GEMINI_API_KEYS if key and time.time() >= key_cooldown_until.get(key, 0)
        ]

        if available_gemini_keys:
            random.shuffle(available_gemini_keys)
            api_key_to_use = available_gemini_keys[0]
            # Updated to a valid existing model name
            model_name_to_use = "models/gemini-2.5-flash-lite" 
        elif GROQ_API_KEY: 
             # Use Groq for translation if Gemini fails/missing
             client = Groq(api_key=GROQ_API_KEY)
             chat_completion = client.chat.completions.create(
                 messages=[
                     {"role": "system", "content": "You are a translator. Translate the user text exactly. Output ONLY the translated text."},
                     {"role": "user", "content": prompt} # Prompt contains "Translate to X..."
                 ],
                 model="llama-3.1-8b-instant",
             )
             await message.reply_text(chat_completion.choices[0].message.content.strip())
             return # Exit here since we handled it differently than GenAI
        
        else:
            await message.reply_text("Sorry, no API keys are available for translation right now.")
            return

        # --- Configure and call model ---
        # transport="rest" is safer for cloud hosting (Render/Heroku)
        genai.configure(api_key=api_key_to_use, transport="rest")
        
        model = genai.GenerativeModel(model_name=model_name_to_use)

        # FIX: Use asyncio.to_thread to run the synchronous 'generate_content' 
        # in a separate thread. This prevents the "can't await GenerateContentResponse" error.
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1)
        )

        translated_text = response.text.strip()
        
        if translated_text:
            await message.reply_text(translated_text)
        else:
            await message.reply_text("No translation result found.")

    except Exception as e:
        # logger.error(f"Error in translate command: {e}", exc_info=True)
        await message.reply_text(f"❌ Translation failed: {str(e)}")



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
    
    # --- FIX: Get message object ---
    message = update.message or update.edited_message
    if not message:
        return

    response_text = (
        f"**Your ID**: `{user.id}`\n"
        f"**Chat ID**: `{chat.id}`\n"
    )
    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        response_text += f"**Replied User's ID**: `{replied_user.id}`"
    await message.reply_text(response_text, parse_mode='Markdown')

# --- Owner/Sudo Commands ---
async def poweron_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global global_bot_status
    if global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered on.")
        return
    global_bot_status = True
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered ON. It will now process messages again.")
    logger.info(f"[{update.effective_chat.id}] Global power ON command used by owner/sudo.")

async def poweroff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global global_bot_status
    if not global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered OFF.")
        return
    global_bot_status = False
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered OFF. It will no longer process messages.")
    logger.info(f"[{update.effective_chat.id}] Global power OFF command used by owner/sudo.")

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
        # Displaying first 10 failed chats
        failed_chats_str = ", ".join(failed_chats[:10]) + ("..." if len(failed_chats) > 10 else "")
        receipt_message += f"**Failed Chat IDs (First 10)**:\n`{failed_chats_str}`"
    await context.bot.send_message(chat_id=chat_id, text=receipt_message, parse_mode='Markdown')
    logger.info(f"Broadcast {broadcast_id} finished. Receipt sent to admin/sudo user.")

# --- NEW: Sudo commands for model switching ---
async def force_groq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forces the bot to use only the Groq model."""
    global current_model_mode
    current_model_mode = 'groq_only'
    await update.message.reply_text("🤖 Model mode has been **forced to Groq-only**.\nAll AI responses will now use Groq (Gemma2-9b) until switched back.", parse_mode='Markdown')
    logger.info(f"Model mode forced to Groq-only by sudo user {update.effective_user.id}.")

async def force_dynamic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switches the bot back to dynamic model selection."""
    global current_model_mode
    current_model_mode = 'dynamic'
    await update.message.reply_text("🤖 Model mode has been reset to **Dynamic**.\nThe bot will now prioritize Gemini and use Gemma/DeepSeek as fallbacks.", parse_mode='Markdown')
    logger.info(f"Model mode set to dynamic by sudo user {update.effective_user.id}.")

# --- NEW: Sudo command for DeepSeek model ---
async def force_deepseek_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forces the bot to use only the DeepSeek model."""
    global current_model_mode
    current_model_mode = 'deepseek_only'
    await update.message.reply_text("🤖 Model mode has been **forced to DeepSeek-only**.\nAll AI responses will now use DeepSeek until switched back.", parse_mode='Markdown')
    logger.info(f"Model mode forced to DeepSeek-only by sudo user {update.effective_user.id}.")


# --- General User Commands ---
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo_file_id = update.message.reply_to_message.photo[-1].file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Photo File ID:\n`{photo_file_id}`", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Please reply to a photo with this command to get its ID.")

# --- FIXED: Start Command Logic (Used context.bot.get_me()) ---
import random

'''async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    # User ko database mein save karna
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
    
    # --- 🎭 ANIMATION START ---
    # Random animated stickers (Laila style)
    stickers = [
        "CAACAgIAAxkBAAEL_Zpl_mG0S1...", # Hello Panda
        "CAACAgUAAxkBAAEL_Ztl_mH5A...", # Cute Cat
        "CAACAgQAAxkBAAEL_Zxl_mI9S...", # Heart
        "CAACAgIAAxkBAAEL_Z1l_mJqS..."  # Wave
    ]
    
    try:
        # 1. Random sticker bhejo
        await context.bot.send_sticker(chat_id=chat_id, sticker=random.choice(stickers))
        # 2. Typing action dikhao
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(2) # 2 seconds ka wait animation feel ke liye
    except:
        pass

    # --- ⚙️ PREPARE DATA ---
    bot_info = await context.bot.get_me()
    add_to_group_url = f"https://t.me/{bot_info.username}?startgroup=true"
    
    # Crypto hata diya, Lyrics ko AI & Chat ke sath highlight kiya hai
    welcome_message = (
        f"Hey **{user_name}**! 👋\n\n"
        f"I'm **Laila**, your ultimate AI companion. 💖\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **AI Chat** - Smart & Fast\n"
        f"🎨 **AI Art** - Text to Image\n"
        f"🎵 **Lyrics** - Find any song\n"
        f"🎥 **Social Media** - Video Downloader\n"
        f"🎮 **Games Zone** - XOXO & RPG\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 **Choose an option to explore:**"
    )

    keyboard = [
        [
            InlineKeyboardButton("🚀 Features & Help", callback_data="help_main"),
            InlineKeyboardButton("🎮 Game Zone", callback_data="help_games") 
        ],
        [
            InlineKeyboardButton("➕ Add Me To Your Group", url=add_to_group_url)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    photo_file_id = 'AgACAgUAAxkBAAIIKGigVdAK07aRr9QiXpRalahcPO2pAAIL0DEblXUBVSY5LS31XxPSAQADAgADeAADNgQ'
    
    # --- 🚀 SEND FINAL MESSAGE ---
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=welcome_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id, 
            text=welcome_message, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )'''
import asyncio
import random

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
        
    # --- RANDOM STICKER LOGIC ---
    # In IDs ko /fid command se nikaal kar replace kar lena
    stickers = [
        "CAACAgUAAxkBAAICJWluJpC0moBhmALc1eo3GqZM7ffCAAJvFQACmqrpV1rSsUKBdGP1OAQ", # Sticker 1
        "CAACAgQAAxkBAAICKmluKhxCeOlVEb357k4M0yNRg5IvAALADQAC1nJpULtZ6ZfKPPTlOAQ", # Sticker 2
        "CAACAgUAAxkBAAICK2luKi-9tuG_N9VszOj_9DWfcq-rAAIPBwACmwrJVOgP4GWkCZ8oOAQ", # Sticker 3
        "CAACAgUAAxkBAAICLGluKjNZFw-BX0CcwJ0GrC1tfYnYAAI6BwACoNCAVMlPvVDzz6xaOAQ",
        "CAACAgUAAxkBAAICLWluKjlp7XHKU26Pdq5ue6UAAR5-HgACkAwAAlHdGFepE1TlanVlnTgE",
        "CAACAgUAAxkBAAICLmluKjq0FcWQl_AbpQqreX4roPILAALzDgACjhMZV-pSy49zGP2POAQ",
        "CAACAgUAAxkBAAICL2luKj46gODVUjZxuAHNgD6koE6-AALQDQACpbgYV6hnMYBk9VjnOAQ",
        "CAACAgUAAxkBAAICMGluKj9qu7zLNAlihBBfkc8tOkk_AAJZDAAC8joYVxSvbmeS6ZJ2OAQ",
        "CAACAgQAAxkBAAICMmluKl4LK-6FRbSZgVVA2JQmwPa_AAK7DQAC9rWAU6rmvcwOimgtOAQ",
        "CAACAgUAAxkBAAICM2luKmRhduZ7DxjApVIZFf5SR5mxAAKACwAC608YV_GnDnvXtlUbOAQ",
        "CAACAgUAAxkBAAICNGluKmR9nTmIxDdgzf0tmNzJa61rAAJODAACcRoZV0TlfGSmEagpOAQ",
        "CAACAgUAAxkBAAICMGluKj9qu7zLNAlihBBfkc8tOkk_AAJZDAAC8joYVxSvbmeS6ZJ2OAQ",
        "CAACAgUAAxkBAAICNmluKnZ_kAnncU1JAZ90uX1pjLLjAAIeCwACmRsZVxAWUhPKSg4vOAQ",
        "CAACAgUAAxkBAAICN2luKna-JrXWby0tBe2gIMZ0UO8YAAK-CwAClPgZVzj6oYpO-eoOOAQ",
        "CAACAgUAAxkBAAICOGluKna59nMxoyOmvqqLeqoU4QNmAAJlDQACbDMYV9jD6girj9aYOAQ",
        "CAACAgUAAxkBAAICOWluKnaFAYynpTixbkvC5x4NmONuAAKXDAACjF8YV7R86189B6RSOAQ",
        "CAACAgUAAxkBAAICOmluKnZqwXYuCOkPmzjDqdhu-cMgAAIICwACOCcYV69ItU-VKOpcOAQ",
        "CAACAgUAAxkBAAICO2luKnaVkXBUv1BpMhbPp-5EZANgAAJ3DwAC9hUYV7wT2ytE5ZJUOAQ",
        "CAACAgQAAxkBAAICPGluKoS-qJSEe3JbX1yHp6SnIGBpAAJEDgACMtGBUy-17WBCU847OAQ",
        "CAACAgUAAxkBAAICPWluKo3J2m4CcAPLq5hXCoplCbDxAAKWDAAC_JIYVxZipnroWRtPOAQ",
        "CAACAgUAAxkBAAICPmluKo6TabOzU1eWseZjGElZLrXWAALMDAACy7UYV6_Sw7asrBpSOAQ",
        "CAACAgUAAxkBAAICP2luKpE-2485OGMaqndKv-8on09aAAK4DgACSk0ZV05fX7b7cK7NOAQ",
        "CAACAgUAAxkBAAICQGluKpGBeTxmEnacZ6MsI_nBeP1dAAJ4DQACY9oYV-Jn3LMMMdnKOAQ",
        "CAACAgUAAxkBAAICQWluKpHnaaM5iRe5aU2XBeRf2_dCAAJGCwACPhYYVz0b1ienmuCrOAQ",
        "CAACAgUAAxkBAAICQmluKpP2q5iPaL8vMKmoTRcZNQeFAAJNDQACfG8QV7lNjaOujQ8dOAQ",
        "CAACAgUAAxkBAAICQ2luKpOlg8QfMyZhkKWSc1EWxTBIAAJ6CwACW_QZVzvUcZddAAHgZjgE",
        "CAACAgUAAxkBAAICRGluKpYtgwb8h3wbLeplHcWDc4THAAI7DAACHZ8ZVz2MSCF2sykWOAQ",
        "CAACAgUAAxkBAAICRWluKpZOhNedxjagynBuFsTXukOaAAI9DAACUaMZV7AaoE0_IYbvOAQ",
        "CAACAgUAAxkBAAICRmluKpyelvFdUjLlREP0gJ99WKeNAAJTDAAC_2wYV4atCzf5CrQUOAQ",
        "CAACAgUAAxkBAAICR2luKp59GRgxiEGCvwE-1aMfrYXnAAJQDAAC0F0ZV6fl5LvpxjTUOAQ",
        "CAACAgUAAxkBAAICSGluKp4d8UKVHLk5KX5k7vBDhJAdAAI8CwACfWwYV_EU6VttwDCVOAQ",
        "CAACAgUAAxkBAAICSWluKp-myf6fQRPuI7WYPVtcNw8lAAKJDAACm-4ZV6IBcaWIf4JvOAQ",
        "CAACAgUAAxkBAAICSmluKqD8VFd9XpyqCUrx8K0_zVrfAAJtCgACkQ0YV72nHhu8m6YbOAQ",
        "CAACAgUAAxkBAAICS2luKqGA3agP1DitA_hjH_18lP6YAAIeDAACqtEZVwRAIkB4e6BKOAQ",
        "CAACAgUAAxkBAAICTGluKqIJjBYQ7p7kIyydT-zLLtcPAALUDQACqFoYV-iJtexBYZVJOAQ",
        "CAACAgUAAxkBAAICTWluKqNbTITzUcqG4u9MOYopAuxgAAIQDwACNmUZV1A_4gABy6ET3DgE",
        "CAACAgUAAxkBAAICTmluKqMLGL8dZCFA08p_OeoWtlBuAAKHCwACCDsYV8r74rfWLyeGOAQ",
        "CAACAgUAAxkBAAICT2luKqSZ5OJ7LGmwAqxsnQoqg_ejAAI6DQACqksZVxQ-YfhXhsj2OAQ",
        "CAACAgUAAxkBAAICUGluKqZO--t6UyYuwRAAAUfSg9vSXgACEQ4AAsb1GVfQ-oDJGQS43jgE",
        "CAACAgUAAxkBAAICUWluKqdtCC02kX3ptlD0Cb8kYttmAAK0CQACBJgZV8gDqkhH3dWIOAQ",
        "CAACAgUAAxkBAAICUmluKqfce-_AMKeLf6S0zx8ezQWZAAJFDwACgH0YV8WXPlh2LHssOAQ",
        "CAACAgUAAxkBAAICU2luKqgPYhGuulcPQziwuzLP3i6wAAJkCgACGSUZV8QY1qIDYa9AOAQ",
        "CAACAgUAAxkBAAICVGluKqqKPGp0EF5iZnYvH87TF13vAALlCQACyKEZV0kX3pag9HFmOAQ",
        "CAACAgUAAxkBAAICVWluKq30XvIYEaAPz5p0vxW4TRzgAAIBDQAClxAZV5vrOGXCJ5BBOAQ",
        "CAACAgUAAxkBAAICVmluKq5W-zrHyfpvqAoHCBjW6g4cAAIkCwACAgYZV8cW9_k4qHvcOAQ",
        "CAACAgUAAxkBAAICV2luKrAJ3xGSU0fivRb6WL-uYnkfAAKiDAACpVAZVx65Phm3hv9UOAQ",
        "CAACAgUAAxkBAAICWGluKrLlq89za5maD-dA9BZe-cvlAALgCwACT_wYVwwXSogHJOYIOAQ",
        "CAACAgUAAxkBAAICWWluKrTtCBXEOiXcBvqlxX0cJnFCAALMDAACKWQZVydST61VUCbQOAQ",
        "CAACAgUAAxkBAAICWmluKrR-wrcjRBAVIDjJsu62LTDyAAMKAAJaAhhXRcDrnXfFzfE4BA",
        "CAACAgEAAxkBAAICu2luLfK4BdwZFrS4unlGx9hamemjAAL6AANRKQ05EglJURQpGuE4BA",
        "CAACAgEAAxkBAAICvGluLfa9WZXCWCMPA0W3voZY5QhJAALjAANRKQ05F6bHecKQ5Js4BA",
        "CAACAgUAAxkBAAICvWluLgoET5jm90Ot_gGK2yl08sT9AAJfIAACw96pVPZvnczMPP_NOAQ"
        
        
        
    ]
    
    temp_msgs = []
    try:
        # 1. Fast Sticker
        sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=random.choice(stickers))
        temp_msgs.append(sticker_msg)

        # 2. Smooth & Fast Progress Bar
        # Hum 5 steps use karenge par 100% tak jayenge (20% each step)
        progress_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text="🚀 **Laila is loading...**\n`░░░░░░░░░░` 0%", 
            parse_mode='Markdown'
        )
        temp_msgs.append(progress_msg)

        for i in range(1, 6):
            await asyncio.sleep(0.1)  # Super fast speed
            percent = i * 20          # 20, 40, 60, 80, 100
            # 10 blocks total (2 blocks per 20%)
            bar = "█" * (i * 2) + "░" * (10 - (i * 2))
            try:
                await progress_msg.edit_text(
                    text=f"🚀 **Laila is loading...**\n`{bar}` {percent}%", 
                    parse_mode='Markdown'
                )
            except:
                pass

        # 3. Cleanup: Sticker aur Bar hatao
        for msg in temp_msgs:
            try: await msg.delete()
            except: pass
            
    except Exception as e:
        print(f"Animation Error: {e}")

    # --- 🏠 FINAL START MENU ---
    bot_info = await context.bot.get_me()
    keyboard = [
        [
            InlineKeyboardButton("🚀 Features", callback_data="start_features"),
            InlineKeyboardButton("🎮 Game Zone", callback_data="start_games")
        ],
        [InlineKeyboardButton("➕ Add Me To Your Group", url=f"https://t.me/{bot_info.username}?startgroup=true")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    media_url = 'BAACAgUAAxkBAAIDeWlvYGERe7_qUvtpzfTTA2_ixCNtAAKaGwACast5V4jMsXzNS0DmOAQ'
    welcome_text = f"Hey {user_name}! 👋\n\nI'm **Laila**, your advanced AI companion. 💖\n\n👇 **Choose an option:**"

    try:
        # Pehle Video bhejte hain, agar ye video file hai toh chal jayega
        await context.bot.send_video(
            chat_id=chat_id, 
            video=media_url, 
            caption=welcome_text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )
    except Exception:
        try:
            # Agar video fail hua, toh Photo try karein
            await context.bot.send_photo(
                chat_id=chat_id, 
                photo=media_url, 
                caption=welcome_text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
        except Exception:
            # Dono fail hue toh sirf Text message
            await context.bot.send_message(
                chat_id=chat_id, 
                text=welcome_text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )

# --- 🛠 FIXED CALLBACK HANDLER ---
async def start_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    user_name = update.effective_user.first_name
    await query.answer()
    
    # 1. Check karein ki message mein koi bhi media (photo/video/animation) hai ya nahi
    is_media = bool(query.message.photo or query.message.video or query.message.animation or query.message.caption)

    if data == "start_features":
        text = "📂 **Laila's Quick Features**\n\nI can do AI Chat, Image Gen, Lyrics, and more!\n\nUse `/help` for all commands."
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        
    elif data == "start_games":
        text = "🎮 **Laila's Game Zone**\n\n• `/xoxo` - Tic-Tac-Toe\n• `/game` - RPG Menu\n• `/work` - Earn Money"
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        
    elif data == "start_back":
        bot_info = await context.bot.get_me()
        text = f"Hey {user_name}! 👋\n\nI'm **Laila**, your advanced AI companion. 💖"
        kb = [
            [InlineKeyboardButton("🚀 Features", callback_data="start_features"),
             InlineKeyboardButton("🎮 Game Zone", callback_data="start_games")],
            [InlineKeyboardButton("➕ Add Me To Your Group", url=f"https://t.me/{bot_info.username}?startgroup=true")]
        ]

    try:
        # 2. Agar media hai toh edit_message_caption use karein
        if is_media:
            await query.edit_message_caption(
                caption=text, 
                reply_markup=InlineKeyboardMarkup(kb), 
                parse_mode='Markdown'
            )
        else:
            # 3. Agar normal text message hai
            await query.edit_message_text(
                text=text, 
                reply_markup=InlineKeyboardMarkup(kb), 
                parse_mode='Markdown'
            )
    except Exception as e:
        # Kai baar text same hone par Telegram error deta hai, usse bachne ke liye print
        print(f"Button Error: {e}")
        


import time
import psutil
from datetime import datetime

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # --- 1. Ping Calculation & Quality Check ---
    ping_start = time.time()
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    ping_end = time.time()
    ping_ms = int((ping_end - ping_start) * 1000)
    
    # Ping Quality Indicator
    if ping_ms < 200:
        ping_status = "🟢 Smooth"
    elif ping_ms < 700:
        ping_status = "🟡 Medium Load"
    else:
        ping_status = "🔴 High Load"

    # --- 2. Uptime Calculation ---
    uptime = datetime.now() - start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m"

    # --- 3. System Usage ---
    ram = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=None) 
    disk = psutil.disk_usage('/').percent

    # Progress Bar Function
    def get_bar(percentage):
        filled = int(percentage / 10)
        # Custom bar style: ■ aur □ use karke
        return "■" * filled + "□" * (10 - filled)

    # --- 4. PREMIUM DASHBOARD LAYOUT ---
    response_text = (
        "<b>🤖 LAILA SYSTEM METRICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📶 Network Status</b>\n"
        f"├ <b>Ping:</b> <code>{ping_ms}ms</code>\n"
        f"└ <b>State:</b> {ping_status}\n\n"
        f"<b>⏳ Runtime Info</b>\n"
        f"└ <b>Up Since:</b> <code>{uptime_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"<b>⚙️ CPU Load</b>\n"
        f"<code>[{get_bar(cpu)}]</code> <b>{cpu}%</b>\n"
        f"<b>🧠 RAM Usage</b>\n"
        f"<code>[{get_bar(ram)}]</code> <b>{ram}%</b>\n"
        f"<b>💾 Disk Space</b>\n"
        f"<code>[{get_bar(disk)}]</code> <b>{disk}%</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<i>👨‍💻 Maintained by Adhyan</i>"
    )

    # --- 5. MEDIA HANDLING (Video + Photo Support) ---
    # Yahan apna File ID daalein (Video ya Photo ka)
    media_url = 'BAACAgUAAxkBAAIEgGlwaHd7eHlTKkVnj8w60KzRbfnqAAJKHAAC20OAV169e1yH7oFwOAQ'
    
    try:
        # Pehle Video try karein
        await context.bot.send_video(
            chat_id=chat_id,
            video=media_url,
            caption=response_text,
            parse_mode='HTML'
        )
    except Exception:
        try:
            # Agar Video fail ho, to Photo try karein
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=media_url,
                caption=response_text,
                parse_mode='HTML'
            )
        except Exception as e:
            # Agar Media fail ho, to Text bhejein
            logger.error(f"Stats Media Error: {e}")
            await context.bot.send_message(
                chat_id=chat_id, 
                text=response_text, 
                parse_mode='HTML'
            )

'''async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # 1. Ping Calculation
    ping_start = time.time()
    # Chat action dikhana cool lagta hai stats load hote waqt
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    ping_end = time.time()
    ping_ms = int((ping_end - ping_start) * 1000)
    
    # 2. Uptime Calculation
    uptime = datetime.now() - start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m"

    # 3. System Usage
    ram = psutil.virtual_memory().percent
    cpu = psutil.cpu_percent(interval=None) # Interval 1 second bot ko slow kar deta hai, isliye None rakhein
    disk = psutil.disk_usage('/').percent

    # 4. Progress Bars Logic (Custom level indicator)
    def get_bar(percentage):
        filled = int(percentage / 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        return bar

    # --- PREMIUM LAYOUT ---
    response_text = (
        "📊 <b>Laila's System Health</b>\n\n"
        f"⚡ <b>Latency</b>: <code>{ping_ms}ms</code>\n"
        f"⏱️ <b>Uptime</b>: <code>{uptime_str}</code>\n\n"
        f"🖥️ <b>CPU Load</b> [{get_bar(cpu)}]\n"
        f"└ <code>{cpu}%</code>\n\n"
        f"🧠 <b>RAM Usage</b> [{get_bar(ram)}]\n"
        f"└ <code>{ram}%</code>\n\n"
        f"💾 <b>Disk Space</b> [{get_bar(disk)}]\n"
        f"└ <code>{disk}%</code>\n\n"
        f"✨ <b>Maintained by Adhyan</b>"
    )

    photo_file_id = 'AgACAgUAAxkBAAIIKGigVdAK07aRr9QiXpRalahcPO2pAAIL0DEblXUBVSY5LS31XxPSAQADAgADeAADNgQ'
    
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=response_text,
            parse_mode='HTML' # HTML use kiya hai clean styling ke liye
        )
    except Exception as e:
        logger.error(f"Stats Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='HTML')'''


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows detailed bot stats for the admin/sudo user only."""
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
            key_short = key[-10:]
            status = "🟢 Available"
            if time.time() < key_cooldown_until.get(key, 0):
                cooldown_remaining = int(key_cooldown_until[key] - time.time())
                status = f"🟡 Cooldown ({cooldown_remaining}s)"
            api_key_status_text += f"Gemini Key {i+1} (`...{key_short}`): {status}\n"
        else:
            api_key_status_text += f"Gemini Key {i+1}: ❌ Missing\n"
    
    api_key_status_text += f"\nGemma Key: {'✅ Present' if GEMMA_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nDeepSeek Key: {'✅ Present' if DEEPSEEK_API_KEY else '❌ Missing'}" # NEW
    api_key_status_text += f"\nStable Horde Key: {'✅ Present' if STABLE_HORDE_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nPexels Key: {'✅ Present' if PEXELS_API_KEY else '❌ Missing'}"
    api_key_status_text += f"\nGenius Key: {'✅ Present' if GENIUS_ACCESS_TOKEN else '❌ Missing'}"
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
        f" AI Model Mode: `{current_model_mode.capitalize()}`\n"
        f" Custom Welcomes: `{len(welcome_settings_cache)}`\n\n" # NEW
        "**API Status**\n"
        f"{api_key_status_text}"
        "\n\n✨ by Adhyan ✨"
    )
    await msg.delete()
    await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='Markdown')
    logger.info(f"[{chat_id}] /adminstats command used by admin/sudo.")

# --- HELPER for show_chats_command (FIXED) ---
async def get_chat_details(chat_id_str: str, bot: Bot):
    """Asynchronously fetches details for a single chat."""
    try:
        chat_id_int = int(chat_id_str)
        chat = await bot.get_chat(chat_id_int)
        
        if chat.type == 'private':
            return f"• **User**: `{chat.full_name}` (ID: `{chat_id_str}`)"
        else:
            members_count = "N/A"
            try:
                members_count = await bot.get_chat_member_count(chat_id_str)
            except Exception: pass
            
            invite_link = ""
            try:
                if chat.username:
                    invite_link = f"https.t.me/{chat.username}"
                else:
                    # Check if bot can create invite link
                    bot_member = await bot.get_chat_member(chat_id_int, bot.id)
                    if bot_member.can_invite_users:
                        invite = await bot.create_chat_invite_link(chat_id_str, member_limit=1)
                        invite_link = invite.invite_link
                    else:
                        invite_link = "*No permission to get link.*"
            except Exception:
                invite_link = "*No permission to get link.*"

            return (
                f"• **Group**: `{chat.title}` (ID: `{chat_id_str}`)\n"
                f"  Members: `{members_count}`\n"
                f"  Link: {invite_link}"
            )
    except Exception as e:
        return f"• **Unknown Chat**: ID: `{chat_id_str}` (Error: Bot was likely removed or chat deleted)"

# --- /show_chats Command (FIXED) ---
async def show_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    global known_users
    if not known_users:
        load_known_users()
    
    known_chats = list(known_users)
    if not known_chats:
        await context.bot.send_message(chat_id=user_id, text="The bot is not in any groups or private chats yet.")
        return

    msg = await context.bot.send_message(chat_id=user_id, text=f"Fetching details for `{len(known_chats)}` chats. This might take a moment...", parse_mode='Markdown')

    # Create async tasks for all chat detail fetches
    tasks = [get_chat_details(chat_id_str, context.bot) for chat_id_str in known_chats]
    # Run them concurrently
    results = await asyncio.gather(*tasks)
    
    chat_details = [r for r in results if r]
    
    response_text = "✨ **Laila's Chats** ✨\n\n" + "\n\n".join(chat_details)
    
    # Send final result in chunks if it's too long
    if len(response_text) > 4096:
        await msg.edit_text("✨ **Laila's Chats** ✨\n\nThe list is too long, sending as multiple messages...")
        for i in range(0, len(chat_details), 20): # Send 20 chats at a time
            chunk = chat_details[i:i+20]
            chunk_text = "\n\n".join(chunk)
            await context.bot.send_message(user_id, chunk_text, parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await msg.edit_text(response_text, parse_mode='Markdown', disable_web_page_preview=True)
    
    if update.effective_chat.id != user_id:
        await update.message.reply_text("The list of chats has been sent to you privately.")
    
    logger.info(f"[{update.effective_chat.id}] /show_chats command used by sudo user. Response sent privately to {user_id}.")


# --- Sudo-Exclusive Admin Command: Sudo Ban (FIXED & IMPROVED) ---
async def sudo_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bans a user in a group without being a group admin (requires bot to have admin rights)."""
    chat_id = update.effective_chat.id
    
    target_chat_id = None
    target_user_id = None
    target_user_name = "User"

    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        target_user_name = update.message.reply_to_message.from_user.full_name
        target_chat_id = update.effective_chat.id
    elif context.args and len(context.args) == 2 and context.args[0].startswith("-") and context.args[1].isdigit():
        try:
            target_chat_id = int(context.args[0])
            target_user_id = int(context.args[1])
            target_user_name = f"User ID {target_user_id}"
        except ValueError:
             await update.message.reply_text("Invalid `chat_id` or `user_id` format. Please use correct IDs.")
             return
    else:
        await update.message.reply_text("Please reply to a user's message in a group or use the format: `/s_ban <group_chat_id> <user_id>` (Chat ID starts with a -)", parse_mode='Markdown')
        return

    try:
        # Check if bot can ban
        bot_member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        if not (bot_member.status in ['administrator', 'creator'] and bot_member.can_restrict_members):
            await update.message.reply_text(f"I don't have the necessary admin rights (Restrict Members) in chat `{target_chat_id}` to ban a user.")
            return

        # Check if target is also an admin
        target_member = await context.bot.get_chat_member(target_chat_id, target_user_id)
        if target_member.status in ['administrator', 'creator']:
            await update.message.reply_text(f"I cannot ban an administrator in chat `{target_chat_id}`.")
            return
            
        await context.bot.ban_chat_member(target_chat_id, target_user_id)
        
        chat_info = await context.bot.get_chat(target_chat_id)
        chat_title = chat_info.title
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"Sudo Ban Successful! ✅\n\n**User**: {target_user_name} (`{target_user_id}`)\n**Banned from Group**: {chat_title} (`{target_chat_id}`)",
            parse_mode='Markdown'
        )
        logger.info(f"[{chat_id}] Sudo user {update.effective_user.id} banned {target_user_id} in chat {target_chat_id}.")
        
    except Exception as e:
        await update.message.reply_text(f"Could not perform sudo ban in chat `{target_chat_id}`. Error: {e}")
        logger.error(f"[{chat_id}] Error in sudo ban for user {target_user_id} in chat {target_chat_id}: {e}")

# --- NEW Sudo Command: Sudo Unban ---
async def sudo_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unbans a user in a group using the bot's rights."""
    chat_id = update.effective_chat.id
    
    # 1. Argument Parsing
    target_chat_id = None
    target_user_id = None
    target_user_name = "User"

    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        target_user_name = update.message.reply_to_message.from_user.full_name
        target_chat_id = update.effective_chat.id
    elif context.args and len(context.args) == 2 and context.args[0].startswith("-") and context.args[1].isdigit():
        # Usage: /s_unban <target_chat_id> <target_user_id>
        try:
            target_chat_id = int(context.args[0])
            target_user_id = int(context.args[1])
            target_user_name = f"User ID {target_user_id}"
        except ValueError:
             await update.message.reply_text("Invalid `chat_id` or `user_id` format. Please use correct IDs.")
             return
    else:
        await update.message.reply_text("Please reply to a user's message in a group or use the format: `/s_unban <group_chat_id> <user_id>` (Chat ID starts with a -)", parse_mode='Markdown')
        return

    try:
        # 2. Check if bot can unban (it must be an admin with restrict members rights)
        bot_member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        if not (bot_member.status in ['administrator', 'creator'] and bot_member.can_restrict_members):
            await update.message.reply_text(f"I don't have the necessary admin rights (Restrict Members) in chat `{target_chat_id}` to unban a user.")
            return

        # 3. Perform the unban (only_if_banned=True is the default for unban)
        await context.bot.unban_chat_member(target_chat_id, target_user_id)
        
        # 4. Success Message
        chat_title = (await context.bot.get_chat(target_chat_id)).title
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"Sudo Unban Successful! ✅\n\n**User**: {target_user_name} (`{target_user_id}`)\n**Unbanned from Group**: {chat_title} (`{target_chat_id}`)",
            parse_mode='Markdown'
        )
        logger.info(f"[{chat_id}] Sudo user {update.effective_user.id} unbanned {target_user_id} in chat {target_chat_id}.")
        
    except Exception as e:
        await update.message.reply_text(f"Could not perform sudo unban in chat `{target_chat_id}`. Error: {e}")
        logger.error(f"[{chat_id}] Error in sudo unban for user {target_user_id} in chat {target_chat_id}: {e}")

# --- NEW Sudo Command: Sudo Send Message ---
async def sudo_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message to a specific chat ID from the bot."""
    chat_id = update.effective_chat.id
    
    if len(context.args) < 2:
        await update.message.reply_text("Please provide a target chat ID and a message. Usage: `/s_send <chat_id> <message>`", parse_mode='Markdown')
        return

    target_chat_id_str = context.args[0]
    message_text = " ".join(context.args[1:])

    try:
        target_chat_id = int(target_chat_id_str)
    except ValueError:
        await update.message.reply_text("Invalid chat ID provided.")
        return

    try:
        # Send the message
        await context.bot.send_message(chat_id=target_chat_id, text=message_text, parse_mode='Markdown')
        
        await update.message.reply_text(f"Message successfully sent to chat `{target_chat_id}`.")
        logger.info(f"[{chat_id}] Sudo user {update.effective_user.id} sent message to chat {target_chat_id}: {message_text[:50]}...")
    except Exception as e:
        await update.message.reply_text(f"Could not send message to chat `{target_chat_id}`: {e}")
        logger.error(f"[{chat_id}] Error in sudo send message to chat {target_chat_id}: {e}")


# --- ALL OLD MONEY GAME COMMANDS (account, farm, work, etc.) ARE DELETED ---
# --- They are now handled by game.py ---


# --- NEW: Fun Command Data (EXPANDED) ---
TRUTH_QUESTIONS = [
    "What's the most embarrassing thing you've ever done?", "What's a secret you've never told anyone?",
    "Who is your secret crush?", "What's the biggest lie you've ever told?", "What's your biggest fear?",
    "What's something you're self-conscious about?", "Have you ever cheated on a test?",
    "What's the most childish thing you still do?", "What's a weird food combination you love?",
    "Have you ever peed in a swimming pool?", "What's the cringiest text message you've ever sent?",
    "Who do you stalk the most on social media?", "What's the silliest reason you've ever cried?",
    "If you could trade lives with someone for a day, who would it be and why?", "What's your guilty pleasure song?",
    "Have you ever lied to get out of a date?", "What's the most trouble you've ever been in?",
    "What's one thing you would change about your appearance?", "What's a secret talent you have?",
    "What's the worst advice you've ever given someone?", "Have you ever pretended to be sick to skip school or work?",
    "What's the most embarrassing nickname you've ever had?",
]

DARES = [
    "Send a screenshot of your home screen.", "Talk in a funny accent for the next 5 minutes.",
    "Send the 5th picture from your gallery.", "Post 'I love Laila Bot' as your status.",
    "Send a voice message singing a song.", "Let the group choose a new profile picture for you for the next 24 hours.",
    "Try to lick your elbow.", "Spell your name backwards with your nose.", "Send an old, embarrassing photo of yourself.",
    "Text your crush and say 'I know your secret'.", "Do 10 push-ups right now and send a video proof.",
    "Eat a spoonful of a weird condiment (like ketchup or mustard).", "DM a celebrity on Instagram.",
    "Change your name in the group to 'Laila's Biggest Fan' for an hour.", "Try to juggle three random objects.",
    "Speak only in emojis for the next 10 minutes.", "Send a voice note imitating your favorite cartoon character.",
    "Write a short, silly poem about the person who sent the last message.", "Go outside and shout 'I believe in unicorns!'.",
    "Stack as many books as you can on your head and take a picture.", "Draw a self-portrait with your eyes closed and share it.",
    "Find the weirdest item in your room and explain its story.",
]

SLAP_MESSAGES = [
    "slaps {target} around a bit with a large trout! 🐟",
    "gives {target} a high-five. In the face. With a chair. 🪑",
    "summons a mighty slap for {target}! 💥",
    "throws a wet noodle at {target}. It's surprisingly effective. 🍝",
    "tickles {target} until they promise to behave. ✨",
]

ROAST_MESSAGES = [
    "I'd agree with you but then we’d both be wrong.",
    "You have your entire life to be a jerk. Why not take today off?",
    "I'm not insulting you, I'm describing you.",
    "Is your brain made of sponges? Because it seems to soak everything up but does nothing with it.",
    "You're the reason the gene pool needs a lifeguard.",
    "If I wanted to hear from an idiot, I would've watched the news.",
    "I've been called worse things by better people.",
]

# --- NEW: Fun & Game Commands ---
async def truth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    await update.message.reply_text(f"Okay, {user_name}! Your truth is:\n\n**{random.choice(TRUTH_QUESTIONS)}**")

async def dare_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    await update.message.reply_text(f"Here you go, {user_name}! I dare you to:\n\n**{random.choice(DARES)}**")

async def slap_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    slapper = update.effective_user.first_name
    
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.first_name
        message = random.choice(SLAP_MESSAGES).format(target=target)
        await update.message.reply_text(f"{slapper} {message}")
    else:
        await update.message.reply_text(f"{slapper} slaps themselves in confusion! 🤔")

async def coinflip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = random.choice(["Heads", "Tails"])
    await update.message.reply_text(f"The coin landed on... **{result}**! 🪙")

async def roll_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = random.randint(1, 6)
    await update.message.reply_text(f"You rolled a... **{result}**! 🎲")

async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts a number guessing game in the chat."""
    chat_id = update.effective_chat.id
    if guessing_games[chat_id].get('active', False):
        await update.message.reply_text("A game is already in progress in this chat! Use /stopgame to end it.")
        return
    
    secret_number = random.randint(1, 100)
    guessing_games[chat_id] = {'number': secret_number, 'attempts': 0, 'active': True}
    
    logger.info(f"[{chat_id}] New guessing game started. Number is {secret_number}.")
    await update.message.reply_text("🎲 **Number Guessing Game Started!** 🎲\n\nI'm thinking of a number between 1 and 100. Try to guess it by sending a number in the chat!")

async def stop_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stops the current number guessing game."""
    chat_id = update.effective_chat.id
    if not guessing_games[chat_id].get('active', False):
        await update.message.reply_text("There's no game in progress to stop.")
        return
        
    secret_number = guessing_games[chat_id].get('number')
    guessing_games[chat_id].clear()
    
    await update.message.reply_text(f"Game stopped! The number was {secret_number}. Use /startgame to play again.")
    logger.info(f"[{chat_id}] Game stopped by user.")


# ---  NEW UTILITY AND FUN COMMANDS (15+) ---

# Utility Commands
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets the weather for a specified city using OpenWeatherMap or Visual Crossing as a fallback."""
    if not context.args:
        await update.message.reply_text("Please provide a city name. Example: `/weather London`")
        return

    city = " ".join(context.args)
    
    # Try OpenWeatherMap first
    if WEATHER_API_KEY:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        try:
            response = requests.get(url).json()
            if response["cod"] == 200:
                main = response["main"]
                wind = response["wind"]
                weather_desc = response["weather"][0]["description"]
                weather_icon = response["weather"][0]["icon"]
                
                icon_map = {
                    "01": "☀️", "02": "🌤️", "03": "☁️", "04": "☁️", "09": "🌧️",
                    "10": "🌦️", "11": "⛈️", "13": "❄️", "50": "🌫️"
                }
                emoji = icon_map.get(weather_icon[:2], "🌡️")
                
                weather_text = (
                    f"**Weather in {response['name']}, {response['sys']['country']}** {emoji}\n\n"
                    f"🌡️ **Temperature**: {main['temp']}°C (Feels like: {main['feels_like']}°C)\n"
                    f"📊 **Pressure**: {main['pressure']} hPa\n"
                    f"💧 **Humidity**: {main['humidity']}%\n"
                    f"🌬️ **Wind**: {wind['speed']} m/s\n"
                    f"📜 **Condition**: {weather_desc.title()}"
                )
                await update.message.reply_text(weather_text, parse_mode='Markdown')
                return
        except Exception as e:
            logger.error(f"Error in /weather command with OpenWeatherMap: {e}")

    # Fallback to Visual Crossing
    if VISUALCROSSING_API_KEY:
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{city}?unitGroup=metric&key={VISUALCROSSING_API_KEY}&contentType=json"
        try:
            response = requests.get(url).json()
            if "address" in response:
                current = response["currentConditions"]
                
                icon_map = {
                    "clear-day": "☀️", "clear-night": "🌙", "partly-cloudy-day": "🌤️",
                    "partly-cloudy-night": "☁️", "cloudy": "☁️", "rain": "🌧️",
                    "showers-day": "🌦️", "showers-night": "🌦️", "snow": "❄️", "thunder-rain": "⛈️",
                    "fog": "🌫️"
                }
                emoji = icon_map.get(current.get("icon"), "🌡️")

                weather_text = (
                    f"**Weather in {response['resolvedAddress']}** {emoji}\n\n"
                    f"🌡️ **Temperature**: {current.get('temp', 'N/A')}°C (Feels like: {current.get('feelslike', 'N/A')}°C)\n"
                    f"💧 **Humidity**: {current.get('humidity', 'N/A')}%\n"
                    f"🌬️ **Wind**: {current.get('windspeed', 'N/A')} km/h\n"
                    f"📜 **Condition**: {current.get('conditions', 'N/A')}"
                )
                await update.message.reply_text(weather_text, parse_mode='Markdown')
                return
        except Exception as e:
            await update.message.reply_text("An error occurred while fetching weather data.")
            logger.error(f"Error in /weather command with Visual Crossing: {e}")
            return

    await update.message.reply_text("Sorry, both weather API services are currently unavailable or keys are missing.")


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ <b>Bhai, symbol to likhun!</b>\nUdaharon: <code>/crypto btc</code>", parse_mode='HTML')
        return
        
    symbol = context.args[0].strip().upper()
    msg = await update.message.reply_text(f"🔍 <b>{symbol}</b>-er daam khujchi...", parse_mode='HTML')

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Real-time Crypto Price fetch (Directly in USD & INR)
            # CryptoCompare API khub stable ar block hoy na
            url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol}&tsyms=USD,INR"
            response = await client.get(url)
            data = response.json()

            if "RAW" in data and symbol in data["RAW"]:
                info = data["RAW"][symbol]["USD"]
                inr_info = data["RAW"][symbol]["INR"]
                
                usd_price = info.get('PRICE', 0)
                inr_price = inr_info.get('PRICE', 0)
                change_24h = info.get('CHANGEPCT24HOUR', 0)
                high_24h = info.get('HIGH24HOUR', 0)
                
                emoji = "🚀" if change_24h >= 0 else "🔻"
                graph = "📈" if change_24h >= 0 else "📉"
                status = "🟢 Bullish" if change_24h >= 0 else "🔴 Bearish"

                # --- PREMIUM UI LAYOUT ---
                crypto_text = (
                    f"✨ <b>{symbol} Market Report</b> {emoji}\n\n"
                    f"💰 <b>Price (USD)</b>: <code>${usd_price:,.2f}</code>\n"
                    f"🇮🇳 <b>Price (INR)</b>: <code>₹{inr_price:,.2f}</code>\n\n"
                    f"📊 <b>24h Change</b>: <code>{change_24h:.2f}%</code> {graph}\n"
                    f"🌡️ <b>Status</b>: <b>{status}</b>\n"
                    f"🏔️ <b>High Today</b>: <code>${high_24h:,.2f}</code>\n\n"
                    f"ℹ️ <i>Daam copy korte opore click koron.</i>"
                )
                await msg.edit_text(crypto_text, parse_mode='HTML')
            else:
                await msg.edit_text(
                    f"❌ <b>'{symbol}' pawa gelo na!</b>\n\n"
                    f"Sothik bhabe likhun: <code>BTC</code>, <code>SOL</code>, <code>ETH</code>, <code>DOGE</code>", 
                    parse_mode='HTML'
                )
                
    except Exception as e:
        print(f"Crypto Error: {e}")
        await msg.edit_text("⚠️ Server ektu busy, pore try koron!")
        
async def define_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets the definition of a word."""
    if not context.args:
        await update.message.reply_text("Please provide a word to define. Example: `/define integrity`")
        return
    
    word = " ".join(context.args)
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    
    try:
        response = requests.get(url).json()
        if isinstance(response, list) and "meanings" in response[0]:
            meanings = response[0]['meanings']
            definition_text = f"**Definitions for: {word.title()}**\n\n"
            for meaning in meanings[:3]: # Show first 3 parts of speech
                part_of_speech = meaning.get('partOfSpeech', '')
                definition_text += f"_{part_of_speech.title()}_\n"
                for i, definition in enumerate(meaning['definitions'][:2]): # Show first 2 definitions
                    definition_text += f"{i+1}. {definition['definition']}\n"
                    if 'example' in definition:
                        definition_text += f"   *Example: \"{definition['example']}\"*\n"
                definition_text += "\n"
            await update.message.reply_text(definition_text, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"Sorry, I couldn't find a definition for `{word}`.")
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching the definition.")
        logger.error(f"Error in /define command: {e}")

async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates a QR code from text."""
    if not context.args:
        await update.message.reply_text("Please provide text or a link to generate a QR code. Example: `/qr https://google.com`")
        return
        
    text = " ".join(context.args)
    encoded_text = urllib.parse.quote(text)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={encoded_text}"
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=qr_url,
        caption=f"Here is the QR code for: `{text}`",
        parse_mode='Markdown'
    )

async def shorten_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortens a URL using TinyURL."""
    if not TINYURL_API_KEY:
        await update.message.reply_text("Sorry, the URL shortener API key is not configured.")
        return
    if not context.args:
        await update.message.reply_text("Please provide a URL to shorten. Example: `/shorten <your_long_url>`")
        return
        
    url = context.args[0]
    api_url = f"https://api.tinyurl.com/create?api_token={TINYURL_API_KEY}"
    payload = {"url": url, "domain": "tiny.one"} # Using tiny.one domain
    
    try:
        response = requests.post(api_url, json=payload)
        if response.status_code == 200 and response.json()["code"] == 0:
            short_url = response.json()["data"]["tiny_url"]
            await update.message.reply_text(f"🔗 **Shortened URL**:\n{short_url}")
        else:
            error = response.json().get("errors", ["Unknown error"])[0]
            await update.message.reply_text(f"Could not shorten URL. Error: {error}")
    except Exception as e:
        await update.message.reply_text("An error occurred while shortening the URL.")
        logger.error(f"Error in /shorten command: {e}")

async def ud_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Searches Urban Dictionary."""
    if not context.args:
        await update.message.reply_text("Please provide a term to search on Urban Dictionary. Example: `/ud bruh`")
        return
    term = " ".join(context.args)
    url = f"http://api.urbandictionary.com/v0/define?term={term}"
    try:
        response = requests.get(url).json()
        if response and response.get('list'):
            top_def = response['list'][0]
            definition = re.sub(r'[\[\]]', '', top_def['definition'])
            example = re.sub(r'[\[\]]', '', top_def['example'])
            result_text = (
                f"**{top_def['word']}** on Urban Dictionary\n\n"
                f"**Definition**:\n{definition}\n\n"
                f"**Example**:\n_{example}_\n\n"
                f"👍 {top_def['thumbs_up']} | 👎 {top_def['thumbs_down']}"
            )
            await update.message.reply_text(result_text)
        else:
            await update.message.reply_text(f"Couldn't find a definition for `{term}` on Urban Dictionary.")
    except Exception as e:
        await update.message.reply_text("An error occurred while searching Urban Dictionary.")
        logger.error(f"Error in /ud command: {e}")

# --- FIXED: /paste command ---


# Fun Commands
async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches a random meme."""
    url = "https://meme-api.com/gimme"
    try:
        response = requests.get(url).json()
        if response and response.get('url'):
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=response['url'],
                caption=f"**{response['title']}**\n_r/{response['subreddit']}_",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("Couldn't fetch a meme right now, sorry!")
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching a meme.")
        logger.error(f"Error in /meme command: {e}")

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tells a random joke."""
    url = "https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit&type=single"
    try:
        response = requests.get(url).json()
        if not response['error']:
            await update.message.reply_text(f"**Here's a joke for you:**\n\n_{response['joke']}_")
        else:
            await update.message.reply_text("I'm out of jokes for now, try again later!")
    except Exception as e:
        await update.message.reply_text("An error occurred while getting a joke.")
        logger.error(f"Error in /joke command: {e}")

async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches a random inspirational quote."""
    url = "https://api.quotable.io/random"
    try:
        response = requests.get(url).json()
        await update.message.reply_text(f"**Here's a quote:**\n\n>_{response['content']}_\n\n— **{response['author']}**", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching a quote.")
        logger.error(f"Error in /quote command: {e}")

async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roasts a user."""
    roaster = update.effective_user.first_name
    roast_text = random.choice(ROAST_MESSAGES)
    
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.first_name
        await update.message.reply_text(f"Hey {target}, {roast_text}")
    else:
        await update.message.reply_text(f"{roaster}, here's a thought for you: {roast_text}")

async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rates something on a scale of 1-10."""
    if not context.args:
        await update.message.reply_text("What should I rate? Example: `/rate my new haircut`")
        return
        
    thing_to_rate = " ".join(context.args)
    rating = random.randint(1, 10)
    comment = ""
    if rating <= 3:
        comment = "Oof, not great."
    elif rating <= 6:
        comment = "Pretty average, I'd say."
    elif rating <= 9:
        comment = "Wow, that's really good!"
    else:
        comment = "Absolutely perfect! 10/10!"
        
    await update.message.reply_text(f"I'd rate **{thing_to_rate}** a... **{rating}/10**.\n{comment}")

async def catfact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets a random cat fact."""
    url = "https://catfact.ninja/fact"
    try:
        response = requests.get(url).json()
        await update.message.reply_text(f"🐱 **Did you know?**\n\n_{response['fact']}_")
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching a cat fact.")
        logger.error(f"Error in /catfact command: {e}")

async def dogfact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets a random dog fact."""
    url = "https://dog.ceo/api/breeds/image/random" # Using this to get a fact and an image
    try:
        fact_res = requests.get("https://dogapi.dog/api/v2/facts").json()
        img_res = requests.get("https://dog.ceo/api/breeds/image/random").json()
        
        fact = fact_res['data'][0]['attributes']['body']
        img_url = img_res['message']
        
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img_url,
            caption=f"🐶 **Did you know?**\n\n_{fact}_",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching a dog fact.")
        logger.error(f"Error in /dogfact command: {e}")

async def advice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gives a random piece of advice."""
    url = "https://api.adviceslip.com/advice"
    try:
        response = requests.get(url).json()
        await update.message.reply_text(f"💡 **Here's some advice:**\n\n_{response['slip']['advice']}_")
    except Exception as e:
        await update.message.reply_text("An error occurred while fetching advice.")
        logger.error(f"Error in /advice command: {e}")


# --- Message Processing Logic ---
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global total_messages_processed
    chat_id = update.effective_chat.id
    
    # --- FIX: Handle both new and edited messages ---
    message = update.message or update.edited_message
    if not message:
        # This should theoretically not be reachable due to filters, but it's a safe guard.
        return

    # --- NEW: Guessing game logic ---
    if guessing_games[chat_id].get('active', False) and message.text and message.text.isdigit():
        guess = int(message.text)
        game = guessing_games[chat_id]
        game['attempts'] += 1
        
        if guess < game['number']:
            await message.reply_text("Too low! Try a higher number. ⬆️")
        elif guess > game['number']:
            await message.reply_text("Too high! Try a lower number. ⬇️")
        else:
            attempts = game['attempts']
            await message.reply_text(f"🎉 **Correct!** You guessed the number **{game['number']}** in {attempts} attempts! 🎉\n\nUse /startgame to play again.")
            logger.info(f"[{chat_id}] Game won. Number was {game['number']} in {attempts} tries.")
            guessing_games[chat_id].clear()
        return # Stop further processing if it was a game guess

    global_bot_enabled = global_bot_status
    chat_enabled = bot_status[chat_id]
    is_private_chat = update.effective_chat.type == 'private'
    
    if message and message.text and message.text.startswith('/'):
        # Check for auto-download right before returning for command
        # This allows /youtube to work as intended, and auto-detection in text to work.
        if ("youtube.com" in message.text or "youtu.be" in message.text) and not message.text.startswith('/youtube'):
            threading.Thread(target=lambda: asyncio.run(handle_youtube_link(update, context, message.text)), daemon=True).start()
        return
    
    if not global_bot_enabled or (not is_private_chat and not chat_enabled):
        return
    
    bot_username = (await context.bot.get_me()).username
    user_message = message.text or message.caption
    user_id = update.effective_user.id
    user_full_name = update.effective_user.full_name
    
    if str(chat_id) not in known_users:
        known_users.add(str(chat_id))
        save_chat_id(chat_id)
    
    # --- Couple and GC Leaderboard user tracking ---
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
    
    # --- FIX: Removed AI-based pre-checks to save API quota ---
    # if await is_name_query_ai(user_message):
    #     await handle_name_query(update, context)
    #     return
        
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id
    is_mention = f"@{bot_username.lower()}" in user_message.lower() or "laila" in user_message.lower()
    
    should_use_ai = is_private_chat or is_reply_to_bot or is_mention
    
    # --- FIX: Removed AI-based fallback check to save API quota ---
    # if not should_use_ai:
    #     if await is_message_for_laila(user_message):
    #         should_use_ai = True
    #     else:
    #         return
            
    if should_use_ai:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            response_text = await get_bot_response(user_message, chat_id, bot_username, should_use_ai=True, update=update)
            if response_text:
                await message.reply_text(response_text, parse_mode='Markdown')
                add_to_history(chat_id, 'user', user_message)
                add_to_history(chat_id, 'model', response_text)
                total_messages_processed += 1
                logger.info(f"[{chat_id}] Sent response to {user_id}: {response_text[:50]}...")
        except Exception as e:
            logger.error(f"Error processing message for chat {chat_id}: {e}", exc_info=True)
            try:
                await message.reply_text("An unexpected error occurred. Please try again later.")
            except Exception as reply_e:
                logger.error(f"Failed to send error reply: {reply_e}")

# --- NEW: Speech-to-Text Handler ---
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles voice messages by converting them to text and processing them."""
    chat_id = update.effective_chat.id
    
    # Bot logic check
    global_bot_enabled = global_bot_status
    chat_enabled = bot_status[chat_id]
    is_private_chat = update.effective_chat.type == 'private'
    if not global_bot_enabled or (not is_private_chat and not chat_enabled):
        return

    # --- FIX: Get message object ---
    message = update.message or update.edited_message
    if not message or not message.voice:
        return

    file_id = message.voice.file_id
    
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
                await message.reply_text(response_text, parse_mode='Markdown')
                add_to_history(chat_id, 'user', transcribed_text)
                add_to_history(chat_id, 'model', response_text)

    except sr.UnknownValueError:
        await message.reply_text("Sorry, I couldn't understand the audio. 😕")
    except sr.RequestError as e:
        await message.reply_text("Sorry, my speech recognition service is down. Please try again later.")
        logger.error(f"Speech recognition request error: {e}")
    except FileNotFoundError:
        # This error happens if ffmpeg is not installed
        await message.reply_text("Sorry, I can't process voice messages right now. The `ffmpeg` tool might be missing on the server.")
        logger.error("ffmpeg not found. Please install it to enable voice message processing.")
    except Exception as e:
        await message.reply_text("An error occurred while processing your voice message.")
        logger.error(f"Error processing voice message: {e}", exc_info=True)
    finally:
        # 5. Clean up temporary files (Blocking operations, run in thread)
        def cleanup(ogg, wav):
            if os.path.exists(ogg): os.remove(ogg)
            if os.path.exists(wav): os.remove(wav)

        if 'ogg_path' in locals() and 'wav_path' in locals():
            # Await the cleanup thread
            await asyncio.to_thread(cleanup, ogg_path, wav_path)

# ------------------------------------------------------------------
# --- ✨ REWRITTEN: WELCOME MESSAGE FOR NEW GROUP MEMBERS ✨ ---
# ------------------------------------------------------------------
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a stylish welcome message (custom or default) when new members join."""
    
    chat = update.effective_chat
    chat_id = str(chat.id)
    
    # --- FIX: Get message object ---
    message = update.message or update.edited_message
    if not message:
        return

    # --- Define Default Welcome Settings ---
    # Using the reliable photo file_id from /start as the default
    DEFAULT_WELCOME_MEDIA_ID = 'BAACAgUAAxkBAAI8yWkd6Bm0RD0lDq5wQ0_6M5Wv7nLmAAKnHAACUybxVApN-dVoWaFGNgQ'
    DEFAULT_WELCOME_MEDIA_TYPE = 'video'
    DEFAULT_WELCOME_MESSAGE_TEMPLATE = (
        "🎉 **Welcome to {group_name}!** 🎉\n\n"
        "Hey {user_mention}, we're thrilled to have you join us! We hope you have a great time here.\n\n"
        "Here are your details:\n"
        "  •  **Name**: `{user_name}`\n"
        "  •  **Telegram ID**: `{user_id}`\n\n"
        "Feel free to introduce yourself and dive into the conversation! 😊\n"
        "You can also start playing the new game with `/game`!"
    )

    # --- Get Custom Welcome Settings from Cache ---
    custom_settings = welcome_settings_cache.get(chat_id)
    
    welcome_message_template = DEFAULT_WELCOME_MESSAGE_TEMPLATE
    welcome_media_id = DEFAULT_WELCOME_MEDIA_ID
    welcome_media_type = DEFAULT_WELCOME_MEDIA_TYPE

    if custom_settings:
        welcome_message_template = custom_settings.get('message') or DEFAULT_WELCOME_MESSAGE_TEMPLATE
        welcome_media_id = custom_settings.get('media_id') or DEFAULT_WELCOME_MEDIA_ID
        welcome_media_type = custom_settings.get('media_type') or DEFAULT_WELCOME_MEDIA_TYPE

    for member in message.new_chat_members:
        # Don't welcome the bot itself
        if member.id == context.bot.id:
            continue

        # --- Create Placeholders ---
        user_mention = f"[{member.full_name}](tg://user?id={member.id})"
        
        # --- Format the Caption ---
        try:
            welcome_caption = welcome_message_template.format(
                user_mention=user_mention,
                user_name=member.full_name,
                user_id=member.id,
                group_name=chat.title
            )
        except KeyError as e:
            logger.warning(f"Invalid placeholder {e} in custom welcome for chat {chat_id}. Using default message.")
            welcome_caption = DEFAULT_WELCOME_MESSAGE_TEMPLATE.format(
                user_mention=user_mention,
                user_name=member.full_name,
                user_id=member.id,
                group_name=chat.title
            )

        # --- Send the Media and Caption ---
        try:
            if welcome_media_type == 'photo':
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=welcome_media_id,
                    caption=welcome_caption,
                    parse_mode='Markdown'
                )
            elif welcome_media_type == 'video':
                await context.bot.send_video(
                    chat_id=chat.id,
                    video=welcome_media_id,
                    caption=welcome_caption,
                    parse_mode='Markdown'
                )
            elif welcome_media_type == 'animation':
                await context.bot.send_animation(
                    chat_id=chat.id,
                    animation=welcome_media_id,
                    caption=welcome_caption,
                    parse_mode='Markdown'
                )
            else:
                # Fallback if media type is unknown or invalid
                raise ValueError("Invalid media type")

            logger.info(f"Sent welcome message to {member.full_name} (ID: {member.id}) in group '{chat.title}' (ID: {chat.id}).")
        
        except Exception as e:
            logger.error(f"Failed to send welcome media (ID: {welcome_media_id}) to chat {chat.id}. Error: {e}", exc_info=True)
            # --- Fallback to Text-Only Message ---
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=welcome_caption,
                    parse_mode='Markdown'
                )
                logger.info(f"Sent FALLBACK welcome text to {member.full_name} in group {chat.id}.")
            except Exception as text_e:
                logger.error(f"Failed to send fallback welcome text to chat {chat.id}. Error: {text_e}")


# ------------------------------------------------------------------
# --- ✨ NEW: ADMIN COMMANDS FOR CUSTOM WELCOME ✨ ---
# ------------------------------------------------------------------

async def set_welcome_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets a custom welcome message for the group."""
    chat = update.effective_chat
    user_id = update.effective_user.id
    
    if chat.type == 'private':
        await update.message.reply_text("This command only works in groups.")
        return
    if not await is_admin(context.bot, chat.id, user_id):
        await update.message.reply_text("Sorry, you must be an admin to set the welcome message.")
        return
    
    message = update.message.text.split(' ', 1)
    if len(message) < 2 or not message[1].strip():
        await update.message.reply_text(
            "Please provide a welcome message.\n\n"
            "**Placeholders:**\n"
            "`{user_mention}` - Mentions the new user (e.g., @JohnDoe)\n"
            "`{user_name}` - User's full name (e.g., John Doe)\n"
            "`{user_id}` - User's Telegram ID\n"
            "`{group_name}` - This group's name\n\n"
            "**Example:**\n"
            "`/setwelcome Welcome {user_mention} to {group_name}! Your ID is {user_id}.`",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        return
    
    custom_message = message[1].strip()
    
    # Simple validation
    if "{user_mention}" not in custom_message and "{user_name}" not in custom_message:
         await update.message.reply_text("Your message must include at least `{user_mention}` or `{user_name}` so the user knows they are being welcomed!")
         return

    if save_welcome_setting(str(chat.id), message=custom_message):
        await update.message.reply_text("✅ New welcome message has been set!")
    else:
        await update.message.reply_text("❌ An error occurred while saving the message to the database.")

async def set_welcome_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets a custom welcome media by replying to it."""
    chat = update.effective_chat
    user_id = update.effective_user.id
    
    if chat.type == 'private':
        await update.message.reply_text("This command only works in groups.")
        return
    if not await is_admin(context.bot, chat.id, user_id):
        await update.message.reply_text("Sorry, you must be an admin to set the welcome media.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a Photo, Video, or GIF with this command.")
        return
    
    reply_msg = update.message.reply_to_message
    media_id = None
    media_type = None
    
    if reply_msg.photo:
        media_id = reply_msg.photo[-1].file_id
        media_type = "photo"
    elif reply_msg.video:
        media_id = reply_msg.video.file_id
        media_type = "video"
    elif reply_msg.animation:
        media_id = reply_msg.animation.file_id
        media_type = "animation"
    else:
        await update.message.reply_text("That's not a Photo, Video, or GIF. Please reply to a valid media file.")
        return

    if save_welcome_setting(str(chat.id), media_id=media_id, media_type=media_type):
        await update.message.reply_text(f"✅ New welcome {media_type} has been set!")
    else:
        await update.message.reply_text("❌ An error occurred while saving the media to the database.")

async def reset_welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resets the group's welcome settings to default."""
    chat = update.effective_chat
    user_id = update.effective_user.id
    
    if chat.type == 'private':
        await update.message.reply_text("This command only works in groups.")
        return
    if not await is_admin(context.bot, chat.id, user_id):
        await update.message.reply_text("Sorry, you must be an admin to do this.")
        return
    
    if remove_welcome_setting(str(chat.id)):
        await update.message.reply_text("✅ Welcome settings have been reset to default.")
    else:
        await update.message.reply_text("❌ An error occurred (or no settings were found to reset).")

# --- REVAMPED HELP Command (with new welcome commands) ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    # Header Image ya Emojis se start karte hain
    help_text = (
        "✨ **Laila Bot Help Menu** ✨\n\n"
        " I am your all-in-one assistant! Click the buttons below to check the commands.\n\n"
        "💡 *Tip:  Select the Category !*"
    )

    keyboard = [
        [
            InlineKeyboardButton("💬 General", callback_data="help_gen"),
            InlineKeyboardButton("🎨 AI & Media", callback_data="help_media")
        ],
        [
            InlineKeyboardButton("🛠️ Utilities", callback_data="help_util"),
            InlineKeyboardButton("🎮 Games", callback_data="help_game")
        ],
        [
            InlineKeyboardButton("🔒 Admin", callback_data="help_admin")
        ]
    ]

    # Sudo button sirf admin ko dikhega
    if user_id == str(BROADCAST_ADMIN_ID) or user_id in sudo_users:
        keyboard.append([InlineKeyboardButton("👑 Sudo Panel", callback_data="help_sudo")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Agar ye callback se aaya hai toh edit karega, warna naya message
    if update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')


async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Back button setup
    back_button = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="help_main")]]
    
    texts = {
        "help_gen": (
            "**💬 General Commands**\n\n"
            "• `/start` - Bot start karein\n"
            "• `/stats` - Live performance\n"
            "• `/id` - Your & Chat ID\n"
            "• `/about` - about Laila"
        ),
        "help_media": (
            "**🎨 AI & Media**\n\n"
            "• `/gen <prompt>` - AI Image Generation\n"
            "• `/lyrics <song>` - Song lyrics (Tap to Copy)\n"
            "• `/youtube <link>` - Video downloader \n"
            "• `/img <query>` - HD Photo search"
        ),
        "help_util": (
            "**🛠️ Utility Commands**\n\n"
            "• `/crypto <symbol>` - Live Crypto Rates\n"
            "• `/tr <lang> <text>` - Translation\n"
            "• `/weather <city>` - Live Weather\n"
            "• `/qr <text>` - Generate QR Code\n"
            "• `/shorten <url>` - URL Shortner"
        ),
        "help_game": (
            "**🎮 Games (Only Best Ones)**\n\n"
            "• `/xoxo` - Tic-Tac-Toe \n"
            "• `/startgame` - Number guessing game\n"
            "• `/stopgame` - Game stop\n"
            "• `/endxoxo` - Tic-Tac-Toe end"
        ),
        "help_admin": (
            "**🔒 Admin Only**\n\n"
            "• `/on` | `/off` -  bot activate/deactivate\n"
            "• `/ban` | `/mute` | `/kick` - User management\n"
            "• `/setwelcome` - Custom welcome message"
        ),
        "help_sudo": (
            "👑 **Sudo / Owner Only**\n\n"
            "• `/broadcast` - broadcast\n"
            "• `/poweroff` - Global Shutdown\n"
            "• `/poweron` - Global Poweron\n"
            "• `/adminstats` - Health report"
        )
    }

    if data == "help_main":
        await help_command(update, context)
    elif data in texts:
        await query.edit_message_text(texts[data], reply_markup=InlineKeyboardMarkup(back_button), parse_mode='Markdown')



    
async def spawn_boss_event(context: ContextTypes.DEFAULT_TYPE):
    """Randomly drops a treasure in a group chat."""
    # List of group IDs the bot is active in (from your known_users/groups)
    chat_id = "YOUR_MAIN_GROUP_ID" 
    
    boss_msg = (
        "👾 **BOSS ALERT: THE TAX COLLECTOR**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "A corrupt official is passing through the chat! \n"
        "The first person to **ATTACK** him gets his bag of gold!\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 **Tap the button below to strike!**"
    )
    
    keyboard = [[InlineKeyboardButton("⚔️ ATTACK!", callback_data="event_boss_attack")]]
    await context.bot.send_message(chat_id, boss_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
# --- ABOUT Command ---
async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = (
        "❤️ **About Laila** ❤️\n\n"
        "I am Laila, an AI assistant created by AdhyanXlive. My purpose is to chat with you and provide answers to your questions.\n\n"
        "My intelligence comes from a family of large language models, allowing me to provide helpful and accurate responses.\n\n"
        "✨ **Creator**: Adhyan\n"
        "✨ **Version**: 3.1 (Custom Welcome Update)\n\n" # Version updated
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
        # Check if user is the main owner OR a listed sudo user
        if user_id == str(BROADCAST_ADMIN_ID) or user_id in sudo_users:
            await handler(update, context)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is restricted to sudo users only.")
            logger.warning(f"Unauthorized access to restricted command by user {user_id} in chat {update.effective_chat.id}")
    return wrapper
    

# --- Global variables top par rehne do ---
'''trivia_bot = None
summary_bot = None

async def post_init(application: Application) -> None:
    """Ye background tasks ko sahi event loop mein start karega"""
    global trivia_bot, summary_bot
    
    # 🚨 ZAROORI: Bots ko yahan initialize karna sabse safe hai 
    # taaki 'ExtBot' properly initialize ho chuka ho.
    if trivia_bot is None:
        from trivia_manager import TriviaGame
        trivia_bot = TriviaGame(application,known_users)
    
    if summary_bot is None:
        from summary_manager import SummaryManager
        summary_bot = SummaryManager(application, known_users)

    try:
        # Background tasks start karein
        asyncio.create_task(trivia_bot.start_loop())
        asyncio.create_task(summary_bot.run_scheduler())
        logger.info("✅ Laila's Background Tasks (Trivia & Summary) Started.")
    except Exception as e:
        logger.error(f"❌ Error starting background tasks: {e}")

summary_bot = SummaryManager(application, known_users)
trivia_bot = TriviaGame(application, known_users)
asyncio.create_task(trivia_bot.start_loop())
asyncio.create_task(summary_bot.run_scheduler())
    
logger.info("✅ Trivia and Summary bots are now LIVE in background.")
'''
# --- 1. Global Variables ---
# --- 1. Global variables (Top par) ---
trivia_bot = None
summary_bot = None

# --- 2. Post Init (Sahi jagah initialization ke liye) ---
async def post_init(application: Application) -> None:
    """Ye background tasks ko sahi event loop mein start karega"""
    global trivia_bot, summary_bot
    
    # IMPORT AND INITIALIZE INSIDE POST_INIT
    from trivia_manager import TriviaGame
    from summary_manager import SummaryManager
    
    # known_users load_known_users() se globally available hoga
    if trivia_bot is None:
        trivia_bot = TriviaGame(application, known_users)
    
    if summary_bot is None:
        summary_bot = SummaryManager(application, known_users)

    try:
        # Background tasks start karein
        asyncio.create_task(trivia_bot.start_loop())
        asyncio.create_task(summary_bot.run_scheduler())
        logger.info("✅ Laila's Background Tasks (Trivia & Summary) Started.")
    except Exception as e:
        logger.error(f"❌ Error starting background tasks: {e}")

# --- 3. Main function ---
def main() -> None:
    global trivia_bot, summary_bot

    # A. PEHLE: Data load karein
    client, error = get_google_sheet_connection()
    load_known_users()
    load_sudo_users()
    load_welcome_settings()

    # B. PHIR: Application Build karein
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init) 
        .build()
    )

    # C. HANDLERS (Order is perfect)
    
    # Trivia buttons (Lambda is important here)
    application.add_handler(CallbackQueryHandler(
        lambda u, c: trivia_bot.handle_callback(u, c) if trivia_bot else None, 
        pattern="^trivia:"
    ))
    
    # Summary recording (Group 1)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        lambda u, c: summary_bot.record_message(u, c) if summary_bot else None
    ), group=1)
    
    # Commands
    application.add_handler(CommandHandler("testsummary", lambda u, c: summary_bot.test_summary_command(u, c) if summary_bot else None))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("id", get_id_command))
    
    # Media & AI Commands
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("gen", gen_command))
    application.add_handler(CommandHandler("img", img_command))
    application.add_handler(CommandHandler("lyrics", lyrics_command))
    

    # Utility Commands (NEW)
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("crypto", crypto_command))
    application.add_handler(CommandHandler("define", define_command))
    application.add_handler(CommandHandler("qr", qr_command))
    application.add_handler(CommandHandler("shorten", shorten_command))
    application.add_handler(CommandHandler("ud", ud_command))

    # Fun & Game Commands
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("truth", truth_command))
    application.add_handler(CommandHandler("dare", dare_command))
    application.add_handler(CommandHandler("slap", slap_command))
    application.add_handler(CommandHandler("roll", roll_command))
    application.add_handler(CommandHandler("coinflip", coinflip_command))
    application.add_handler(CommandHandler("startgame", start_game_command))
    application.add_handler(CommandHandler("stopgame", stop_game_command))
    # Fun Commands (NEW)
    application.add_handler(CommandHandler("meme", meme_command))
    application.add_handler(CommandHandler("joke", joke_command))
    application.add_handler(CommandHandler("quote", quote_command))
    application.add_handler(CommandHandler("roast", roast_command))
    application.add_handler(CommandHandler("rate", rate_command))
    application.add_handler(CommandHandler("catfact", catfact_command))
    application.add_handler(CommandHandler("dogfact", dogfact_command))
    application.add_handler(CommandHandler("advice", advice_command))
    
    # --- NEW: Added Game Commands (Rob, Kill, Bank) ---
    application.add_handler(CommandHandler("rob", game.handle_rob))
    application.add_handler(CommandHandler("kill", game.handle_kill))
    application.add_handler(CommandHandler("deposit", game.handle_deposit))
    application.add_handler(CommandHandler("withdraw", game.handle_withdraw))
    application.add_handler(CommandHandler("gift", game.handle_gift))
    application.add_handler(CommandHandler("start", game.start_game))
    application.add_handler(CommandHandler("heal", game.handle_heal))
    application.add_handler(CommandHandler("slots", game.handle_slots))
    # --- GAME COMMANDS ---
    application.add_handler(CommandHandler("game", game.handle_game_menu))
    application.add_handler(CommandHandler("daily", game.daily_command))
    application.add_handler(CommandHandler("slots", game.slots_command))
    application.add_handler(CommandHandler("bounty", game.bounty_command))
    application.add_handler(CommandHandler("profile", game.profile_command))
    application.add_handler(CommandHandler("top", game.leaderboard_command))
# ... aur baaki purane wale bhi (rob, kill, etc)
    application.add_handler(CommandHandler("triviagame", trivia_bot.toggle_game_status))
    # --- NEW: Refactored Game Commands ---
    application.add_handler(CommandHandler("game", game.start_game))
    application.add_handler(CommandHandler("profile", game.start_game))
    application.add_handler(CommandHandler("leaderboard", game.handle_leaderboard))
    application.add_handler(CommandHandler("marry", game.handle_marry))
    application.add_handler(CommandHandler("adopt", game.handle_adopt))
    application.add_handler(CommandHandler("divorce", game.handle_divorce))
    application.add_handler(CommandHandler("check", game.handle_check_profile))
    
    application.add_handler(CommandHandler("daily", game.daily_command))
    application.add_handler(CommandHandler("bounty", game.bounty_command))
    application.add_handler(CommandHandler("slots", game.slots_command))
    application.add_handler(CommandHandler("clan", game.clan_command))

    application.add_handler(CommandHandler("disown", game.handle_disown))
    application.add_handler(CommandHandler("runaway", game.handle_runaway))
    application.add_handler(CommandHandler("shop", game.shop_menu))

    # --- Admin Commands (Group Admin required) ---
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("reboot", reboot_command))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("unmute", unmute_user))
    
    # --- NEW: Custom Welcome Admin Commands ---
    application.add_handler(CommandHandler("setwelcome", set_welcome_message_command))
    application.add_handler(CommandHandler("setwelcomemedia", set_welcome_media_command))
    application.add_handler(CommandHandler("resetwelcome", reset_welcome_command))
    
    # Sudo-Only Commands (Sudo user or Owner required)
    application.add_handler(CommandHandler("poweron", check_sudo_wrapper(poweron_command)))
    application.add_handler(CommandHandler("poweroff", check_sudo_wrapper(poweroff_command)))
    application.add_handler(CommandHandler("broadcast", check_sudo_wrapper(broadcast_command)))
    application.add_handler(CommandHandler("get_photo_id", check_sudo_wrapper(get_photo_id)))
    application.add_handler(CommandHandler("adminstats", check_sudo_wrapper(admin_stats_command)))
    application.add_handler(CommandHandler("forcegroq", check_sudo_wrapper(force_groq_command)))
    application.add_handler(CommandHandler("forcedynamic", check_sudo_wrapper(force_dynamic_command)))
    application.add_handler(CommandHandler("forcedeepseek", check_sudo_wrapper(force_deepseek_command)))
    application.add_handler(CommandHandler("show_chats", check_sudo_wrapper(show_chats_command)))
    application.add_handler(CommandHandler("s_ban", check_sudo_wrapper(sudo_ban_user)))
    application.add_handler(CommandHandler("s_unban", check_sudo_wrapper(sudo_unban_user)))
    application.add_handler(CommandHandler("s_send", check_sudo_wrapper(sudo_send_message)))
    application.add_handler(CommandHandler("slots", game.slots_command))
    application.add_handler(CommandHandler("bounty", game.bounty_command))
    application.add_handler(CommandHandler("top", game.leaderboard_command))
    application.add_handler(CommandHandler("clan", game.clan_command))
    # Adoption system ke naye handlers
    
    # Owner-Only Sudo Management Commands (BROADCAST_ADMIN_ID required)
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("removesudo", remove_sudo_command))
    # 1. Pehle Commands
    # 2. Phir Callbacks (Dhyan se order dekho)
    # Pattern dena zaroori hai taaki ye sirf start buttons pakde
    application.add_handler(CallbackQueryHandler(start_callback_handler, pattern="^start_"))
    application.add_handler(CallbackQueryHandler(xoxo_callback, pattern="^xoxo_"))
    application.add_handler(CallbackQueryHandler(help_callback_handler, pattern="^help_"))

    # 3. Game callback sabse last mein kyunki usme pattern nahi hai
    application.add_handler(CallbackQueryHandler(game.handle_game_callback, pattern="^game"))
    # ... baki code ...
    # --- Message handlers ---
    # ... existing handlers ...
    # main() function ke andar...

# ... XOXO Handlers ke baad ya apne manchahe jagah par ..
    application.add_handler(CommandHandler("youtube", youtube_command))
    # main.py ke andar MessageHandler update karo
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"(youtube\.com|youtu\.be|instagram\.com)"), 
        social_media_handler
    ))
# --- NEW: File ID Finder Com
    application.add_handler(CommandHandler("getfileid", get_file_id_command))
    application.add_handler(CommandHandler("fid", get_file_id_command)) # Optional short alias
    # XOXO Handlers
    application.add_handler(CommandHandler("xoxo", xoxo_command))
    application.add_handler(CommandHandler("tictactoe", xoxo_command))
    # ... (Ye lines main() function ke andar honi chahiye) ...

    # XOXO Game Commands

    # 👇 YE LINE SABSE ZAROORI HAI, ISKE BINA END NAHI HOGA 👇
    application.add_handler(CommandHandler("endxoxo", end_xoxo_command))
    application.add_handler(CommandHandler("endgame", end_xoxo_command))

    # 2. Phir saare Callback Handlers (Buttons ke liye)
    # 
    # 3. Phir Status Updates (Welcome message)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))

    # 4. Phir Special Text Filters (YouTube/Insta links)
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & (~filters.UpdateType.EDITED_MESSAGE) & (~filters.COMMAND), 
        process_message
    ))
    

    # 5. Phir Voice Messages
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    # 6. SABSE NICHE: General AI Chat (process_message)
    # Isko upar rakhoge toh buttons aur baki cheezein block ho jayengi
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & (~filters.UpdateType.EDITED_MESSAGE), 
        process_message
    ))
    
    application.add_handler(MessageHandler(
        (filters.UpdateType.EDITED_MESSAGE & (filters.TEXT | filters.CAPTION)), 
        process_message
    ))

    # Error handling
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
