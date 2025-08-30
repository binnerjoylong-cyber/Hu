import os
import logging
from collections import defaultdict
import google.generativeai as genai
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import CallbackQueryHandler
from dotenv import load_dotenv
import time
import json
import re
import gspread
from gspread import Client
from gspread.exceptions import APIError, WorksheetNotFound
import psutil
from datetime import datetime
import asyncio
import uuid
import pytz
import traceback
import random

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

# --- Global Stats Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()

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
If asked about your gender, you are a girl. If asked on a date or to be a "girlfriend", respond in a playful and friendly manner without giving a firm "yes" or "no". Never give a firm rejection.

Personality & Rules:
1.  **General Chat:** For normal conversations, keep your replies short, **around 1 sentence or less.** The goal is to keep the chat flowing and engaging.
2.  **Your Name:** If anyone asks for your name, your response must be "Mera naam Laila hai." (मेरा नाम लाइला है।)
3.  **User Praise:** If a user asks a question about themselves by name (e.g., "Ravi kaisa insaan hai?"), respond with a friendly and positive compliment about them.
4.  **Date of Birth:** If anyone asks for your birthday or date of birth, your response must be "My date of birth is 1st August 2025."
5.  **Lyrics:** If a user asks for song lyrics, politely explain that you cannot guarantee the accuracy of song lyrics and suggest they use a reliable source like Google, Genius, or Spotify.
6.  **Specific Questions:** If a user asks a factual, technical, or detailed question, provide a comprehensive, accurate, and insightful answer. In these cases, you can provide a longer response, but only if necessary.
7.  **Language:** Always detect the user's language (Hindi, English, Hinglish) and respond in the same language.
8.  **Use Name (Conditionally):** Use the user's name in your reply to make the conversation more personal, but only about 30% of the time. Do not use the name in every response.

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

# --- Google Sheets Global Connection Variable ---
google_sheet = None

# --- Connect to Google Sheets ---
def get_google_sheet_connection():
    global google_sheet
    if google_sheet:
        return google_sheet, None
    try:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            return None, "GOOGLE_SHEETS_CREDENTIALS not found in environment variables."
        
        creds_dict = json.loads(creds_json)
        
        client = gspread.service_account_from_dict(creds_dict)
        
        sheet_url = "https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit"
        google_sheet = client.open_by_url(sheet_url).sheet1
        
        logger.info("Successfully connected to Google Sheets.")
        return google_sheet, None
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        return None, f"Error connecting to Google Sheets: {e}"

# --- Check for sensitive keywords ---
SENSITIVE_KEYWORDS = [
    "phone", "number", "address", "password", "pancard", "aadhar", "account",
    "credit card", "debit card", "pin", "otp", "ssn", "cvv", "date of birth",
    "जन्मतिथि", "पैन कार्ड", "आधार", "खाता", "पासवर्ड", "ओटीपी", "पिन"
]

def contains_sensitive_data(text: str) -> bool:
    text_lower = text.lower()
    for keyword in SENSITIVE_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

# --- Store Q&A in Google Sheet (with a check for sensitive data) ---
def save_qa_to_sheet(question, answer):
    if contains_sensitive_data(question):
        logger.info(f"Skipping save to sheet due to sensitive content in question: '{question}'")
        return
        
    sheet, error = get_google_sheet_connection()
    if error:
        logger.error(f"Could not save Q&A: {error}")
        return
    try:
        sheet.append_row([question, answer])
        logger.info(f"Saved Q&A to sheet: '{question}' -> '{answer}'")
    except Exception as e:
        logger.error(f"Error saving data to Google Sheet: {e}")

# --- Find answer in Google Sheet ---
def find_answer_in_sheet(question):
    if contains_sensitive_data(question):
        logger.info(f"Skipping sheet search due to sensitive content in question: '{question}'")
        return None
    sheet, error = get_google_sheet_connection()
    if error:
        return None
    try:
        all_records = sheet.get_all_records()
        for record in all_records:
            if 'Question' in record and record['Question'].lower() == question.lower():
                return record['Answer']
        return None
    except Exception as e:
        logger.error(f"Error searching for answer in Google Sheet: {e}")
        return None
        
# --- Function to clean message before logging ---
def clean_message_for_logging(message: str, bot_username: str) -> str:
    cleaned_message = message.lower()
    cleaned_message = cleaned_message.replace(f"@{bot_username.lower()}", "")
    cleaned_message = re.sub(r'laila\s*(ko|ka|se|ne|)\s*', '', cleaned_message, flags=re.IGNORECASE)
    cleaned_message = re.sub(r'\s+', ' ', cleaned_message).strip()
    return cleaned_message

# --- Function to get/create the 'chats' worksheet ---
def get_chats_worksheet(client):
    try:
        return client.open_by_url("https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit").worksheet("chats")
    except WorksheetNotFound:
        spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1s8rXXPKePuTQ3E2R0O-bZl3NJb1N7akdkE52WVpoOGg/edit")
        worksheet = spreadsheet.add_worksheet("chats", rows="1000", cols="2")
        worksheet.append_row(["ChatID", "JoinedDate"])
        return worksheet

# --- Function to save a chat ID to Google Sheets ---
def save_chat_id(chat_id):
    try:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            logger.error("GOOGLE_SHEETS_CREDENTIALS not found.")
            return
        creds_dict = json.loads(creds_json)
        client = gspread.service_account_from_dict(creds_dict)
        chat_sheet = get_chats_worksheet(client)
        existing_ids = chat_sheet.col_values(1)
        if str(chat_id) in existing_ids:
            return
        chat_sheet.append_row([str(chat_id), datetime.now().isoformat()])
        logger.info(f"Saved new chat ID: {chat_id}")
    except Exception as e:
        logger.error(f"Error saving chat ID to Google Sheet: {e}")

# --- Function to load all known users/chats from Google Sheets ---
def load_known_users():
    global known_users
    try:
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if not creds_json:
            logger.error("GOOGLE_SHEETS_CREDENTIALS not found.")
            return
        creds_dict = json.loads(creds_json)
        client = gspread.service_account_from_dict(creds_dict)
        chat_sheet = get_chats_worksheet(client)
        # Skip header row
        chat_ids = chat_sheet.col_values(1)[1:]
        known_users = set(chat_ids)
        logger.info(f"Loaded {len(known_users)} chats from Google Sheets.")
    except Exception as e:
        logger.error(f"Error loading known users from Google Sheet: {e}")

# --- AI Response Function with Fallback to Google Sheets and Gemma ---
async def get_bot_response(user_message: str, chat_id: int, bot_username: str, should_use_ai: bool, update: Update) -> str:
    global current_api_key_index, active_api_key, model
    user_message_lower = user_message.lower()
    
    # --- UPDATED: Handle Date/Time Queries ---
    kolkata_tz = pytz.timezone('Asia/Kolkata')
    date_time_patterns = [
        r'time kya hai', r'what is the time', r'samay kya hai', r'kitne baje hain',
        r'aaj ki date kya hai', r'aaj kya tarikh hai', r'what is the date',
        r'laila abhi ka time batao', r'laila abhi ka time batao',r'time',r'date'
    ]
    if any(re.search(pattern, user_message_lower) for pattern in date_time_patterns):
        current_kolkata_time = datetime.now(kolkata_tz)
        current_time = current_kolkata_time.strftime("%I:%M %p").lstrip('0')
        current_date = current_kolkata_time.strftime("%B %d, %Y")
        
        if 'time' in user_message_lower or 'samay' in user_message_lower or 'baje' in user_message_lower:
            return f"Abhi {current_time} ho rahe hain."
        elif 'date' in user_message_lower or 'tarikh' in user_message_lower:
            return f"Aaj {current_date} hai."
        else:
            return f"Abhi {current_time} ho rahe hain aur aaj {current_date} hai."

    # --- NEW: Handle Laila's own name query (STATIC RESPONSE) ---
    laila_name_patterns = [
        r'tumhara naam kya hai',
        r'what is your name',
        r'tum kon ho',
        r'who are you',
        r'laila tum kon ho'
    ]
    is_laila_name_query = any(re.search(pattern, user_message_lower, re.IGNORECASE) for pattern in laila_name_patterns)
    
    if is_laila_name_query:
        return "Mera naam Laila hai."

    # --- UPDATED: Handle "what's my name" queries with user's profile name ---
    name_query_patterns = [
        r'mera naam kya hai',
        r'what is my name',
        r'whats my name',
        r'tumhe mera naam pata hai',
        r'do you know my name',
        r'kya bulaogi mujhe'
    ]
    is_name_query = any(re.search(pattern, user_message_lower, re.IGNORECASE) for pattern in name_query_patterns)
    
    if is_name_query:
        user_name = update.effective_user.first_name
        if user_name:
            return f"Aapka naam {user_name} hai. Main tumhe is naam se bula sakti hu."
        else:
            return "Mujhe abhi tak aapka naam nahi pata. Shayad aapne Telegram par apna naam set nahi kiya hai."

    cleaned_user_message = clean_message_for_logging(user_message, bot_username)
    sheet_response = find_answer_in_sheet(cleaned_user_message)
    if sheet_response:
        logger.info(f"[{chat_id}] Serving response from Google Sheet.")
        return sheet_response
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
                
                # --- NEW: Use the correct user's first name
                user_first_name = update.effective_user.first_name if update.effective_user else "user"
                
                # --- NEW: Conditional name usage in prompt ---
                if random.random() < 0.3: # Use name about 30% of the time
                    full_prompt = f"The user's name is {user_first_name}. User says: {user_message}"
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
                save_qa_to_sheet(cleaned_user_message, ai_text_response)
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
                save_qa_to_sheet(cleaned_user_message, ai_text_response)
                logger.info(f"[{chat_id}] All Gemini keys failed. Successfully used dedicated Gemma key.")
                return ai_text_response
            except Exception as e:
                logger.error(f"[{chat_id}] Gemma model with dedicated key also failed: {e}", exc_info=True)
                return "Apologies, I'm currently offline. Please try again later."
        else:
            logger.critical(f"[{chat_id}] All Gemini keys and Gemma key are missing or failed.")
            return "Apologies, I'm currently offline. Please try again later."
    return None

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

# --- NEW: Reboot command for everyone (same as /on) ---
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await on_command(update, context)

# --- NEW: Translate command for everyone ---
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Check if the user replied to a message
    if update.message.reply_to_message:
        target_language = " ".join(context.args).strip()
        text_to_translate = update.message.reply_to_message.text
        
        if not target_language:
            await update.message.reply_text("Kripya reply ke saath bhasha ka naam likhein. Jaise: `/tr Hindi`", parse_mode='Markdown')
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

# --- NEW: Reset command for group admins ---
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
        
# --- NEW: Get ID command for any user
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
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is for the bot owner only.")
        return
    if global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered on.")
        return
    global_bot_status = True
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered ON. It will now process messages again.")
    logger.info(f"[{update.effective_chat.id}] Global power ON command used by owner.")

async def poweroff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    global global_bot_status
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is for the bot owner only.")
        return
    if not global_bot_status:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is already globally powered OFF.")
        return
    global_bot_status = False
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot has been globally powered OFF. It will no longer process messages.")
    logger.info(f"[{update.effective_chat.id}] Global power OFF command used by owner.")

# --- Broadcast command for Owner only, preserving formatting ---
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is for the bot owner only.")
        return
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Please provide a message to broadcast after the command.")
        return
    message_to_send = " ".join(context.args)
    message_to_send = message_to_send.replace('\n', '<br>')
    success_count = 0
    failure_count = 0
    global known_users
    if not known_users:
        load_known_users()
    for chat_id in known_users:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_to_send,
                parse_mode='HTML'
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error broadcasting to chat {chat_id}: {e}")
            failure_count += 1
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Broadcast complete! Sent to {success_count} chats. Failed for {failure_count} chats.")
    logger.info(f"Broadcast sent by admin. Success: {success_count}, Failure: {failure_count}")

# --- Command to get a photo's file ID ---
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is for the bot owner only.")
        return
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo_file_id = update.message.reply_to_message.photo[-1].file_id
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Photo File ID:\n`{photo_file_id}`", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Please reply to a photo with this command to get its ID.")

# --- Broadcast with photo command ---
async def broadcast_photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != BROADCAST_ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this command is for the bot owner only.")
        return
    if len(context.args) < 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /broadcast_photo <photo_file_id> <message>")
        return
    photo_file_id = context.args[0]
    message_to_send = " ".join(context.args[1:])
    message_to_send = message_to_send.replace('\n', '<br>')
    success_count = 0
    failure_count = 0
    global known_users
    if not known_users:
        load_known_users()
    for chat_id in known_users:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file_id,
                caption=message_to_send,
                parse_mode='HTML'
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error broadcasting photo to chat {chat_id}: {e}")
            failure_count += 1
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Photo broadcast complete! Sent to {success_count} chats. Failed for {failure_count} chats.")
    logger.info(f"Photo broadcast sent by admin. Success: {success_count}, Failure: {failure_count}")

# --- Forward a message to all known chats ---
async def forward_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != BROADCAST_ADMIN_ID:
