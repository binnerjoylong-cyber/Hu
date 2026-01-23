# game.py
import logging
import gspread
import json
import time
import random
import re
import asyncio
from gspread import WorksheetNotFound
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes

# --- Global Game Variables ---
game_sheet = None
logger = logging.getLogger(__name__)

# --- NEW GAME CONSTANTS ---
GAME_SHEET_NAME = "laila_game_v2"
STARTING_MONEY = 500
STARTING_BANK = 0
STARTING_HEALTH = 100
# Adoption GIFs
GIF_ADOPT_PROPOSE = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3ZidXN6bm1oZ3R3eXlyZ3B6Z3B6Z3B6Z3B6Z3B6Z3B6Z3B6JmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/brsEO1JayBVja/giphy.gif"
GIF_ADOPT_SUCCESS = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3h6OHR0eXlyZ3B6Z3B6Z3B6Z3B6Z3B6Z3B6Z3B6JmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/MDJ9IbxxvDUQM/giphy.gif"
GIF_DISOWN = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3h6OHR0eXlyZ3B6Z3B6Z3B6Z3B6Z3B6Z3B6Z3B6JmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l0HlIDU8q079S37gc/giphy.gif"
GIF_RUNAWAY = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM3h6OHR0eXlyZ3B6Z3B6Z3B6Z3B6Z3B6Z3B6Z3B6JmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7ZetIsj6yALBg9BS/giphy.gif"

# Proposals storage
if 'proposals' not in globals():
    proposals = {"marry": {}, "adopt": {}}
# Cooldowns in seconds
COOLDOWNS = {
    "work": 20 * 60,    # 20 minutes
    "farm": 30 * 60,    # 30 minutes
    "crime": 15 * 60,   # 15 minutes
    "mine": 45 * 60,    # 45 minutes
    "rob": 30 * 60,     # 30 minutes (WAS 1 hour)
    "kill": 4 * 60 * 60, # 4 hours (WAS 6 hours)
    "heal": 5 * 60,     # 5 minutes
    "task": 3 * 60 * 60,  # 3 hours
    "daily": 23 * 60 * 60 # 23 hours
}

# Earnings & Risks
EARNINGS = {
    "work": (200, 800),
    "farm": (100, 1000),
    "mine": (500, 2500),
    "task": (1000, 5000),
    "daily": (3000, 7000)
}
CRIME_RATES = {"chance": 60, "success": (500, 2000), "fail": (300, 1000)}
# User request: >30%. We'll set rob percentage from 10% to 35% of cash.
ROB_RATES = {"chance": 40, "success_pct": (0.1, 0.35), "fail_hp_loss": 15}
# User request: 5 times/day. 6-hour cooldown is 4/day. We'll stick to 6 hours.
KILL_RATES = {"chance": 30, "cost": 5000, "success_hp_loss": 0, "fail_hp_loss": 25} # success_hp_loss 0, killer shouldn't die.

# --- ITEM CATALOG (RESTRUCTURED FOR VARIETY) ---
SHOP_ITEMS = {
    "Common": {
        "🥖 Bread": {"price": 100, "effect": "Restores 20 Health"},
        "🔪 Pocket Knife": {"price": 1500, "effect": "+5% Rob success"}
    },
    "Epic": {
        "🛡️ Kevlar Vest": {"price": 50000, "effect": "-50% damage from /kill"},
        "🔫 Glock-17": {"price": 75000, "effect": "+20% Kill success"}
    },
    "Legendary": {
        "👑 Laila's Crown": {"price": 1000000, "effect": "Tax Immunity + 2x Daily Rewards"},
        "🏎️ Ferrari": {"price": 5000000, "effect": "Instant /work cooldown"}
    }
}
ACHIEVEMENTS = {
    "richie_rich": {"threshold": 1000000, "label": "💰 Millionaire", "bonus": "5% higher Work pay"},
    "serial_killer": {"threshold": 50, "label": "💀 Assassin", "bonus": "+10% Kill success"},
    "loyal_player": {"threshold": 30, "label": "🔥 Devoted", "bonus": "2x Daily Rewards"}, # 30 day streak
}

async def get_badges(data):
    """Checks player data and returns a string of earned badges."""
    badges = []
    if data.get('Money', 0) + data.get('Bank', 0) >= 1000000:
        badges.append("💰")
    if data.get('Kills', 0) >= 50:
        badges.append("💀")
    if data.get('StreakCount', 0) >= 30:
        badges.append("🔥")
    
    return " ".join(badges) if badges else "🆕 Newbie"

# Helper to find an item in the new list-based catalog by its ID
def _find_item(category, item_id):
    if category in SHOP_CATALOG:
        for item in SHOP_CATALOG[category]:
            if item["id"] == item_id:
                return item
    return None


# --- ITEM CATALOG ---
# This dictionary structure is required for your handle_game_callback logic
SHOP_CATALOG = {
    "items": [
        {"id": "bandage", "name": "Bandage 🩹", "price": 100, "description": "Heals 10 HP.", "value": 10},
        {"id": "medkit", "name": "Medkit ✚", "price": 500, "description": "Heals 50 HP.", "value": 50},
        {"id": "bodyguard", "name": "Bodyguard 🛡️", "price": 50000, "description": "Stops one /rob or /kill attempt."}
    ],
    "weapons": [
        {"id": "knife", "name": "Knife 🔪", "price": 1000, "description": "+5% Rob/Kill chance.", "value": 5},
        {"id": "pistol", "name": "Pistol 🔫", "price": 5000, "description": "+10% Rob/Kill chance.", "value": 10},
        {"id": "glock", "name": "Glock-17 🔫", "price": 75000, "description": "+20% Kill success.", "value": 20}
    ],
    "pets": [
        {"id": "dog", "name": "Dog 🐶", "price": 10000, "description": "A loyal friend. -5% rob chance against you."},
        {"id": "cat", "name": "Cat 🐱", "price": 10000, "description": "A cute companion."}
    ],
    "vehicles": [
        {"id": "used_car", "name": "Used Car 🚗", "price": 25000, "description": "Basic transport."},
        {"id": "sports_car", "name": "Sports Car 🏎️", "price": 150000, "description": "Fast and flashy."},
        {"id": "ferrari", "name": "Ferrari 🏎️", "price": 5000000, "description": "Instant /work cooldown."}
    ],
    "yachts": [
        {"id": "small_yacht", "name": "Small Yacht 🛥️", "price": 750000, "description": "Rule the local seas."}
    ],
    "real_estate": [
        {"id": "house", "name": "House 🏡", "price": 150000, "description": "A place to call home."},
        {"id": "villa", "name": "Villa 🏰", "price": 750000, "description": "Live in luxury."}
    ]
}

# --- NEW DATA MODEL (22 Columns) ---
# Update this list at the top of your file
PLAYER_HEADERS = [
    "UserID", "UserName", "Money", "Bank", "Health", "MarriedToID", "ChildrenIDs",
    "Pet", "Inventory", "Assets", "Weapon", "LastWork", "LastFarm", "LastCrime",
    "LastMine", "LastRob", "LastKill", "LastHeal", "LastTask", "LastDaily",
    "Kills", "Deaths", "StreakCount", "XP", "Level", "Bounty", "ClanName", "ClanRole",
    "ParentID", "Rebirths" # <--- ADDED THESE
]

# --- In-memory proposal cache ---
# proposals["marry"]["target_id"] = "proposer_id"
# proposals["adopt"]["target_id"] = "proposer_id"
proposals = {
    "marry": defaultdict(int),
    "adopt": defaultdict(int)
}

# --- Game Initialization ---

def init_game_module(spreadsheet):
    global game_sheet
    try:
        # Try to open the existing sheet
        game_sheet = spreadsheet.worksheet(GAME_SHEET_NAME)
        logger.info(f"Game sheet '{GAME_SHEET_NAME}' loaded.")
    except gspread.WorksheetNotFound:
        # If deleted, create a new one with headers
        logger.warning(f"Sheet '{GAME_SHEET_NAME}' not found. Creating new one...")
        game_sheet = spreadsheet.add_worksheet(title=GAME_SHEET_NAME, rows="1000", cols="20")
        # Add the headers immediately so the bot knows where to put data
        game_sheet.append_row(PLAYER_HEADERS)
        logger.info(f"New sheet '{GAME_SHEET_NAME}' created with headers.")

def get_progress_bar(current, total, length=10):
    """Generates a visual bar like: [🟩🟩🟩⬜⬜⬜]"""
    filled_length = int(length * current // total)
    bar = "🟩" * filled_length + "⬜" * (length - filled_length)
    return f"[{bar}] {current}/{total}"

def get_status_emoji(health):
    if health > 70: return "😎"
    if health > 30: return "😟"
    return "💀"
# --- ELITE VISUAL HELPERS ---
def get_bar(current, total=100, length=10):
    """Generates a high-quality progress bar."""
    filled = int(length * current // total)
    bar = "🟩" * filled + "⬜" * (length - filled)
    return f"`{bar}` {current}%"

def format_money(amount):
    """Formats 1000000 into $1,000,000."""
    return f"${amount:,}"
# --- ADVANCED VISUAL HELPERS ---
def get_visual_bar(current, total, length=10):
    """Generates a professional-grade progress bar."""
    filled = int(length * current // total)
    bar = "🟩" * filled + "⬜" * (length - filled)
    return f"[{bar}] {current}%"

# game.py -> Inside handle_game_menu or game_menu function

    

async def handle_game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    # Progress bar for Health
    health_val = int(data.get('Health', 0))
    health_bar = get_progress_bar(health_val, 100)
    status = "💀" if health_val <= 0 else "❤️"
    
    text = (
        f"🏆 **LAILA LEGENDS: {user.first_name.upper()}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Wallet:** `${data['Money']:,}`\n"
        f"🏦 **Bank:** `${data['Bank']:,}`\n"
        f"❤️ **Health:** {health_bar} `{health_val}%`\n"
        f"⭐ **Level:** `{data.get('Level', 1)}` | **XP:** `{data.get('XP', 0)}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡️ *Choose your action below:* "
    )

    
    keyboard = [
        [
            InlineKeyboardButton("👤 Profile", callback_data="game:profile"),
            InlineKeyboardButton("🎒 Inventory", callback_data="game:inventory")
        ],
        [
            InlineKeyboardButton("💼 Work", callback_data="game:work"),       # Direct Work Action
            InlineKeyboardButton("🚜 Farm", callback_data="game:farm:menu")   # Opens Farm Menu
        ],
        [
            InlineKeyboardButton("⚔️ Arena", callback_data="game:arena:menu"), # Opens Arena Menu
            InlineKeyboardButton("🎰 Gamble", callback_data="game:gamble")
        ],
        [
            InlineKeyboardButton("🏪 Shop", callback_data="game:shop"),
            InlineKeyboardButton("🏦 Bank", callback_data="game:bank")
        ],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="game:leaderboard")]
    ]
    
    
    markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
# --- Helper Functions ---

def _format_time(seconds: int) -> str:
    """Formats seconds into a 'Xh Ym Zs' string."""
    if seconds <= 0:
        return "Ready"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h > 0: parts.append(f"{h}h")
    if m > 0: parts.append(f"{m}m")
    if s > 0 or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def _check_cooldown(last_time: float, cooldown: int) -> (bool, str):
    """Checks if a cooldown has passed. Returns (is_ready, time_remaining_str)."""
    time_passed = time.time() - last_time
    if time_passed >= cooldown:
        return True, "Ready"
    time_left = int(cooldown - time_passed)
    return False, _format_time(time_left)

def _mention(user_id: int, name: str) -> str:
    """Creates a Telegram Markdown mention."""
    name = re.sub(r'[_*\[\]()~`>#+-=|{}.!]', '', name) # Clean name for markdown
    return f"[{name}](tg://user?id={user_id})"

def _get_player_row(user_id: int) -> gspread.Cell | None:
    """Finds a player's row cell."""
    if not game_sheet:
        logger.error("game_sheet not initialized.")
        return None
    try:
        return game_sheet.find(str(user_id), in_column=1)
    except gspread.exceptions.CellNotFound:
        return None
    except Exception as e:
        logger.error(f"Error finding user {user_id}: {e}", exc_info=True)
        return None
async def get_player_data(user_id: int, user_name: str) -> dict | None:
    """Fetches or creates a player's account. Returns a dictionary mapped by headers."""
    global game_sheet
    if game_sheet is None:
        logger.error("Game sheet is not initialized!")
        return None

    # Use a thread for blocking gspread call
    cell = await asyncio.to_thread(_get_player_row, user_id)
    
    player_data = {}
    
    if cell:
        # --- USER FOUND: FETCH DATA ---
        row_values = await asyncio.to_thread(game_sheet.row_values, cell.row)
        
        # Map values to headers
        for i, header in enumerate(PLAYER_HEADERS):
            try:
                player_data[header] = row_values[i]
            except IndexError:
                # Agar koi naya column add hua hai jo sheet mein nahi hai
                player_data[header] = "0" if header not in ["UserName", "Pet", "Weapon", "ClanName", "ClanRole"] else "None"
        
        # Update username if it changed
        if player_data.get("UserName") != user_name:
            try:
                await asyncio.to_thread(game_sheet.update_cell, cell.row, 2, user_name)
                player_data["UserName"] = user_name
            except Exception as e:
                logger.error(f"Failed to update username: {e}")
                
    else:
        # --- USER NOT FOUND: CREATE NEW ACCOUNT (28 COLUMNS) ---
        default_row = {
            "UserID": str(user_id),
            "UserName": user_name,
            "Money": 500,
            "Bank": 0,
            "Health": 100,
            "MarriedToID": "0",
            "ChildrenIDs": "[]",
            "Pet": "None",
            "Inventory": "{}",
            "Assets": "{}",
            "Weapon": "None",
            "LastWork": 0.0, "LastFarm": 0.0, "LastCrime": 0.0, "LastMine": 0.0,
            "LastRob": 0.0, "LastKill": 0.0, "LastHeal": 0.0, "LastTask": 0.0, "LastDaily": 0.0,
            "Kills": 0,
            "Deaths": 0,
            "StreakCount": 0,
            "XP": 0,
            "Level": 1,
            "Bounty": 0,
            "ClanName": "None",
            "ClanRole": "None"
        }
        
        # Ensure values are in the correct header order
        new_row_values = [str(default_row.get(h, "0")) for h in PLAYER_HEADERS]
        try:
            await asyncio.to_thread(game_sheet.append_row, new_row_values)
            logger.info(f"✅ Created new game account for {user_name} ({user_id})")
            player_data = default_row
        except Exception as e:
            logger.error(f"❌ Failed to create account for {user_id}: {e}", exc_info=True)
            return None

    # --- SAFE TYPE CONVERSION & JSON PARSING ---
    # Is part ko hamesha 'try-except' ke andar rakhte hain taaki string "100" number ban sake
    try:
        # Integer conversions
        int_fields = ["UserID", "Money", "Bank", "Health", "Kills", "Deaths", "XP", "Level", "Bounty", "StreakCount"]
        for field in int_fields:
            if field in player_data:
                try:
                    # float conversion isliye taaki agar "100.0" likha ho toh crash na ho
                    player_data[field] = int(float(player_data[field]))
                except:
                    player_data[field] = 0 if field != "Level" else 1

        # Float/Time conversions
        for h in PLAYER_HEADERS:
            if h.startswith("Last"):
                try:
                    player_data[h] = float(player_data[h])
                except:
                    player_data[h] = 0.0

        # JSON Fields Parsing (ChildrenIDs, Inventory, Assets)
        json_fields = {"ChildrenIDs": [], "Inventory": {}, "Assets": {}}
        for field, default_val in json_fields.items():
            raw_val = player_data.get(field, str(default_val))
            try:
                parsed = json.loads(raw_val)
                player_data[field] = parsed if isinstance(parsed, type(default_val)) else default_val
            except:
                player_data[field] = default_val
        
        return player_data

    except Exception as e:
        logger.error(f"Critical data parsing error for {user_id}: {e}")
        return player_data

'''async def get_player_data(user_id: int, user_name: str) -> dict | None:
    """Fetches or creates a player's account. Returns a dictionary mapped by headers."""
    
    # Use a thread for blocking gspread call
    cell = await asyncio.to_thread(_get_player_row, user_id)
    
    player_data = {}
    
    if cell:
        # User found, fetch data
        row_values = await asyncio.to_thread(game_sheet.row_values, cell.row)
        
        # Map values to headers
        for i, header in enumerate(PLAYER_HEADERS):
            try:
                player_data[header] = row_values[i]
            except IndexError:
                player_data[header] = "" # Fill missing columns
        
        # Update username if it changed
        if player_data["UserName"] != user_name:
            await asyncio.to_thread(game_sheet.update_cell, cell.row, 2, user_name)
            player_data["UserName"] = user_name
            
    else:
        # User not found, create new account
        default_row = {
            "UserID": str(user_id),
            "UserName": user_name,
            "Money": STARTING_MONEY,
            "Bank": STARTING_BANK,
            "Health": STARTING_HEALTH,
            "MarriedToID": 0,
            "ChildrenIDs": "[]",
            "Pet": "",
            "Inventory": "{}", # { "item_id": count }
            "Assets": "{}",    # { "category": ["item_id_1", "item_id_2"] }
            "Weapon": "",      # "weapon_id"
            "LastWork": 0.0,
            "LastFarm": 0.0,
            "LastCrime": 0.0,
            "LastMine": 0.0,
            "LastRob": 0.0,
            "LastKill": 0.0,
            "LastHeal": 0.0,
            "LastTask": 0.0,
            "LastDaily": 0.0,
            "Kills": 0,
            "Deaths": 0
        }
        
        # Ensure values are in the correct header order
        new_row_values = [default_row.get(h, "") for h in PLAYER_HEADERS]
        try:
            await asyncio.to_thread(game_sheet.append_row, new_row_values)
            logger.info(f"Created new game account for {user_name} ({user_id})")
            player_data = default_row
        except Exception as e:
            logger.error(f"Failed to create new game account for {user_id}: {e}", exc_info=True)
            return None

    # --- Type Conversion and JSON Parsing ---
    try:
        player_data["UserID"] = int(player_data["UserID"])
        player_data["Money"] = int(player_data["Money"])
        player_data["Bank"] = int(player_data["Bank"])
        player_data["Health"] = int(player_data["Health"])
        player_data["MarriedToID"] = int(player_data["MarriedToID"])
        player_data["Kills"] = int(player_data["Kills"])
        player_data["Deaths"] = int(player_data["Deaths"])
        
        # Cooldowns
        for h in PLAYER_HEADERS:
            if h.startswith("Last"):
                player_data[h] = float(player_data[h])

        # JSON Fields
        # Handle potential data corruption or old format
        try:
            player_data["ChildrenIDs"] = json.loads(player_data["ChildrenIDs"])
            if not isinstance(player_data["ChildrenIDs"], list):
                player_data["ChildrenIDs"] = []
        except:
            player_data["ChildrenIDs"] = []

        try:
            player_data["Inventory"] = json.loads(player_data["Inventory"])
            if not isinstance(player_data["Inventory"], dict):
                player_data["Inventory"] = {}
        except:
            player_data["Inventory"] = {}

        try:
            player_data["Assets"] = json.loads(player_data["Assets"])
            if not isinstance(player_data["Assets"], dict):
                player_data["Assets"] = {}
        except:
            player_data["Assets"] = {}
        
        return player_data

    except (ValueError, TypeError) as e:
        logger.error(f"Data type error for user {user_id}: {e}. Returning raw data.")
        return player_data # Return as-is, let handler fail'''

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    badges = await get_badges(data)
    health_bar = get_visual_bar(data['Health'], 100) # Using the bar helper from earlier
    xp_progress = get_visual_bar(data.get('XP', 0) % 1000, 1000, length=8)

    profile_ui = (
        f"👤 **PLAYER PROFILE**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"NAME: **{user.first_name}**\n"
        f"RANK: `{badges}`\n"
        f"LEVEL: `Lv. {data.get('Level', 1)}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❤️ HEALTH: {health_bar}\n"
        f"⭐ XP: {xp_progress}\n"
        f"💰 WALLET: `${data['Money']:,}`\n"
        f"🏦 BANK: `${data['Bank']:,}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ KILLS: `{data.get('Kills', 0)}` | 🏴‍☠️ CLAN: `{data.get('ClanName', 'None')}`\n"
    )
    
    await update.message.reply_text(profile_ui, parse_mode='Markdown')

async def check_level_up(data, update, context):
    """
    Checks for level up, awards bonus, and sends a notification message.
    Use this inside command functions (like /work or /crime).
    """
    current_xp = data.get('XP', 0)
    current_level = data.get('Level', 1)
    new_level = (current_xp // 1000) + 1
    
    if new_level > current_level:
        data['Level'] = new_level
        # Give a Level-up bonus!
        data['Money'] += 5000 
        await update.effective_chat.send_message(
            f"🎊 **LEVEL UP!** 🎊\n\n{update.effective_user.first_name} reached **Level {new_level}**!\n"
            f"🎁 Reward: `$5,000` has been added to your wallet."
        )
    return data

async def update_player_data(player_data: dict) -> bool:
    """Updates a player's account data safely without range errors."""
    if not game_sheet:
        logger.error("game_sheet not initialized. Cannot update data.")
        return False
        
    try:
        # 1. Internal Level Up Check
        xp = player_data.get('XP', 0)
        new_level = (xp // 1000) + 1
        if new_level > player_data.get('Level', 1):
            player_data['Level'] = new_level
            logger.info(f"User {player_data['UserID']} internally leveled up to {new_level}")

        # 2. Find Player Row (Async)
        cell = await asyncio.to_thread(_get_player_row, player_data["UserID"])
        if not cell:
            logger.error(f"Cannot update: User {player_data['UserID']} not found in sheet.")
            return False
            
        row_idx = cell.row

        # 3. Map Data to Columns
        row_values = []
        for header in PLAYER_HEADERS:
            val = player_data.get(header, 0)
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            row_values.append(val)

        # 4. Sheet Update Logic (Sahi tareeka)
        # update_row use karne se range ka koi jhanjhat nahi rehta
        await asyncio.to_thread(game_sheet.update, f"A{row_idx}", [row_values])
        
        return True

    except Exception as e:
        logger.error(f"Error updating player data: {e}", exc_info=True)
        return False
        


# --- Main Game Command Handlers ---
# --- 🎰 THE CASINO ENGINE ---
async def slots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("🎰 **Usage:** `/slots <amount>`\nExample: `/slots 500`")
        return

    try:
        bet = int(context.args[0])
        if bet < 100:
            await update.message.reply_text("❌ Minimum bet is `$100`.")
            return
    except:
        await update.message.reply_text("❌ Please enter a valid number.")
        return

    data = await get_player_data(user.id, user.full_name)
    if data['Money'] < bet:
        await update.message.reply_text("💸 You don't have enough money in your wallet!")
        return

    # Slot items
    items = ["🍎", "💎", "🎰", "🔔", "🍒", "⭐"]
    result = [random.choice(items) for _ in range(3)]
    
    # Visual spinning effect
    spinning_msg = await update.message.reply_text("🎰 **SPINNING...**\n`[ ⌛ | ⌛ | ⌛ ]`")
    await asyncio.sleep(1) # Fake delay for suspense
    
    # Calculate Winnings
    win_multiplier = 0
    if result[0] == result[1] == result[2]:
        win_multiplier = 10 if result[0] == "💎" else 5
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        win_multiplier = 2
    
    if win_multiplier > 0:
        winnings = bet * win_multiplier
        data['Money'] += winnings
        status = f"🎉 **YOU WON!**\n💰 Payout: `${winnings:,}`"
    else:
        data['Money'] -= bet
        status = f"💀 **YOU LOST!**\n💸 Better luck next time."

    await update_player_data(data)
    
    final_view = (
        f"🎰 **LAILA CASINO** 🎰\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"  `[ {result[0]} | {result[1]} | {result[2]} ]`  \n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{status}\n"
        f"💰 **New Balance:** `${data['Money']:,}`"
    )
    await spinning_msg.edit_text(final_view, parse_mode='Markdown')


async def shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Laila Black Market Menu"""
    keyboard = [
        [
            InlineKeyboardButton("⚪ Common", callback_data="shop_tier_common"),
            InlineKeyboardButton("🟣 Epic", callback_data="shop_tier_epic")
        ],
        [InlineKeyboardButton("🟡 Legendary", callback_data="shop_tier_legendary")],
        [InlineKeyboardButton("🔙 Back to Game", callback_data="help_main")]
    ]
    text = "🛒 **LAILA BLACK MARKET**\nSelect a rarity tier to browse items:"
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in shop_menu: {e}")

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main game entry point. Shows profile and main menu."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    
    if not player_data:
        await update.message.reply_text("Sorry, there was an error accessing your game account. Please try again.")
        return
    # --- Build Profile Text ---
    # Fetch spouse name if married
    spouse_name = "Nobody"
    if player_data["MarriedToID"] != 0:
        try:
            spouse_chat = await context.bot.get_chat(player_data["MarriedToID"])
            spouse_name = _mention(spouse_chat.id, spouse_chat.full_name)
        except Exception:
            spouse_name = "Unknown User" # User might have left

    profile_text = (
        f"👤 **Profile for {_mention(user.id, user.full_name)}**\n\n"
        f"❤️ **Health**: `{player_data['Health']}/{STARTING_HEALTH}`\n"
        f"💰 **Money**: `${player_data['Money']:,}`\n"
        f"🏦 **Bank**: `${player_data['Bank']:,}`\n\n"
        f"**Family**\n"
        f"  ⚭ **Married to**: {spouse_name}\n"
        f"  👶 **Children**: `{len(player_data['ChildrenIDs'])}`\n\n"
        f"**Stats**\n"
        f"  • **Kills**: `{player_data['Kills']}`\n"
        f"  • **Deaths**: `{player_data['Deaths']}`"
    )

    # --- Build Main Menu Keyboard ---
    keyboard = [
        [
            InlineKeyboardButton("🧑‍🌾 Actions", callback_data="game:menu:actions"),
            InlineKeyboardButton("🏦 Bank", callback_data="game:menu:bank")
        ],
        [
            InlineKeyboardButton("🏪 Shop", callback_data="game:menu:shop"),
            InlineKeyboardButton("📋 My Assets", callback_data="game:menu:assets")
        ],
        [
            InlineKeyboardButton("👨‍👩‍👧‍👦 Family", callback_data="game:menu:family"),
            InlineKeyboardButton("🏆 Leaderboard", callback_data="game:menu:leaderboard")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send as new message if command, edit if callback
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=profile_text,
                reply_markup=reply_markup,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"Failed to edit message: {e}")
            await update.callback_query.answer()
    else:
        await update.message.reply_text(
            text=profile_text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
# --- 🏴‍☠️ THE CLAN SYSTEM ---
async def clan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    # Check if user is in a clan (You'll need a 'ClanName' column in your sheet)
    clan_name = data.get('ClanName', "None")
    
    if clan_name == "None":
        text = (
            "🏴‍☠️ **CLAN HEADQUARTERS**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "You are currently **Lone Wolf**.\n\n"
            "Join a clan to participate in Wars, pool resources, and dominate the leaderboard!\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔹 `/create_clan <name>` - Cost: $100,000\n"
            "🔹 `/join_clan <name>` - Join an existing gang"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    else:
        # Show Clan Dashboard
        text = (
            f"🏴‍☠️ **CLAN: {clan_name.upper()}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👑 **Leader:** `{data.get('ClanRole', 'Member')}`\n"
            f"💰 **Clan Bank:** `$0` (Coming Soon)\n"
            f"⚔️ **Clan Power:** `Level 1`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📢 *Work together to become the most feared gang!*"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
        
# --- 🏆 ELITE DAILY SYSTEM ---
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    now = time.time()
    
    last_daily = data.get('LastDaily', 0)
    # Reuse your existing cooldown checker
    is_ready, time_left = _check_cooldown(last_daily, COOLDOWNS["daily"])
    
    if not is_ready:
        await update.message.reply_text(f"⏳ **Too Early!**\nReturn in `{time_left}` to claim your reward.")
        return

    # Streak Logic: If they miss > 48 hours, streak resets
    streak = data.get('StreakCount', 0)
    if now - last_daily > 172800: # 48 hours
        streak = 1
    else:
        streak += 1

    # Bonus Multiplier: 10% extra per streak day
    multiplier = 1 + (streak * 0.1)
    base_reward = random.randint(3000, 7000)
    total_reward = int(base_reward * multiplier)

    data['Money'] += total_reward
    data['LastDaily'] = now
    data['StreakCount'] = streak
    await update_player_data(data)

    msg = (
        f"🌞 **DAILY REWARDS**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔥 **Streak:** `Day {streak}`\n"
        f"💰 **Earned:** `${total_reward:,}`\n"
        f"📈 **Bonus:** `{int(multiplier*100)-100}% extra`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 *Keep playing daily to reach a 2x bonus!*"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the top players by XP or Money."""
    # Agar aapne leaderboard logic abhi nahi likha hai, to ye temporary message dikhayega
    await update.message.reply_text("🏆 **Leaderboard**\n\nFeature coming soon! We are still ranking the top players.", parse_mode='Markdown')
# --- 🎯 GLOBAL BOUNTY SYSTEM ---
async def bounty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /bounty @user 5000"""
    user = update.effective_user
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ **Usage:** `/bounty @user <amount>`")
        return

    # Extract amount
    try:
        amount = int(re.sub(r'[^0-9]', '', context.args[1]))
        if amount < 1000:
            await update.message.reply_text("⚠️ Minimum bounty is $1,000.")
            return
    except:
        await update.message.reply_text("❌ Invalid amount.")
        return

    # Check if target is mentioned
    target_user = None
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == 'mention':
                # This requires resolving the username, for now we assume they reply to target
                pass
    
    # Simpler version: Bounty via Reply
    if not update.message.reply_to_message:
        await update.message.reply_text("🎯 **Tip:** Reply to the person you want to put a bounty on!")
        return
    
    target = update.message.reply_to_message.from_user
    if target.id == user.id:
        await update.message.reply_text("🤡 You can't put a bounty on yourself!")
        return

    # Deduct money from sender
    sender_data = await get_player_data(user.id, user.full_name)
    if sender_data['Money'] < amount:
        await update.message.reply_text("💸 You don't have enough money in your wallet!")
        return

    target_data = await get_player_data(target.id, target.full_name)
    current_bounty = target_data.get('Bounty', 0)
    
    sender_data['Money'] -= amount
    target_data['Bounty'] = current_bounty + amount
    
    await update_player_data(sender_data)
    await update_player_data(target_data)

    await update.message.reply_text(
        f"📢 **BOUNTY PLACED!**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Target:** {target.first_name}\n"
        f"💰 **Reward:** `${target_data['Bounty']:,}`\n"
        f"🕵️ **Contractor:** {user.first_name}\n\n"
        f"⚔️ *Anyone who uses /kill on them successfully will claim the reward!*"
    )
    
async def handle_game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    health_bar = get_progress_bar(data['Health'], 100)
    status = get_status_emoji(data['Health'])
    
    text = (
        f"🏆 **LAILA LEGENDS: {user.first_name.upper()}** {status}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Wallet:** `${data['Money']:,}`\n"
        f"🏦 **Bank:** `${data['Bank']:,}`\n"
        f"❤️ **Health:** {health_bar}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡️ *Use the buttons below to build your empire!*"
    )

    keyboard = [
        [InlineKeyboardButton("💼 Work", callback_data="game_work"), 
         InlineKeyboardButton("🌾 Farm", callback_data="game_farm")],
        [InlineKeyboardButton("🛒 Shop", callback_data="game_shop"), 
         InlineKeyboardButton("⚔️ Arena", callback_data="game_pvp")],
        [InlineKeyboardButton("📜 Inventory", callback_data="game_inventory")]
    ]
    
    markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
# --- NEW: /check COMMAND ---
async def handle_check_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the profile of the replied-to user."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user with `/check` to see their profile.")
        return

    target_user = update.message.reply_to_message.from_user
    if target_user.is_bot:
        await update.message.reply_text("You cannot check a bot's profile.")
        return
        
    player_data = await get_player_data(target_user.id, target_user.full_name)
    
    if not player_data:
        await update.message.reply_text("This user does not have a game account yet.")
        return

    # --- Build Profile Text ---
    spouse_name = "Nobody"
    if player_data["MarriedToID"] != 0:
        try:
            spouse_chat = await context.bot.get_chat(player_data["MarriedToID"])
            spouse_name = _mention(spouse_chat.id, spouse_chat.full_name)
        except Exception:
            spouse_name = "Unknown User"

    children_names = []
    for child_id in player_data.get("ChildrenIDs", []):
        try:
            child_chat = await context.bot.get_chat(child_id)
            children_names.append(_mention(child_chat.id, child_chat.full_name))
        except Exception: 
            children_names.append("Unknown Child")
    
    children_str = ", ".join(children_names) if children_names else "None"

    profile_text = (
        f"👤 **Profile for {_mention(target_user.id, target_user.full_name)}**\n\n"
        f"❤️ **Health**: `{player_data['Health']}/{STARTING_HEALTH}`\n"
        f"💰 **Money**: `${player_data['Money']:,}`\n"
        f"🏦 **Bank**: `${player_data['Bank']:,}`\n\n"
        f"**Family (Relationships)**\n"
        f"  ⚭ **Married to**: {spouse_name}\n"
        f"  👶 **Children**: {children_str}\n\n"
        f"**Stats**\n"
        f"  • **Kills**: `{player_data['Kills']}`\n"
        f"  • **Deaths**: `{player_data['Deaths']}`\n\n"
    )
    
    # --- Add Assets ---
    profile_text += "**Assets & Inventory**\n"
    
    weapon_data = _find_item("weapons", player_data.get("Weapon", ""))
    profile_text += f"  • **Weapon**: {weapon_data['name'] if weapon_data else 'None'}\n"

    pet_data = _find_item("pets", player_data.get("Pet", ""))
    profile_text += f"  • **Pet**: {pet_data['name'] if pet_data else 'None'}\n"
    
    asset_items = []
    for category, item_list in player_data.get("Assets", {}).items():
        if not isinstance(item_list, list): continue
        for item_id in item_list:
            item_data = _find_item(category, item_id)
            item_name = item_data["name"] if item_data else f"{category}:{item_id}"
            asset_items.append(item_name)
            
    profile_text += f"  • **Properties**: {', '.join(asset_items) if asset_items else 'None'}"

    await update.message.reply_text(
        text=profile_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

# --- LEADERBOARD (REFACTORED FOR MENUS) ---

async def show_leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main leaderboard category menu."""
    leaderboard_text = "🏆 **Leaderboards** 🏆\n\nSelect a category to view:"
    keyboard = [
        [
            InlineKeyboardButton("💰 Global Rich (Money+Bank)", callback_data="game:lb:rich"),
        ],
        [
            InlineKeyboardButton("🏦 Bank Balance", callback_data="game:lb:bank"),
            InlineKeyboardButton("⚔️ Most Kills", callback_data="game:lb:kills")
        ],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=leaderboard_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text=leaderboard_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
async def handle_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plays a slot machine game. Usage: /slots <amount>"""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)

    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return

    # 1. Parse Bet Amount
    if not context.args:
        await update.message.reply_text("🎰 Usage: `/slots <amount>` or `/slots all`", parse_mode='Markdown')
        return

    try:
        amount_str = context.args[0]
        money_on_hand = player_data["Money"]
        
        if amount_str.lower() == "all":
            bet = money_on_hand
        else:
            bet = int(amount_str)

        if bet <= 0:
            await update.message.reply_text("You must bet a positive amount!")
            return
        if bet > money_on_hand:
            await update.message.reply_text(f"You don't have enough cash! You only have `${money_on_hand:,}`.")
            return

    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a number.")
        return

    # 2. Spin the Slots
    # Symbols: 🍒 Cherry, 🍊 Orange, 🍇 Grape, 💎 Diamond, 7️⃣ Seven, 🔔 Bell
    symbols = ["🍒", "🍊", "🍇", "💎", "7️⃣", "🔔"]
    
    s1 = random.choice(symbols)
    s2 = random.choice(symbols)
    s3 = random.choice(symbols)

    # 3. Calculate Winnings
    winnings = 0
    result_message = ""
    
    # Jackpot (3 matching)
    if s1 == s2 == s3:
        multiplier = 10
        if s1 == "7️⃣": multiplier = 20 # Super Jackpot for 7s
        winnings = bet * multiplier
        result_message = f"🎉 **JACKPOT!** You won `${winnings:,}`! 🎉"
    
    # Mini-Win (2 matching)
    elif s1 == s2 or s2 == s3 or s1 == s3:
        multiplier = 2
        winnings = bet * multiplier
        result_message = f"✨ **Nice!** You matched 2 and won `${winnings:,}`."
    
    # Loss
    else:
        winnings = 0
        result_message = f"💥 You lost `${bet:,}`. Better luck next time!"

    # 4. Update Player Data
    player_data["Money"] -= bet
    player_data["Money"] += winnings
    
    # Save to sheet
    if await update_player_data(player_data):
        # 5. Send Result
        # Format: 
        # 🎰 SLOTS 🎰
        # | 🍒 | 💎 | 🍒 |
        # result message
        await update.message.reply_text(
            f"🎰 **SLOTS** 🎰\n\n"
            f"   | {s1} | {s2} | {s3} |\n\n"
            f"{result_message}\n"
            f"💰 New Balance: `${player_data['Money']:,}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("An error occurred while saving your game.")
async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the top 10 users for a specific category."""
    
    # This command handler now just shows the menu.
    # The callback handler will deal with showing the actual list.
    await show_leaderboard_menu(update, context)


async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, lb_type: str):
    """Fetches and displays a specific leaderboard."""
    
    query = update.callback_query
    await query.edit_message_text(text="🏆 **Leaderboard** 🏆\n\nFetching data...", parse_mode='Markdown')
    
    try:
        all_data = await asyncio.to_thread(game_sheet.get_all_values)
        if len(all_data) < 2:
            await query.edit_message_text("No one is on the leaderboard yet!")
            return
            
        header = all_data[0]
        rows = all_data[1:]
        
        # Find indices
        name_idx = header.index("UserName")
        
        leaderboard = []
        title = "🏆 **Global Rich List** 🏆\n_(Based on Money + Bank)_\n\n"
        
        if lb_type == "rich":
            money_idx = header.index("Money")
            bank_idx = header.index("Bank")
            for row in rows:
                try:
                    name = row[name_idx]
                    total_money = int(row[money_idx]) + int(row[bank_idx])
                    leaderboard.append((name, total_money))
                except (ValueError, IndexError, TypeError): continue
        
        elif lb_type == "bank":
            title = "🏦 **Top Bank Balances** 🏦\n\n"
            bank_idx = header.index("Bank")
            for row in rows:
                try:
                    name = row[name_idx]
                    total_money = int(row[bank_idx])
                    leaderboard.append((name, total_money))
                except (ValueError, IndexError, TypeError): continue
        
        elif lb_type == "kills":
            title = "⚔️ **Most Kills** ⚔️\n\n"
            kills_idx = header.index("Kills")
            for row in rows:
                try:
                    name = row[name_idx]
                    total_kills = int(row[kills_idx])
                    leaderboard.append((name, total_kills))
                except (ValueError, IndexError, TypeError): continue
        
        else:
            await query.edit_message_text("Unknown leaderboard type.")
            return

        leaderboard.sort(key=lambda x: x[1], reverse=True)
        
        response_text = title
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (name, total) in enumerate(leaderboard[:10]):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            clean_name = re.sub(r'[_*\[\]()~`>#+-=|{}.!]', '', name)
            
            # Format value
            value_str = f"{total:,}" if lb_type != "kills" else f"{total} kills"
            if lb_type != "kills": value_str = f"${value_str}"
            
            response_text += f"{prefix} {clean_name} - `{value_str}`\n"
            
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Leaderboards", callback_data="game:menu:leaderboard")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
        ])
            
        await query.edit_message_text(
            text=response_text,
            parse_mode='Markdown',
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Error in display_leaderboard: {e}", exc_info=True)
        await query.edit_message_text(text="An error occurred while fetching the leaderboard.")
async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # 1. Fetch player data
    data = await get_player_data(user.id, user.first_name)
    if not data:
        return await update.effective_message.reply_text("❌ Error: Could not retrieve your data.")

    now = time.time()
    last_work = data.get("LastWork", 0)

    # 2. Cooldown Check (20 Minutes)
    if now - last_work < COOLDOWNS["work"]:
        remaining = int((COOLDOWNS["work"] - (now - last_work)) // 60)
        return await update.effective_message.reply_text(
            f"⏳ You are exhausted! Come back in {remaining} minutes."
        )

    # 3. Calculate Earnings and XP
    gain = random.randint(EARNINGS["work"][0], EARNINGS["work"][1])
    xp_gain = 50
    
    # Lucky Bonus (5% chance)
    bonus_text = ""
    if random.random() < 0.05:
        bonus = random.randint(500, 1000)
        gain += bonus
        bonus_text = f"\n✨ **Jackpot!** You received an extra ₹{bonus} bonus!"

    # 4. Update Data Object
    data["Money"] += gain
    data["XP"] += xp_gain
    data["LastWork"] = now
    
    # Level Up Logic
    old_level = data["Level"]
    new_level = (data["XP"] // 1000) + 1
    data["Level"] = new_level

    # 5. Save to Google Sheets
    success = await update_player_data(data)
    
    if success:
        msg = (
            f"👷‍♂️ **Work Complete!**\n\n"
            f"💰 You earned: ₹{gain}\n"
            f"⭐ XP Gained: +{xp_gain}\n"
            f"{bonus_text}"
        )
        if new_level > old_level:
            msg += f"\n\n🎊 **LEVEL UP!** You are now Level {new_level}!"
            
        await update.effective_message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.effective_message.reply_text("❌ Database update failed. Please contact admin.")


async def handle_heal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Heals the user using items from their inventory."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return

    # 1. Check if health is already full
    if player_data["Health"] >= STARTING_HEALTH:
        await update.message.reply_text("Your health is already full! ❤️")
        return

    # 2. Check Cooldown
    is_ready, time_left = _check_cooldown(player_data["LastHeal"], COOLDOWNS["heal"])
    if not is_ready:
        await update.message.reply_text(f"You cannot heal yet! Wait {time_left}.")
        return

    # 3. Check Inventory & Select Item
    # Logic: Prioritize Medkit if HP missing >= 50, otherwise Bandage.
    inventory = player_data["Inventory"]
    item_to_use = None
    heal_amount = 0
    missing_hp = STARTING_HEALTH - player_data["Health"]

    # Check for Medkit first if we need a lot of health
    if missing_hp >= 50 and inventory.get("medkit", 0) > 0:
        item_to_use = "medkit"
        heal_amount = 50
    # Check for Bandage
    elif inventory.get("bandage", 0) > 0:
        item_to_use = "bandage"
        heal_amount = 10
    # Fallback: Use Medkit even if missing < 50 HP if it's all we have
    elif inventory.get("medkit", 0) > 0:
        item_to_use = "medkit"
        heal_amount = 50
    else:
        await update.message.reply_text(
            "You don't have any healing items! 🤕\n"
            "Buy **Bandages** or **Medkits** from the `/shop`."
        )
        return

    # 4. Apply Heal
    player_data["Health"] += heal_amount
    if player_data["Health"] > STARTING_HEALTH:
        player_data["Health"] = STARTING_HEALTH
    
    # 5. Consume Item & Update Cooldown
    player_data["Inventory"][item_to_use] -= 1
    player_data["LastHeal"] = time.time()
    
    if await update_player_data(player_data):
        item_name = "Medkit ✚" if item_to_use == "medkit" else "Bandage 🩹"
        await update.message.reply_text(
            f"You used a **{item_name}** and recovered **{heal_amount} HP**! ❤️\n"
            f"Current Health: `{player_data['Health']}/{STARTING_HEALTH}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("An error occurred while processing your heal.")
# --- Family Command Handlers ---
# --- GIF Links (Inhe aap badal sakte hain) ---
GIF_PROPOSE = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJmZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqJmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/L95W4M8qO1MeY/giphy.gif"
GIF_MARRY_SUCCESS = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJmZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqJmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/vS7pC7iH0AWRy/giphy.gif"
GIF_MARRY_REJECT = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJmZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqZzBqJmVwaT12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/26vUxO6iRj8T2K3K0/giphy.gif"

async def handle_marry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proposes marriage with a GIF."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the user you want to marry with `/marry`.")
        return

    proposer = update.effective_user
    target = update.message.reply_to_message.from_user

    if proposer.id == target.id:
        await update.message.reply_text("You can't marry yourself! 😄")
        return
    if target.is_bot:
        await update.message.reply_text("You can't marry a bot, silly.")
        return

    proposer_data = await get_player_data(proposer.id, proposer.full_name)
    target_data = await get_player_data(target.id, target.full_name)

    if not proposer_data or not target_data:
        await update.message.reply_text("Error accessing accounts. Please try again.")
        return

    # Safe check using int()
    if int(proposer_data.get("MarriedToID", 0)) != 0:
        await update.message.reply_text(f"You are already married! Use `/divorce` first.")
        return
        
    if int(target_data.get("MarriedToID", 0)) != 0:
        await update.message.reply_text(f"{target.full_name} is already married.")
        return
        
    proposals["marry"][target.id] = proposer.id
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"game:marry:accept:{proposer.id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"game:marry:decline:{proposer.id}")
        ]
    ]

    # Animation (GIF) ke sath proposal bhejna
    await update.message.reply_animation(
        animation=GIF_PROPOSE,
        caption=(
            f"Hey {_mention(target.id, target.full_name)}! 💍\n\n"
            f"{_mention(proposer.id, proposer.full_name)} is proposing to you! Do you accept?"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )



async def handle_adopt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proposes to adopt with GIF."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the user you want to adopt with `/adopt`.")
        return

    proposer = update.effective_user
    target = update.message.reply_to_message.from_user

    if proposer.id == target.id or target.is_bot:
        await update.message.reply_text("Invalid adoption request!")
        return

    p_data = await get_player_data(proposer.id, proposer.full_name)
    if not p_data or int(p_data.get("MarriedToID", 0)) == 0:
        await update.message.reply_text("❌ You must be married to adopt a child!")
        return

    proposals["adopt"][target.id] = proposer.id
    
    keyboard = [[
        InlineKeyboardButton("✅ Accept", callback_data=f"game:adopt:accept:{proposer.id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"game:adopt:decline:{proposer.id}")
    ]]

    await update.message.reply_animation(
        animation=GIF_ADOPT_PROPOSE,
        caption=f"👶 Hey {_mention(target.id, target.full_name)}!\n\n{_mention(proposer.id, proposer.full_name)} wants to adopt you! Do you accept?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_disown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parent disowns child (Reply to child)."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the child you want to disown.")
        return

    parent = update.effective_user
    child = update.message.reply_to_message.from_user

    p_data = await get_player_data(parent.id)
    children = p_data.get("ChildrenIDs", [])

    if child.id not in children:
        await update.message.reply_text("This user is not your child!")
        return

    children.remove(child.id)
    p_data["ChildrenIDs"] = children
    await update_player_data(p_data)

    await update.message.reply_animation(
        animation=GIF_DISOWN,
        caption=f"🚫 {_mention(parent.id, parent.full_name)} has disowned {_mention(child.id, child.full_name)}!",
        parse_mode='Markdown'
    )
async def handle_runaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Child runs away from home."""
    child = update.effective_user
    child_data = await get_player_data(child.id, child.full_name)

    parent_id = int(child_data.get("ParentID", 0))

    if parent_id == 0:
        await update.message.reply_text("You don't have parents to run away from! (You are an orphan 🥺)")
        return

    # Remove from Parent
    parent_data = await get_player_data(parent_id, "Parent")
    if child.id in parent_data["ChildrenIDs"]:
        parent_data["ChildrenIDs"].remove(child.id)
        await update_player_data(parent_data)

    # Remove from Spouse (if exists)
    spouse_id = int(parent_data.get("MarriedToID", 0))
    if spouse_id != 0:
        spouse_data = await get_player_data(spouse_id, "Spouse")
        if child.id in spouse_data["ChildrenIDs"]:
            spouse_data["ChildrenIDs"].remove(child.id)
            await update_player_data(spouse_data)

    # Reset Child
    child_data["ParentID"] = 0
    await update_player_data(child_data)

    await update.message.reply_animation(
        animation=GIF_RUNAWAY,
        caption=f"🏃‍♂️ {_mention(child.id, child.full_name)} has run away from home! The family is broken. 💔",
        parse_mode='Markdown'
    )

async def handle_divorce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Divorces the user's current spouse with a legal fee."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    
    # 1. Basic Validation
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return
        
    if int(player_data.get("MarriedToID", 0)) == 0:
        await update.message.reply_text("You are not married! 🤷‍♂️")
        return

    # 2. THE FINE LOGIC (Legal Fees)
    DIVORCE_COST = 5000
    if player_data["Money"] < DIVORCE_COST:
        await update.message.reply_text(
            f"⚖️ **Divorce Request Denied**\n\n"
            f"Lawyers are expensive! You need **${DIVORCE_COST:,}** to pay for legal fees.\n"
            f"💸 Your Wallet: `${player_data['Money']:,}`"
        )
        return

    spouse_id = player_data["MarriedToID"]
    
    # Get spouse data to update them too
    try:
        spouse_chat = await context.bot.get_chat(spouse_id)
        spouse_name = spouse_chat.full_name
    except:
        spouse_name = "Spouse"
        
    spouse_data = await get_player_data(spouse_id, spouse_name)

    # 3. Deduct Money & Execute Divorce
    player_data["Money"] -= DIVORCE_COST  # <--- Deduct the fine
    player_data["MarriedToID"] = 0
    await update_player_data(player_data)
    
    if spouse_data:
        spouse_data["MarriedToID"] = 0
        await update_player_data(spouse_data)
        
    # 4. Result Message
    await update.message.reply_text(
        f"💔 **Divorce Finalized**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"You paid **${DIVORCE_COST:,}** in legal fees to separate from {_mention(spouse_id, spouse_name)}.\n\n"
        f"You are now single again.", 
        parse_mode='Markdown'
    )
# --- NEW UTILITY COMMANDS ---
async def clan_war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /clanwar <EnemyClanName>"""
    user = update.effective_user
    attacker_data = await get_player_data(user.id, user.full_name)
    
    if attacker_data.get('ClanRole') != 'Leader':
        await update.message.reply_text("❌ Only the **Clan Leader** can declare war!")
        return

    if not context.args:
        await update.message.reply_text("⚔️ **Usage:** `/clanwar <ClanName>`")
        return

    target_clan = context.args[0]
    # Logic: Sum up the power of all members in both clans
    # The clan with higher 'Total XP' and 'Better Weapons' wins 70% of the time.
    
    win_chance = random.randint(1, 100)
    if win_chance > 50:
        msg = (
            f"🚩 **CLAN WAR VICTORY!** 🚩\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏴‍☠️ **Winners:** {attacker_data['ClanName']}\n"
            f"🏳️ **Losers:** {target_clan}\n\n"
            f"💰 Your clan looted **$50,000** from their treasury!"
        )
    else:
        msg = f"💀 **WAR DEFEAT!**\n\n{target_clan} defended their base. You lost **$25,000** in damages."
    
    await update.message.reply_text(msg, parse_mode='Markdown')
    
async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deposits money into the bank."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return

    try:
        amount_str = context.args[0] if context.args else "all"
        money_on_hand = player_data["Money"]
        
        if money_on_hand == 0:
            await update.message.reply_text("You have no money to deposit.")
            return

        amount = 0
        if amount_str == "all":
            amount = money_on_hand
        else:
            amount = int(amount_str)

        if amount <= 0:
            await update.message.reply_text("Please enter a positive amount.")
            return
        if amount > money_on_hand:
            await update.message.reply_text(f"You only have `${money_on_hand:,}` to deposit.")
            return
            
        player_data["Money"] -= amount
        player_data["Bank"] += amount
        
        if await update_player_data(player_data):
            await update.message.reply_text(f"Successfully deposited `${amount:,}` into your bank.\n\n**New Balance:**\nCash: `${player_data['Money']:,}`\nBank: `${player_data['Bank']:,}`")
        else:
            await update.message.reply_text("Error saving your transaction.")
    
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid amount. Use `/deposit <amount>` or `/deposit all`.")
    except Exception as e:
        logger.error(f"Error in /deposit: {e}", exc_info=True)
        await update.message.reply_text("An error occurred.")

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Withdraws money from the bank."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return

    try:
        amount_str = context.args[0] if context.args else "all"
        money_in_bank = player_data["Bank"]
        
        if money_in_bank == 0:
            await update.message.reply_text("You have no money in the bank.")
            return

        amount = 0
        if amount_str == "all":
            amount = money_in_bank
        else:
            amount = int(amount_str)

        if amount <= 0:
            await update.message.reply_text("Please enter a positive amount.")
            return
        if amount > money_in_bank:
            await update.message.reply_text(f"You only have `${money_in_bank:,}` in your bank.")
            return
            
        player_data["Bank"] -= amount
        player_data["Money"] += amount
        
        if await update_player_data(player_data):
            await update.message.reply_text(f"Successfully withdrew `${amount:,}` from your bank.\n\n**New Balance:**\nCash: `${player_data['Money']:,}`\nBank: `${player_data['Bank']:,}`")
        else:
            await update.message.reply_text("Error saving your transaction.")
    
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid amount. Use `/withdraw <amount>` or `/withdraw all`.")
    except Exception as e:
        logger.error(f"Error in /withdraw: {e}", exc_info=True)
        await update.message.reply_text("An error occurred.")

async def handle_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gifts money to a replied-to user."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user with `/gift <amount>`.")
        return
    if not context.args:
        await update.message.reply_text("Please specify an amount to gift. `/gift <amount>`")
        return

    gifter = update.effective_user
    target = update.message.reply_to_message.from_user

    if gifter.id == target.id:
        await update.message.reply_text("You can't gift yourself money.")
        return
    if target.is_bot:
        await update.message.reply_text("You can't gift money to a bot.")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            await update.message.reply_text("You must gift a positive amount.")
            return

        gifter_data = await get_player_data(gifter.id, gifter.full_name)
        target_data = await get_player_data(target.id, target.full_name)

        if not gifter_data or not target_data:
            await update.message.reply_text("Error accessing accounts.")
            return

        if gifter_data["Money"] < amount:
            await update.message.reply_text(f"You don't have enough money. You only have `${gifter_data['Money']:,}`.")
            return
            
        gifter_data["Money"] -= amount
        target_data["Money"] += amount
        
        await update_player_data(gifter_data)
        await update_player_data(target_data)
        
        await update.message.reply_text(
            f"{_mention(gifter.id, gifter.full_name)} has gifted `${amount:,}` to {_mention(target.id, target.full_name)}! 🎁",
            parse_mode='Markdown'
        )
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid amount. Use `/gift <amount>`.")
    except Exception as e:
        logger.error(f"Error in /gift: {e}", exc_info=True)
        await update.message.reply_text("An error occurred.")

# --- /ROB AND /KILL COMMANDS ---

async def handle_rob(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Robs a replied-to user."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user with `/rob` to attempt to rob them.")
        return

    robber = update.effective_user
    target = update.message.reply_to_message.from_user

    if robber.id == target.id:
        await update.message.reply_text("You can't rob yourself.")
        return
    if target.is_bot:
        await update.message.reply_text("You can't rob a bot.")
        return
        
    robber_data = await get_player_data(robber.id, robber.full_name)
    target_data = await get_player_data(target.id, target.full_name)

    if not robber_data or not target_data:
        await update.message.reply_text("Error accessing accounts.")
        return

    if target_data["Health"] <= 0:
        await update.message.reply_text(f"{target.full_name} is already dead. You can't rob them.")
        return
        
    is_ready, time_left = _check_cooldown(robber_data["LastRob"], COOLDOWNS["rob"])
    if not is_ready:
        await update.message.reply_text(f"You're too tired to rob. Try again in {time_left}.")
        return

    robber_data["LastRob"] = time.time()
    
    # Check for bodyguard
    if target_data["Inventory"].get("bodyguard", 0) > 0:
        target_data["Inventory"]["bodyguard"] -= 1
        await update_player_data(robber_data) # Save cooldown
        await update_player_data(target_data) # Save used bodyguard
        await update.message.reply_text(
            f"Your attempt to rob {_mention(target.id, target.full_name)} failed! 🛡️\n\nThey were protected by a **Bodyguard**, who caught you! The bodyguard has been used.",
            parse_mode='Markdown'
        )
        return

    # Calculate success chance
    weapon_bonus = _find_item("weapons", robber_data.get("Weapon", ""))
    bonus = weapon_bonus["value"] if weapon_bonus else 0
    success_chance = ROB_RATES["chance"] + bonus
    
    if random.randint(1, 100) <= success_chance:
        # Success
        if target_data["Money"] == 0:
            await update.message.reply_text(f"{_mention(target.id, target.full_name)} has no cash on hand! You get nothing.", parse_mode='Markdown')
            await update_player_data(robber_data) # Save cooldown
            return
            
        min_pct, max_pct = ROB_RATES["success_pct"]
        stolen_amount = int(target_data["Money"] * random.uniform(min_pct, max_pct))
        
        robber_data["Money"] += stolen_amount
        target_data["Money"] -= stolen_amount
        
        await update_player_data(robber_data)
        await update_player_data(target_data)
        
        await update.message.reply_text(
            f"💰 **Robbery Successful!** 💰\n\n{_mention(robber.id, robber.full_name)} successfully robbed `${stolen_amount:,}` from {_mention(target.id, target.full_name)}!",
            parse_mode='Markdown'
        )
    else:
        # Fail
        hp_loss = ROB_RATES["fail_hp_loss"]
        robber_data["Health"] -= hp_loss
        
        if robber_data["Health"] <= 0:
            robber_data["Health"] = 0
            robber_data["Deaths"] += 1
            await update_player_data(robber_data)
            await update.message.reply_text(f"You failed to rob {_mention(target.id, target.full_name)} and were caught! 💥\n\nYou lost {hp_loss} HP and **died**!", parse_mode='Markdown')
        else:
            await update_player_data(robber_data)
            await update.message.reply_text(f"You failed to rob {_mention(target.id, target.full_name)} and were caught! 💥\nYou lost {hp_loss} HP.", parse_mode='Markdown')

async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Attempts to kill a user based on Levels and Health (No Cost)."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user with `/kill` to attempt an assassination.")
        return

    killer = update.effective_user
    target = update.message.reply_to_message.from_user

    if killer.id == target.id:
        await update.message.reply_text("Suicide is not an option. 😄")
        return
    if target.is_bot:
        await update.message.reply_text("You can't kill a bot, they are immortal.")
        return
        
    killer_data = await get_player_data(killer.id, killer.full_name)
    target_data = await get_player_data(target.id, target.full_name)

    if not killer_data or not target_data:
        await update.message.reply_text("Error accessing accounts.")
        return

    # 1. Health Checks (Logical Consistency)
    if int(target_data.get("Health", 0)) <= 0:
        await update.message.reply_text(f"{target.full_name} is already dead. Let them rest in peace.")
        return

    if int(killer_data.get("Health", 0)) < 50:
        await update.message.reply_text("You are too weak to attack! Use `/heal` first (Minimum 50 HP required).")
        return
        
    # 2. Cooldown Check
    is_ready, time_left = _check_cooldown(killer_data.get("LastKill", 0), COOLDOWNS["kill"])
    if not is_ready:
        await update.message.reply_text(f"You need more time to plan. Try again in {time_left}.")
        return

    # Update cooldown immediately to prevent spamming while script processes
    killer_data["LastKill"] = time.time()

    # 3. Success Calculation (Calibrated for Rebirths)
    k_lvl = int(killer_data.get("Level", 1))
    k_reb = int(killer_data.get("Rebirths", 0))
    t_lvl = int(target_data.get("Level", 1))
    t_reb = int(target_data.get("Rebirths", 0))
    
    # Each rebirth acts like 100 levels
    killer_score = k_lvl + (k_reb * 100)
    target_score = t_lvl + (t_reb * 100)
    
    level_diff = killer_score - target_score
    success_chance = 35 + (level_diff * 2) # Slightly nerfed bonus for better balance
    success_chance = max(10, min(85, success_chance))

    # 4. Defense Check
    inventory = target_data.get("Inventory", [])
    if isinstance(inventory, str): # Handle if sheet returns string instead of list
        inventory = json.loads(inventory) if inventory else []

    if "bodyguard" in inventory:
        inventory.remove("bodyguard")
        target_data["Inventory"] = inventory
        await update_player_data(killer_data) 
        await update_player_data(target_data)
        await update.message.reply_text(
            f"Your attempt to kill {_mention(target.id, target.full_name)} failed! 🛡️\n\nThey were protected by a **Bodyguard**!",
            parse_mode='Markdown'
        )
        return

    # 5. Outcome Logic
    if random.randint(1, 100) <= success_chance:
        # --- SUCCESS ---
        target_data["Health"] = 0
        
        # Claim Bounty (Emotional Payoff)
        bounty = int(target_data.get("Bounty", 0))
        bounty_msg = ""
        if bounty > 0:
            killer_data["Money"] = int(killer_data.get("Money", 0)) + bounty
            target_data["Bounty"] = 0
            bounty_msg = f"\n💰 **BOUNTY CLAIMED:** You collected ${bounty:,}!"

        # XP Reward (Fixing string + int crash)
        killer_data["XP"] = int(killer_data.get("XP", 0)) + 500
        
        await update_player_data(killer_data)
        await update_player_data(target_data)
        
        kill_gifs = [
            "https://media.giphy.com/media/l3vRkvDA9uZYh2dGg/giphy.gif",
            "https://media.giphy.com/media/3o7TKwBfD4O3n0gpp6/giphy.gif"
        ]
        
        await update.message.reply_animation(
            animation=random.choice(kill_gifs),
            caption=(
                f"💀 **Assassination Successful!**\n\n"
                f"{_mention(killer.id, killer.full_name)} has killed "
                f"{_mention(target.id, target.full_name)}! {bounty_msg}\n"
                f"🌟 Reward: +500 XP"
            ),
            parse_mode='Markdown'
        )
    else:
        # --- FAIL ---
        hp_loss = 30
        killer_data["Health"] = max(0, int(killer_data.get("Health", 100)) - hp_loss)
        await update_player_data(killer_data)
        
        await update.message.reply_text(
            f"Your assassination attempt on {_mention(target.id, target.full_name)} failed! 💥\n"
            f"You were injured in the struggle and lost **{hp_loss} HP**.",
            parse_mode='Markdown'
        )
# --- Main Callback Query Handler ---
async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Don't answer yet, some logic might need to send a specific alert
    data = query.data
    user = query.from_user
    parts = data.split(":")

    # --- 1. ROUTING LEGACY CALLBACKS TO NEW SYSTEM ---
    if data == "game_work":
        await work_command(update, context)
        await query.answer()
        return
    elif data == "game_shop":
        # Redirect old shop button to new shop menu
        data = "game:menu:shop"
        parts = data.split(":") 

    # --- 2. MAIN MENU HANDLERS ---
    if data == "game:menu:main" or data == "game_main":
        await handle_game_menu(update, context)
        await query.answer()
        return

    # --- 3. ACTIONS (Link to full commands) ---
    if len(parts) > 2 and parts[1] == "action":
        action = parts[2]
        
        if action == "work":
            await work_command(update, context) # Use the full command logic
            await query.answer()
            # Update the menu to show new cooldowns
            # (You can copy the menu refresh logic from your existing code here)
            return
            
        elif action == "heal":
             await handle_heal(update, context)
             await query.answer()
             return

    # ... Rest of your existing logic for shop, family, etc. ...
    elif data == "game_pvp_menu":
        text = "⚔️ **BATTLE ARENA**\nChoose your combat style:"
        buttons = [
            [InlineKeyboardButton("🕵️ Rob Someone", callback_data="game_rob_help")],
            [InlineKeyboardButton("🎯 Place Bounty", callback_data="game_bounty_help")],
            [InlineKeyboardButton("🔙 Back", callback_data="game_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')

    # --- YAHAN SE FIX KIYA GAYA HAI --
    elif data == "game_actions_menu":
        # --- FIX START: Fetch data first ---
        player_data = await get_player_data(user.id, user.full_name)
        if not player_data:
            await query.answer("Error loading data.", show_alert=True)
            return
        # --- FIX END ---

        # Build text with cooldowns
        _, work_cd = _check_cooldown(player_data["LastWork"], COOLDOWNS["work"])
        _, farm_cd = _check_cooldown(player_data["LastFarm"], COOLDOWNS["farm"])
        _, crime_cd = _check_cooldown(player_data["LastCrime"], COOLDOWNS["crime"])
        _, mine_cd = _check_cooldown(player_data["LastMine"], COOLDOWNS["mine"])
        _, task_cd = _check_cooldown(player_data["LastTask"], COOLDOWNS["task"])
        _, daily_cd = _check_cooldown(player_data["LastDaily"], COOLDOWNS["daily"])
        
        action_text = (
            f"**Actions Menu**\n\n"
            f"**Cooldowns:**\n"
            f"  •  **Daily**: `{daily_cd}`\n"
            f"  •  **Work**: `{work_cd}`\n"
            f"  •  **Farm**: `{farm_cd}`\n"
            f"  •  **Mine**: `{mine_cd}`\n"
            f"  •  **Crime**: `{crime_cd}`\n"
            f"  •  **Task**: `{task_cd}`"
        )
        # ... (rest of the keyboard code remains the same)
        keyboard = [
            [InlineKeyboardButton(f"🎁 Daily", callback_data="game:action:daily")],
            [
                InlineKeyboardButton(f"🧑‍💻 Work", callback_data="game:action:work"),
                InlineKeyboardButton(f"🧑‍🌾 Farm", callback_data="game:action:farm"),
                InlineKeyboardButton(f"⛏️ Mine", callback_data="game:action:mine")
            ],
            [
                InlineKeyboardButton(f"💰 Crime", callback_data="game:action:crime"),
                InlineKeyboardButton(f"🎯 Task", callback_data="game:action:task")
            ],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
        ]
        await query.edit_message_text(action_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    

        # --- NEW LEADERBOARD MENU ---
        if data == "game:menu:leaderboard":
            await show_leaderboard_menu(update, context)
            return
            
        # --- NEW LEADERBOARD DISPLAY HANDLER ---
        if parts[1] == "lb":
            lb_type = parts[2] # "rich", "bank", "kills"
            await display_leaderboard(update, context, lb_type)
            return

        # --- NEW BANK MENU ---
        if data == "game:menu:bank":
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.edit_message_text("Error loading your data.")
                return

            bank_text = (
                f"🏦 **City Bank** 🏦\n\n"
                f"Welcome, {_mention(user.id, user.full_name)}.\n\n"
                f"**Cash**: `${player_data['Money']:,}`\n"
                f"**Bank**: `${player_data['Bank']:,}`\n\n"
                f"Use commands to manage your funds:\n"
                f"`/deposit <amount|all>`\n"
                f"`/withdraw <amount|all>`\n"
                f"`/gift <amount>` (Reply to user)\n\n"
                f"*Money in your bank is safe from robbers!*"
            )
            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
            await query.edit_message_text(bank_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)
            return

        if data == "game:menu:shop":
            shop_text = "🏪 **Welcome to the Shop**\n\nWhat category are you interested in?"
            keyboard = [
                [
                    InlineKeyboardButton("🩹 Items", callback_data="game:shop:category:items"),
                    InlineKeyboardButton("⚔️ Weapons", callback_data="game:shop:category:weapons")
                ],
                [
                    InlineKeyboardButton("🐾 Pets", callback_data="game:shop:category:pets"),
                    InlineKeyboardButton("🚗 Vehicles", callback_data="game:shop:category:vehicles")
                ],
                [
                    InlineKeyboardButton("🛥️ Yachts", callback_data="game:shop:category:yachts"),
                    InlineKeyboardButton("🏡 Real Estate", callback_data="game:shop:category:real_estate")
                ],
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
            ]
            await query.edit_message_text(shop_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        if data == "game:menu:family":
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.edit_message_text("Error loading your data.")
                return

            spouse_name = "Nobody"
            children_names = []
            
            if player_data["MarriedToID"]:
                try:
                    spouse_chat = await context.bot.get_chat(player_data["MarriedToID"])
                    spouse_name = _mention(spouse_chat.id, spouse_chat.full_name)
                except Exception: spouse_name = "Unknown User"
            
            for child_id in player_data["ChildrenIDs"]:
                try:
                    child_chat = await context.bot.get_chat(child_id)
                    children_names.append(_mention(child_chat.id, child_chat.full_name))
                except Exception: children_names.append("Unknown Child")
            
            children_str = ", ".join(children_names) if children_names else "None"

            family_text = (
                f"**Your Family**\n\n"
                f"  ⚭ **Spouse**: {spouse_name}\n"
                f"  👶 **Children**: {children_str}\n\n"
                f"Use commands to manage your family:\n"
                f"`/marry` - Reply to a user to propose.\n"
                f"`/adopt` - Reply to a user to adopt.\n"
                f"`/divorce` - Divorce your current spouse."
            )
            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
            await query.edit_message_text(family_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', disable_web_page_preview=True)
            return

        if data == "game:menu:assets":
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.edit_message_text("Error loading your data.")
                return

            assets_text = "**📋 My Assets & Inventory**\n\n"
            
            assets_text += "**Inventory:** (Consumables)\n"
            inv_items = []
            for item_id, count in player_data["Inventory"].items():
                item_data = _find_item("items", item_id)
                item_name = item_data["name"] if item_data else item_id
                inv_items.append(f"  • {item_name} (x{count})")
            assets_text += "\n".join(inv_items) if inv_items else "  • Empty\n"
                
            assets_text += "\n**Weapon:**\n"
            weapon_data = _find_item("weapons", player_data.get("Weapon", ""))
            assets_text += f"  • {weapon_data['name']}\n" if weapon_data else "  • None\n"

            assets_text += "\n**Pet:**\n"
            pet_data = _find_item("pets", player_data.get("Pet", ""))
            assets_text += f"  • {pet_data['name']}\n" if pet_data else "  • None\n"

            assets_text += "\n**Properties & Vehicles:** (Assets)\n"
            asset_items = []
            for category, item_list in player_data["Assets"].items():
                if not isinstance(item_list, list): continue # Skip corrupt data
                for item_id in item_list:
                    item_data = _find_item(category, item_id)
                    item_name = item_data["name"] if item_data else f"{category}:{item_id}"
                    asset_items.append(f"  • {item_name}")
            assets_text += "\n".join(asset_items) if asset_items else "  • Empty\n"


            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
            await query.edit_message_text(assets_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return
            
        # --- Action Handlers (REFACTORED FOR FEEDBACK) ---

        # -

        if parts[1] == "action":
            action_name = parts[2]
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.answer("Error loading your data.", show_alert=True)
                return

            if action_name == 'heal':
                await query.answer("Healing is not implemented as a button. Buy bandages/medkits and they will be used automatically.", show_alert=True)
                return

            last_time_key = f"Last{action_name.capitalize()}"
            cooldown = COOLDOWNS[action_name]
            
            is_ready, time_left = _check_cooldown(player_data[last_time_key], cooldown)
            
            if not is_ready:
                await query.answer(f"Please wait! Cooldown: {time_left}", show_alert=True)
                return

            # --- Handle different actions ---
            player_data[last_time_key] = time.time()
            reply_text = ""
            alert_text = "" # Text for the pop-up
            
            if action_name in EARNINGS:
                # TODO: This is where you would call your mini-game
                min_earn, max_earn = EARNINGS[action_name]
                amount = random.randint(min_earn, max_earn)
                player_data["Money"] += amount
                alert_text = f"You {action_name}ed and earned ${amount:,}!"
                reply_text = f"**Last Action:** Earned `${amount:,}` from `{action_name}`."
            
            elif action_name == "crime":
                # TODO: This is where you would call your mini-game
                if random.randint(1, 100) <= CRIME_RATES["chance"]:
                    min_earn, max_earn = CRIME_RATES["success"]
                    amount = random.randint(min_earn, max_earn)
                    player_data["Money"] += amount
                    alert_text = f"Crime successful! You got ${amount:,}."
                    reply_text = f"**Last Action:** Got `${amount:,}` from `crime`."
                else:
                    min_loss, max_loss = CRIME_RATES["fail"]
                    amount = random.randint(min_loss, max_loss)
                    player_data["Money"] -= amount
                    if player_data["Money"] < 0: player_data["Money"] = 0
                    alert_text = f"Crime failed! You were fined ${amount:,}."
                    reply_text = f"**Last Action:** Fined `${amount:,}` from `crime`."
            
            else:
                alert_text = "This action is not implemented yet."
                reply_text = "**Last Action:** Unknown."

            # Save data and notify user
            await update_player_data(player_data)
            await query.answer(alert_text, show_alert=True)
            
            # --- REFRESH THE MENU WITH NEW COOLDOWNS AND FEEDBACK ---
            _, work_cd = _check_cooldown(player_data["LastWork"], COOLDOWNS["work"])
            _, farm_cd = _check_cooldown(player_data["LastFarm"], COOLDOWNS["farm"])
            _, crime_cd = _check_cooldown(player_data["LastCrime"], COOLDOWNS["crime"])
            _, mine_cd = _check_cooldown(player_data["LastMine"], COOLDOWNS["mine"])
            _, task_cd = _check_cooldown(player_data["LastTask"], COOLDOWNS["task"])
            _, daily_cd = _check_cooldown(player_data["LastDaily"], COOLDOWNS["daily"])
            
            action_text = (
                f"**Actions Menu**\n\n"
                f"{reply_text}\n\n" # <-- ADDED FEEDBACK HERE
                f"**Cooldowns:**\n"
                f"  •  **Daily**: `{daily_cd}`\n"
                f"  •  **Work**: `{work_cd}`\n"
                f"  •  **Farm**: `{farm_cd}`\n"
                f"  •  **Mine**: `{mine_cd}`\n"
                f"  •  **Crime**: `{crime_cd}`\n"
                f"  •  **Task**: `{task_cd}`"
            )
            
            keyboard = [
                [InlineKeyboardButton(f"🎁 Daily", callback_data="game:action:daily")],
                [
                    InlineKeyboardButton(f"🧑‍💻 Work", callback_data="game:action:work"),
                    InlineKeyboardButton(f"🧑‍🌾 Farm", callback_data="game:action:farm"),
                    InlineKeyboardButton(f"⛏️ Mine", callback_data="game:action:mine")
                ],
                [
                    InlineKeyboardButton(f"💰 Crime", callback_data="game:action:crime"),
                    InlineKeyboardButton(f"🎯 Task", callback_data="game:action:task")
                ],
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
            ]
            await query.edit_message_text(action_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return # Already edited

        # --- Shop Navigation (REFACTORED) ---
        if parts[1] == "shop" and parts[2] == "category":
            category = parts[3]
            if category not in SHOP_CATALOG:
                await query.edit_message_text("Invalid shop category.")
                return

            # This is where you would implement photo-based navigation.
            # For now, we build a text list.
            shop_text = f"🏪 **Shop - {category.replace('_', ' ').title()}**\n\n"
            keyboard = []
            
            for item_data in SHOP_CATALOG[category]:
                shop_text += f"• **{item_data['name']}**\n"
                shop_text += f"  *Price*: `${item_data['price']:,}`\n"
                shop_text += f"  *Info*: {item_data['description']}\n\n"
                
                # Add a buy button for this item
                keyboard.append([
                    InlineKeyboardButton(f"Buy {item_data['name']}", callback_data=f"game:buy:{category}:{item_data['id']}")
                ])
                
            keyboard.append([InlineKeyboardButton("⬅️ Back to Shop", callback_data="game:menu:shop")])
            await query.edit_message_text(shop_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        # --- Buy Handlers (REFACTORED) ---
        # --- Buy Handlers (Fixed Logic) ---
        if parts[1] == "buy":
            # Data format: game:buy:category:item_id
            if len(parts) < 4:
                await query.answer("Invalid item data.", show_alert=True)
                return

            category, item_id = parts[2], parts[3]
            
            item_data = _find_item(category, item_id)
            if not item_data:
                await query.answer("This item is out of stock.", show_alert=True)
                return

            price = item_data["price"]

            # Re-fetch fresh player data to avoid money glitches
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.answer("Error loading wallet.", show_alert=True)
                return
                
            if player_data["Money"] < price:
                await query.answer(f"❌ You need ${price:,} but only have ${player_data['Money']:,}!", show_alert=True)
                return

            # --- DEDUCT MONEY ---
            player_data["Money"] -= price
            reply_text = f"✅ Purchased {item_data['name']} for ${price:,}!"

            # --- ADD ITEM LOGIC ---
            if category == "items":
                # Ensure inventory is a dict
                if isinstance(player_data["Inventory"], str): 
                    player_data["Inventory"] = json.loads(player_data["Inventory"])
                player_data["Inventory"][item_id] = player_data["Inventory"].get(item_id, 0) + 1
            
            elif category == "weapons":
                if player_data.get("Weapon") == item_id:
                    player_data["Money"] += price # Refund
                    await query.answer("You already have this weapon!", show_alert=True)
                    return 
                player_data["Weapon"] = item_id
            
            elif category == "pets":
                player_data["Pet"] = item_id

            elif category in ["vehicles", "real_estate", "yachts"]:
                # Ensure Assets is a dict
                if isinstance(player_data["Assets"], str): 
                    player_data["Assets"] = json.loads(player_data["Assets"])
                
                # Initialize category list if missing
                if category not in player_data["Assets"] or not isinstance(player_data["Assets"][category], list):
                    player_data["Assets"][category] = []
                
                if item_id in player_data["Assets"][category]:
                    player_data["Money"] += price # Refund
                    await query.answer("You already own this!", show_alert=True)
                    return
                
                player_data["Assets"][category].append(item_id)

            # Save
            if await update_player_data(player_data):
                await query.answer(reply_text, show_alert=True)
                # Optional: Refresh the menu to show updated balance
            else:
                await query.answer("Database error! Purchase cancelled.", show_alert=True)
            return

        '''
        if parts[1] == "buy":
            category, item_id = parts[2], parts[3]
            
            item_data = _find_item(category, item_id)
            if not item_data:
                await query.answer("This item does not exist.", show_alert=True)
                return

            price = item_data["price"]

            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.answer("Error loading your data.", show_alert=True)
                return
                
            if player_data["Money"] < price:
                await query.answer(f"You don't have enough money! You need ${price:,}.", show_alert=True)
                return

            # Handle different buy types
            player_data["Money"] -= price
            reply_text = f"You bought 1 {item_data['name']}!"

            if category == "items":
                player_data["Inventory"][item_id] = player_data["Inventory"].get(item_id, 0) + 1
            
            elif category == "weapons":
                if player_data.get("Weapon") == item_id:
                    player_data["Money"] += price # Refund
                    await query.answer(f"You already have this weapon equipped.", show_alert=True)
                    return 
                player_data["Weapon"] = item_id
            
            elif category == "pets":
                if player_data.get("Pet") == item_id:
                    player_data["Money"] += price # Refund
                    await query.answer(f"You already have this pet.", show_alert=True)
                    return
                player_data["Pet"] = item_id

            elif category in ["vehicles", "real_estate", "yachts"]:
                # Initialize asset category as list if not present
                if category not in player_data["Assets"] or not isinstance(player_data["Assets"].get(category), list):
                    player_data["Assets"][category] = []
                
                # Check if user already owns this specific item
                if item_id in player_data["Assets"][category]:
                    player_data["Money"] += price # Refund
                    await query.answer(f"You already own this.", show_alert=True)
                    return
                
                # Add item to the list
                player_data["Assets"][category].append(item_id)

            # Save and notify
            
            # ... (Existing buy logic above) ...
            await update_player_data(player_data)
            await query.answer(reply_text, show_alert=True)
            return
            '''
    # --- Family Proposal Handlers (Marry & Adopt) ---
    # Check if it is a family action and has enough data parts
    # Format expected: game:marry:accept:12345
    if len(parts) >= 4 and parts[1] in ["marry", "adopt"]:
        try:
            action = parts[2]       # accept / decline
            proposer_id = int(parts[3])
            target = user           # The user clicking the button
            
            # --- MARRIAGE CALLBACK LOGIC ---
            if parts[1] == "marry":
                if proposals["marry"].get(target.id) != proposer_id:
                    await query.answer("This proposal has expired or is invalid.", show_alert=True)
                    return

                del proposals["marry"][target.id] 
                try:
                    await query.message.delete() # Delete the proposal message
                except:
                    pass
                
                if action == "decline":
                    await context.bot.send_animation(
                        chat_id=query.message.chat_id,
                        animation=GIF_MARRY_REJECT,
                        caption=f"💔 {_mention(target.id, target.full_name)} has declined the marriage proposal.",
                        parse_mode='Markdown'
                    )
                    return

                if action == "accept":
                    proposer_data = await get_player_data(proposer_id, "Proposer")
                    target_data = await get_player_data(target.id, target.full_name)
                    
                    # Check if already married
                    if (int(proposer_data.get("MarriedToID", 0)) != 0) or (int(target_data.get("MarriedToID", 0)) != 0):
                        await context.bot.send_message(query.message.chat_id, "One of you is already married. Proposal cancelled.")
                        return
                        
                    proposer_data["MarriedToID"] = target.id
                    target_data["MarriedToID"] = proposer_id
                    
                    await update_player_data(proposer_data)
                    await update_player_data(target_data)
                    
                    await context.bot.send_animation(
                        chat_id=query.message.chat_id,
                        animation=GIF_MARRY_SUCCESS,
                        caption=f"🎉 **Congratulations!** 🎉\n\n{_mention(proposer_id, proposer_data['UserName'])} and {_mention(target.id, target_data['UserName'])} are now married!",
                        parse_mode='Markdown'
                    )
                    return

            # --- ADOPTION CALLBACK LOGIC ---
        
            elif parts[1] == "adopt":
                if proposals["adopt"].get(target.id) != proposer_id:
                    await query.answer("This adoption offer has expired or is invalid.", show_alert=True)
                    return

                del proposals["adopt"][target.id] 
                try:
                    await query.message.delete()
                except:
                    pass
                
                if action == "decline":
                    await context.bot.send_animation(
                        chat_id=query.message.chat_id,
                        animation=GIF_MARRY_REJECT,
                        caption=f"❌ {_mention(target.id, target.full_name)} has declined the adoption.",
                        parse_mode='Markdown'
                    )
                    return

                
                if action == "accept":
                    proposer_data = await get_player_data(proposer_id, "Proposer")

                    if not proposer_data or int(proposer_data.get("MarriedToID", 0)) == 0:
                        await context.bot.send_message(query.message.chat_id, "The adopter is no longer married. Offer cancelled.")
                        return
                        
                    # Add child if not already there
                    if target.id not in proposer_data["ChildrenIDs"]:
                        proposer_data["ChildrenIDs"].append(target.id)
                        await update_player_data(proposer_data)
                    spouse_id = proposer_data["MarriedToID"]
                    if spouse_id:
                        spouse_data = await get_player_data(spouse_id, "Spouse")
                        if target.id not in spouse_data["ChildrenIDs"]:
                            spouse_data["ChildrenIDs"].append(target.id)
                            await update_player_data(spouse_data)
                            
                    child_data = await get_player_data(target.id, target.full_name)
                    child_data["ParentID"] = proposer_id  # Primary parent
                    await update_player_data(child_data)

                    await context.bot.send_animation(
                        chat_id=query.message.chat_id,
                        animation=GIF_ADOPT_SUCCESS,
                        caption=(
                            f"🎉 **Welcome to the Family!** 🎉\n\n"
                            f"{_mention(target.id, target.full_name)} has been adopted by "
                            f"{_mention(proposer_id, proposer_data['UserName'])} and their spouse!"
                        ),
                        parse_mode='Markdown'
                    )
                    return
                

        except Exception as e:
            logger.error(f"Error in family callback: {e}", exc_info=True)
            await query.answer("An error occurred.", show_alert=True)

    
