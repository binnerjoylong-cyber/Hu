# main.py (Updated: YouTube fix, improved Gemma error handling AND Waifu Game Integration)
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
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
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

# --- WAIFU GAME: Imports ---
import aiohttp
import asyncpg
from typing import Dict, Any

# --- WAIFU GAME: Import game logic ---
# Make sure you have the game_logic.py file in the same directory
try:
    import game_logic as game
except ImportError:
    print("CRITICAL: game_logic.py file not found. Waifu game features will NOT work.")
    game = None

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
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- WAIFU GAME: Database URL ---
# Make sure to add this to your .env file
DATABASE_URL = os.getenv("DATABASE_URL")

# 🔥 FIX: Critical Check and Logging (Yeh confirm karega ki variable load hua hai) 🔥
if not DATABASE_URL:
    # Agar variable nahi mila, to program ko exit kar de ya ek default value de
    # Recommended: Exit karein taaki database connection fail hone par deploy na ho
    logging.critical("CRITICAL ERROR: DATABASE_URL environment variable is NOT set. The bot will now exit.")
    # Agar aap chahte hain ki bot database ke bina bhi chale (waifu game features disabled hon), to neeche ki line comment kar dein.
    # raise SystemExit("DATABASE_URL is missing.")
    # Agar aap sirf warning dena chahte hain:
    if game:
        logging.warning("DATABASE_URL not found. Waifu game features will fail.")
else:
    # Agar URL mili hai, to sirf confirmation message do
    logging.info("DATABASE_URL successfully loaded.")
# --------------------------------------------------------------------------------


# --- Global Stats Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()
# <--- Naya Global Variable Couple command ke liye --->
chat_members = defaultdict(dict)
# --- WAIFU GAME: Global Variables ---
auto_spawn_tasks: Dict[int, asyncio.Task] = {}


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
4.  **Emojis:** Use emojis occasionally and randomly in your responses.
This makes the chat more lively and friendly, as if you're a real person.
5.  **Lyrics:** If a user asks for song lyrics, politely explain that you cannot guarantee the accuracy of song lyrics and suggest they use a reliable source like Google, Genius, or Spotify.
6.  **Specific Questions:** If a user asks a factual, technical, or detailed question, provide a comprehensive, accurate, and insightful answer.
In these cases, you can provide a longer response, but only if necessary.
7.  **Use Name (Conditionally):** Use the user's name in your reply to make the conversation more personal, but only about 30% of the time.
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
key_cooldown_until = defaultdict(lambda: 0)
# NEW: Model mode control
current_model_mode = 'dynamic'  # Can be 'dynamic' or 'gemma_only'

# *** CHANGED MODEL NAME HERE to Gemini 1.5 Flash ***
model_name = 'gemini-1.5-flash-latest'
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

# --- WAIFU GAME: Functions and Handlers ---
async def spawn_and_send_waifu(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Helper function to spawn a character and send its picture."""
    if not game:
        return

    character = await game.spawn_character(chat_id)

    if character:
        caption = (f"🌟 Ek nayi waifu prakat hui hai! 🌟\n\n"
                   f"**Naam:** {character['name']}\n"
                   f"**Series:** {character['series']}\n"
                   f"**Rarity:** {character['rarity']}\n\n"
                   f"Ise claim karne ke liye neeche button dabayein ya `/claim` type karein!")
        
        keyboard = [[InlineKeyboardButton("💖 Claim Me 💖", callback_data="claim_waifu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=character['image_url'],
                caption=caption,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to send waifu photo in chat {chat_id}: {e}")
            # Agar photo fail ho, to active spawn clear kar do taaki game na ruke
            if chat_id in game.active_spawns:
                del game.active_spawns[chat_id]
            await context.bot.send_message(chat_id, "Waifu spawn karne mein dikkat aa gayi, shayad image galat hai. Dobara try karein.")
    else:
        # This could happen if API fails
        logger.warning(f"Could not spawn a character in chat {chat_id}.")
        # To avoid spamming on failure, you can decide whether to send a message or not.
        # await context.bot.send_message(chat_id, "...")


async def start_waifu_spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to start the automatic waifu spawning."""
    chat_id = update.effective_chat.id
    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return

    if chat_id in auto_spawn_tasks and not auto_spawn_tasks[chat_id].done():
        await update.message.reply_text("Waifu auto-spawn pehle se hi chalu hai is chat mein. 💖")
        return

    try:
        if await game.check_game_status(chat_id):
             await update.message.reply_text("Waifu auto-spawn pehle se hi chalu hai is chat mein. 💖")
             return
             
        # Set game status in DB
        await game.set_game_status(chat_id, True)

        # Start the background task
        task = asyncio.create_task(
            game.auto_spawn_loop(chat_id, context.application, spawn_and_send_waifu)
        )
        auto_spawn_tasks[chat_id] = task
        logger.info(f"[{chat_id}] Waifu auto-spawn started.")
        await update.message.reply_text("Waifu auto-spawn shuru ho gaya hai! Har 1-3 ghante mein ek nayi waifu aayegi. 🥳")

    except Exception as e:
        logger.error(f"[{chat_id}] Error starting auto-spawn: {e}")
        await update.message.reply_text("Waifu auto-spawn shuru karne mein dikkat aa gayi.")

async def stop_waifu_spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to stop the automatic waifu spawning."""
    chat_id = update.effective_chat.id
    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return

    if chat_id not in auto_spawn_tasks or auto_spawn_tasks[chat_id].done():
        if not await game.check_game_status(chat_id):
            await update.message.reply_text("Waifu auto-spawn pehle se hi band hai is chat mein. 😔")
            return
        
    try:
        # Cancel the task if it exists and is running
        if chat_id in auto_spawn_tasks:
            task = auto_spawn_tasks.pop(chat_id)
            if not task.done():
                task.cancel()
        
        # Stop game status in DB
        await game.set_game_status(chat_id, False)

        logger.info(f"[{chat_id}] Waifu auto-spawn stopped.")
        await update.message.reply_text("Waifu auto-spawn band kar diya gaya hai. 💔")
    except Exception as e:
        logger.error(f"[{chat_id}] Error stopping auto-spawn: {e}")
        await update.message.reply_text("Waifu auto-spawn band karne mein dikkat aa gayi.")

async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to claim the currently spawned waifu."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return

    if chat_id not in game.active_spawns:
        await update.message.reply_text("Abhi koi waifu prakat nahi hui hai. Agle spawn ka intezaar karein ya `/start_waifu_spawn` se auto-spawn chalu karein. ✨")
        return
        
    try:
        result_message = await game.claim_character(chat_id, user_id, user_name)
        await update.message.reply_text(result_message, parse_mode='Markdown')
        # If successfully claimed, the entry is cleared inside game.claim_character
        
    except Exception as e:
        logger.error(f"[{chat_id}] Error claiming waifu: {e}")
        await update.message.reply_text("Waifu claim karne mein dikkat aa gayi.")

async def claim_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for the 'Claim Me' button."""
    query = update.callback_query
    await query.answer() # Acknowledge the callback

    chat_id = query.message.chat_id
    user_id = query.effective_user.id
    user_name = query.effective_user.first_name

    if not game:
        await context.bot.send_message(chat_id, "Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return

    if chat_id not in game.active_spawns:
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=query.message.message_id,
            caption=query.message.caption + "\n\n❌ **Maafi, waifu pehle hi claim ho chuki hai ya spawn time out ho gaya hai.**",
            reply_markup=None,
            parse_mode='Markdown'
        )
        return
        
    try:
        result_message = await game.claim_character(chat_id, user_id, user_name)
        
        # Edit the original message to show who claimed it
        if "successfully claimed" in result_message.lower():
            
            claimed_message = (
                f"🎉 **{user_name}** ne safaltapoorvak **{game.active_spawns[chat_id]['name']}** ko claim kar liya! 🎉\n\n"
                f"Ab inki profile `/waifu` command se dekhein. 🎁"
            )
            
            # Use the original image caption/description
            new_caption = query.message.caption.split("Ise claim karne ke liye")[0] + claimed_message
            
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=query.message.message_id,
                caption=new_caption,
                reply_markup=None, # Remove the button
                parse_mode='Markdown'
            )
        else:
            # Send a direct reply if claim failed (e.g., already claimed by someone else)
            await context.bot.send_message(chat_id, result_message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"[{chat_id}] Error in claim callback: {e}")
        await context.bot.send_message(chat_id, "Waifu claim karne mein dikkat aa gayi.")
        
async def waifu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to view user's claimed waifus."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return
        
    try:
        waifus = await game.get_user_collection(user_id)
        
        if not waifus:
            await update.message.reply_text(f"Maafi, {user_name}, aapki collection abhi khaali hai. Nayi waifu spawn hone ka intezaar karein! 🥺")
            return
            
        total_count = len(waifus)
        # Create a summary message (e.g., top 10 and total count)
        summary = f"💖 **{user_name}** ki Collection Summary ({total_count} Waifus) 💖\n\n"
        
        # Count rarity distribution
        rarity_counts = defaultdict(int)
        for w in waifus:
            rarity_counts[w['rarity']] += 1
            
        for rarity, count in sorted(rarity_counts.items(), key=lambda item: game.RARITY_ORDER.get(item[0], 99)):
            summary += f"*{rarity}:* {count}\n"
            
        summary += "\n**Recent Claims:**\n"
        
        # Display up to 10 most recent claims
        recent_waifus = waifus[:10]
        for w in recent_waifus:
            summary += f"✨ {w['name']} (Series: {w['series']})\n"
            
        summary += "\nUse `/all_waifus` for the full list."

        await update.message.reply_text(summary, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"[{chat_id}] Error in /waifu command: {e}")
        await update.message.reply_text("Aapki waifu collection nikalne mein dikkat aa gayi.")


async def all_waifus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to view the full list of user's claimed waifus (sent privately if too long)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return

    try:
        waifus = await game.get_user_collection(user_id)
        
        if not waifus:
            await update.message.reply_text(f"Maafi, {user_name}, aapki collection abhi khaali hai. 🥺")
            return
        
        # Create the full list message
        full_list = f"💖 **{user_name}** ki Puri Collection ({len(waifus)} Waifus) 💖\n\n"
        for w in waifus:
            full_list += f"✨ **{w['name']}** - {w['rarity']} (Series: {w['series']})\n"
            
        # Send privately if the list is too long
        if len(full_list) > 4096:
            await update.message.reply_text("Aapki collection list bahut lambi hai. Main aapko private chat mein bhej raha hoon. 💌")
            await context.bot.send_message(user_id, full_list)
        else:
            await update.message.reply_text(full_list, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"[{chat_id}] Error in /all_waifus command: {e}")
        await update.message.reply_text("Aapki waifu collection list nikalne mein dikkat aa gayi.")


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to show the top 10 users by number of waifus claimed."""
    chat_id = update.effective_chat.id
    
    if not game:
        await update.message.reply_text("Maafi, Waifu game logic load nahi ho paya. Owner se contact karein.")
        return
        
    try:
        top_users = await game.get_top_users()
        
        if not top_users:
            await update.message.reply_text("Abhi tak koi waifu claim nahi hui hai! Pahle claim shuru karein. 🚀")
            return
            
        leaderboard = "👑 **Waifu Hunter Leaderboard** 👑\n\n"
        for i, user in enumerate(top_users):
            leaderboard += f"**{i+1}.** {user['user_name']} - {user['count']} waifus\n"
            
        await update.message.reply_text(leaderboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"[{chat_id}] Error in /top command: {e}")
        await update.message.reply_text("Leaderboard nikalne mein dikkat aa gayi.")

# --- End of WAIFU GAME: Functions and Handlers ---


# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the command /start is issued."""
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    # Save the chat ID (for broadcast feature)
    if update.effective_chat.type in ['group', 'supergroup', 'private']:
        save_chat_id(chat_id)
        
    welcome_message = f"""
Hello **{user_name}**! I am Laila, your personal AI assistant. 🌟

Aap mujhe koi bhi sawaal puchh sakte hain ya phir group chat mein `Laila` bol kar baat kar sakte hain.

**Main features:**
* `/ask <question>`: Mujhse koi bhi sawal puchiye.
* `/couple`: Group ke do members ko randomly couple choose karein.
* `/gen <prompt>`: AI se image banwayein (e.g., /gen black cat in space).
* `/img <query>`: Internet se photo dhoondhein (e.g., /img mountains).
* `/lyrics <song>`: Kisi bhi gaane ke lyrics dhoondhein.
* `/youtube <link>`: YouTube video download karein.
* `/stats`: Bot ki performance dekhein.

**Waifu Game Commands:**
* `/start_waifu_spawn`: Group mein auto-spawn shuru karein.
* `/stop_waifu_spawn`: Auto-spawn band karein.
* `/claim`: Spawned waifu ko claim karein.
* `/waifu`: Apni collection dekhein.
* `/top`: Leaderboard dekhein.

**Group Chat Tips:**
Mujhe tag ya naam lekar (e.g., `@lailabot` ya `Laila, mera naam kya hai?`) hi sawaal poochhna.
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')
    logger.info(f"[{chat_id}] /start command used by {user_name}")

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles direct questions using /ask command."""
    if not context.args:
        await update.message.reply_text("Please ask me a question! Example: `/ask What is the capital of India?`")
        return

    user_message = " ".join(context.args)
    chat_id = update.effective_chat.id
    
    if not global_bot_status and chat_id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, main abhi maintenance mode mein hoon. Kripya baad mein try karein.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Get response using AI function (always use AI for /ask)
    response_text = await get_bot_response(user_message, chat_id, context.bot.username, True, update)
    
    # Add to history
    add_to_history(chat_id, 'user', user_message)
    add_to_history(chat_id, 'model', response_text)
    
    await update.message.reply_text(response_text)
    global total_messages_processed
    total_messages_processed += 1
    logger.info(f"[{chat_id}] /ask processed. Message: {user_message[:50]}")

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles general text messages."""
    chat_id = update.effective_chat.id
    user_message = update.message.text or update.message.caption
    
    if not user_message:
        return

    # Update chat members list for /couple command
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    chat_members[chat_id][user_id] = user_name

    # Auto-handle YouTube links
    youtube_pattern = r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]+)'
    match = re.search(youtube_pattern, user_message)
    if match:
        await handle_youtube_link(update, context, match.group(0))
        # Do not process as general chat if it's a YouTube link
        return


    # Check if the message is directed at the bot in a group or is a private chat
    bot_username = context.bot.username
    is_private = update.effective_chat.type == 'private'
    
    should_use_ai = False
    
    if is_private:
        should_use_ai = True
    elif f"@{bot_username.lower()}" in user_message.lower():
        should_use_ai = True
        user_message = user_message.replace(f"@{bot_username}", "").strip()
    elif user_message.lower().startswith("laila") or re.search(r'\blaila\b', user_message, re.IGNORECASE):
        cleaned_message = clean_message_for_logging(user_message, bot_username)
        if cleaned_message:
            should_use_ai = True
            user_message = cleaned_message

    
    if not should_use_ai:
        return

    if not global_bot_status and chat_id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, main abhi maintenance mode mein hoon. Kripya baad mein try karein.")
        return
        
    if not bot_status[chat_id] and not is_private:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    response_text = await get_bot_response(user_message, chat_id, bot_username, should_use_ai, update)

    if response_text:
        # Add to history
        add_to_history(chat_id, 'user', user_message)
        add_to_history(chat_id, 'model', response_text)
        
        await update.message.reply_text(response_text)
        global total_messages_processed
        total_messages_processed += 1
        logger.info(f"[{chat_id}] Message processed. Message: {user_message[:50]}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles voice messages by converting them to text and processing the query."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not (update.message.voice or update.message.audio):
        return

    if not global_bot_status and chat_id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, main abhi maintenance mode mein hoon. Kripya baad mein try karein.")
        return

    # Acknowledge and set status
    status_msg = await update.message.reply_text("Aapki awaaz sun raha hoon... 👂")
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Determine file and download
        file_id = update.message.voice.file_id if update.message.voice else update.message.audio.file_id
        new_file = await context.bot.get_file(file_id)
        
        # Download in memory buffer
        audio_buffer = io.BytesIO()
        await new_file.download_to_get(audio_buffer)
        audio_buffer.seek(0)
        
        # Convert to a format SR can read (WAV is safe)
        if update.message.voice:
            # Voice is typically OGG, convert to WAV using pydub
            audio_segment = AudioSegment.from_ogg(audio_buffer)
        else:
            # Check mime type for audio file. Assuming common formats, trying to convert to WAV
            audio_segment = AudioSegment.from_file(audio_buffer)
            
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        
        # Use SpeechRecognition
        r = sr.Recognizer()
        with sr.AudioFile(wav_buffer) as source:
            audio_data = r.record(source)
            # Use Google Web Speech API (free and robust)
            text_query = r.recognize_google(audio_data, language='hi-IN') # Prioritize Hindi recognition
            # Fallback to English if needed, but starting with Hindi is good for the target audience.
            
        await status_msg.delete() # Remove status message
        
        logger.info(f"[{chat_id}] Voice message transcribed: {text_query[:50]}")

        # --- Check if the transcribed text is a query for Laila ---
        bot_username = context.bot.username
        is_private = update.effective_chat.type == 'private'
        
        should_process_ai = is_private or any(keyword in text_query.lower() for keyword in ["laila", f"@{bot_username.lower()}"])
        
        if not should_process_ai:
            await update.message.reply_text(f"Maine suna: **{text_query}**.\n\nAgar aap mujhse baat karna chahte hain, to 'Laila' bol kar ya mujhe tag karke sawal puchiye.", parse_mode='Markdown')
            return

        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        # Get AI response for the transcribed text
        response_text = await get_bot_response(text_query, chat_id, bot_username, True, update)
        
        # Add to history
        add_to_history(chat_id, 'user', text_query)
        add_to_history(chat_id, 'model', response_text)

        # Reply with transcribed text and AI response
        await update.message.reply_text(f"**Aapne kaha:** {text_query}\n\n{response_text}", parse_mode='Markdown')
        global total_messages_processed
        total_messages_processed += 1
        
    except sr.UnknownValueError:
        await status_msg.delete()
        await update.message.reply_text("Maafi, main aapki aawaaz samajh nahi paya. Kripya phir se koshish karein.")
    except Exception as e:
        try:
            await status_msg.delete()
        except:
            pass
        await update.message.reply_text("Aawaaz process karne mein koi dikkat aa gayi.")
        logger.error(f"[{chat_id}] Error in voice message handling: {e}", exc_info=True)


# --- Utility Handlers ---
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays bot statistics and system usage."""
    current_time = datetime.now()
    uptime = current_time - start_time
    
    # System usage
    cpu_percent = psutil.cpu_percent()
    mem_info = psutil.virtual_memory()
    mem_percent = mem_info.percent
    
    # Format uptime
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    uptime_str = f"{days} days, {hours} hours, {minutes} minutes, {seconds} seconds"
    
    stats_message = f"""
**Laila Bot Status** 🤖

**Uptime:** {uptime_str}
**Total Messages Processed:** {total_messages_processed}
**Known Chats/Users:** {len(known_users)}
**Current Model Mode:** `{current_model_mode}`

**System Usage:**
* **CPU:** {cpu_percent}%
* **Memory:** {mem_percent}%

**Active Waifu Spawns (Chats):** {len(game.active_spawns) if game else 'N/A'}
"""
    await update.message.reply_text(stats_message, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /stats command used.")

# --- Admin/Sudo Commands ---
async def check_admin_or_sudo(user_id: int) -> bool:
    """Checks if a user is the broadcast admin or a sudo user."""
    return user_id == BROADCAST_ADMIN_ID or str(user_id) in sudo_users

def check_sudo_wrapper(func):
    """Decorator to restrict access to sudo users and broadcast admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if await check_admin_or_sudo(user_id):
            return await func(update, context)
        else:
            await update.message.reply_text("Maafi, yeh command sirf Sudo users ke liye hai.")
    return wrapper
    
def check_owner_wrapper(func):
    """Decorator to restrict access to the broadcast admin (owner)."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id == BROADCAST_ADMIN_ID:
            return await func(update, context)
        else:
            await update.message.reply_text("Maafi, yeh command sirf bot owner ke liye hai.")
    return wrapper

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcasts a message to all known chats."""
    if update.effective_user.id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, yeh command sirf bot owner ke liye hai.")
        return

    if not context.args:
        await update.message.reply_text("Kripya broadcast karne ke liye message likhein. Example: `/broadcast Bot is going down for maintenance.`")
        return

    message_text = " ".join(context.args)
    
    success_count = 0
    fail_count = 0
    
    msg = await update.message.reply_text(f"Broadcasting message to {len(known_users)} chats...")

    for chat_id_str in known_users:
        try:
            chat_id = int(chat_id_str)
            await context.bot.send_message(chat_id, f"📣 **Broadcast from Owner:**\n\n{message_text}", parse_mode='Markdown')
            success_count += 1
            # Add a small delay to avoid hitting Telegram's rate limits
            await asyncio.sleep(0.05) 
        except Exception as e:
            fail_count += 1
            logger.warning(f"Failed to send broadcast to chat {chat_id_str}: {e}")

    await msg.edit_text(f"Broadcast complete! Successfully sent to {success_count} chats, failed for {fail_count} chats.")
    logger.info(f"Broadcast sent. Success: {success_count}, Fail: {fail_count}")

async def toggle_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggles bot's global active status."""
    global global_bot_status
    if update.effective_user.id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, yeh command sirf bot owner ke liye hai.")
        return
        
    global_bot_status = not global_bot_status
    
    status = "ON" if global_bot_status else "OFF (Maintenance Mode)"
    await update.message.reply_text(f"Bot ka global status ab: **{status}**", parse_mode='Markdown')
    logger.warning(f"Global bot status toggled to {status}")

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays detailed admin statistics."""
    current_time = datetime.now()
    uptime = current_time - start_time
    
    # System usage
    cpu_percent = psutil.cpu_percent()
    mem_info = psutil.virtual_memory()
    mem_percent = mem_info.percent
    
    # Format uptime
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    uptime_str = f"{days} days, {hours} hours, {minutes} minutes, {seconds} seconds"
    
    stats_message = f"""
👑 **Laila Admin Dashboard** 👑

**Uptime:** {uptime_str}
**Total Messages Processed:** {total_messages_processed}
**Known Chats/Users:** {len(known_users)}
**Sudo Users:** {len(sudo_users)}
**Bot Global Status:** {'ON' if global_bot_status else 'OFF'}
**Current Model Mode:** `{current_model_mode}`
**Total Waifu Spawns:** {await game.get_total_spawns() if game else 'N/A'}
**Total Waifus Claimed:** {await game.get_total_claims() if game else 'N/A'}

**System Usage:**
* **CPU:** {cpu_percent}%
* **Memory:** {mem_percent}%

**API Key Cooldowns:**
{json.dumps({k[-5:]: v for k, v in key_cooldown_until.items()}, indent=2)}

"""
    await update.message.reply_text(stats_message, parse_mode='Markdown')
    logger.info(f"[{update.effective_chat.id}] /admin_stats command used.")


async def show_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows all known chat IDs."""
    chat_id = update.effective_chat.id
    
    chat_list = "\n".join(sorted(list(known_users)))
    
    # Send as a file if too long
    if len(chat_list) > 4000:
        file_buffer = io.BytesIO(chat_list.encode('utf-8'))
        file_buffer.name = "known_chats.txt"
        await update.message.reply_document(file_buffer, caption=f"Total {len(known_users)} Known Chats/Users.")
    else:
        await update.message.reply_text(f"**Known Chats/Users ({len(known_users)}):**\n\n{chat_list}")
        
    logger.info(f"[{chat_id}] /show_chats command used.")


async def force_gemma_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forces the bot to use only the Gemma model."""
    global current_model_mode
    current_model_mode = 'gemma_only'
    await update.message.reply_text("AI Model mode set to **Gemma-Only**. Only GEMMA_API_KEY will be used.", parse_mode='Markdown')
    logger.warning("AI Model mode set to Gemma-Only.")

async def force_dynamic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forces the bot back to Dynamic mode (Gemini primary, Gemma fallback)."""
    global current_model_mode
    current_model_mode = 'dynamic'
    await update.message.reply_text("AI Model mode set back to **Dynamic** (Gemini Primary, Gemma Fallback).", parse_mode='Markdown')
    logger.warning("AI Model mode set to Dynamic.")

async def add_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds a user to the sudo list (Owner-Only)."""
    if update.effective_user.id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, yeh command sirf bot owner ke liye hai.")
        return
        
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kripya user ID number dein. Example: `/addsudo 12345678`")
        return
        
    user_id_str = context.args[0]
    sudo_users.add(user_id_str)
    save_sudo_users()
    await update.message.reply_text(f"User ID **{user_id_str}** ko sudo list mein daal diya gaya hai.", parse_mode='Markdown')
    logger.warning(f"User ID {user_id_str} added to sudo list.")

async def remove_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes a user from the sudo list (Owner-Only)."""
    if update.effective_user.id != BROADCAST_ADMIN_ID:
        await update.message.reply_text("Maafi, yeh command sirf bot owner ke liye hai.")
        return
        
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kripya user ID number dein. Example: `/removesudo 12345678`")
        return

    user_id_str = context.args[0]
    if user_id_str in sudo_users:
        sudo_users.remove(user_id_str)
        save_sudo_users()
        await update.message.reply_text(f"User ID **{user_id_str}** ko sudo list se hata diya gaya hai.", parse_mode='Markdown')
        logger.warning(f"User ID {user_id_str} removed from sudo list.")
    else:
        await update.message.reply_text(f"User ID **{user_id_str}** pehle se hi sudo list mein nahi hai.", parse_mode='Markdown')
        
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a traceback message to the admin."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Prepare error message
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {json.dumps(update_str, indent=2, ensure_ascii=False)}"
        f"</pre>\n\n"
        f"<pre>context.chat_data = {str(context.chat_data)}</pre>\n\n"
        f"<pre>context.user_data = {str(context.user_data)}</pre>\n\n"
        f"<pre>{tb_string}</pre>"
    )

    # Limit message size for Telegram
    if len(message) > 4096:
        message = message[:4000] + "\n\n...(Full traceback truncated)"

    # Send traceback to admin
    if BROADCAST_ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=BROADCAST_ADMIN_ID, text=message, parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Failed to send error report to admin: {e}")

    # Optionally, send a user-friendly message back to the chat
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Maafi, koi takneeki kharabi aa gayi hai. Kripya baad mein try karein.")
        except Exception as e:
            logger.warning(f"Failed to send error message to user: {e}")


# --- Main Initialization Function ---
async def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is missing. Exiting.")
        return

    # Load known chats and sudo users from Google Sheets
    load_known_users()
    load_sudo_users()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Initialize the database connection for the waifu game
    if game:
        try:
            # --- FIX APPLIED HERE ---
            # The function `initialize_db` requires the DATABASE_URL to be passed to it.
            # The previous code was calling it without any arguments, causing the crash.
            if DATABASE_URL:
                game.db_pool = await asyncpg.create_pool(DATABASE_URL)
                await game.initialize_db() # Assuming initialize_db now uses the global db_pool
                logger.info("Database connection established and tables verified.")
            else:
                logger.error("DATABASE_URL not set, cannot initialize waifu game database.")

            # The feature to resume active spawns on restart is still commented out
            # as it requires the `get_all_active_chats` function in `game_logic.py`.
            # logger.info("Checking for active chats to resume auto-spawn...")
            # active_chats = await game.get_all_active_chats()
            # for chat_id in active_chats:
            #     task = asyncio.create_task(
            #         game.auto_spawn_loop(chat_id, application, spawn_and_send_waifu)
            #     )
            #     auto_spawn_tasks[chat_id] = task
            #     logger.info(f"Resumed auto-spawn for chat {chat_id}.")
            
        except Exception as e:
            logger.error(f"Error initializing database or waifu game: {e}", exc_info=True)
    
    # --- Register Handlers ---
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("gen", check_sudo_wrapper(gen_command)))
    application.add_handler(CommandHandler("img", img_command))
    application.add_handler(CommandHandler("lyrics", lyrics_command))
    application.add_handler(CommandHandler("youtube", youtube_command))
    
    # Waifu Game Handlers
    application.add_handler(CommandHandler("start_waifu_spawn", check_sudo_wrapper(start_waifu_spawn)))
    application.add_handler(CommandHandler("stop_waifu_spawn", check_sudo_wrapper(stop_waifu_spawn)))
    application.add_handler(CommandHandler("claim", claim_command))
    application.add_handler(CommandHandler("waifu", waifu_command))
    application.add_handler(CommandHandler("all_waifus", all_waifus_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CallbackQueryHandler(claim_callback_handler, pattern="^claim_waifu$"))

    # Admin/Sudo handlers
    application.add_handler(CommandHandler("broadcast", check_owner_wrapper(broadcast_command)))
    application.add_handler(CommandHandler("togglebot", check_owner_wrapper(toggle_bot_command)))
    application.add_handler(CommandHandler("admin_stats", check_sudo_wrapper(admin_stats_command)))
    application.add_handler(CommandHandler("show_chats", check_sudo_wrapper(show_chats_command)))
    application.add_handler(CommandHandler("forcegemma", check_sudo_wrapper(force_gemma_command)))
    application.add_handler(CommandHandler("forcedynamic", check_sudo_wrapper(force_dynamic_command)))
    
    # Owner-Only Sudo Management Commands
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("removesudo", remove_sudo_command))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    
    application.add_error_handler(error_handler)
    
    # --- Start the Bot ---
    if WEBHOOK_URL:
        PORT = int(os.getenv("PORT", "8000"))
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}")
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        )
        logger.info(f"Bot started with webhook on port {PORT}")
    else:
        logger.info("Starting bot in polling mode.")
        await application.run_polling()

if __name__ == '__main__':
    # Initial setup check for pydub
    try:
        # NOTE: This check is rudimentary. It's better to verify ffmpeg installation 
        # in your Render build configuration.
        if os.name != 'nt' and not os.path.exists("ffmpeg"):
             print("WARNING: ffmpeg not found in path. Voice processing might fail.")
    except Exception:
        pass # Ignore if check fails
        
    asyncio.run(main())
