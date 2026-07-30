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
GIF_ADOPT_PROPOSE = "CgACAgQAAyEFAATHcBuEAAIFkWl1mUcwFgJl9Ve1es4EE_ul68m5AAKyAwAC8l61Ury452c9ObZcOAQ"
GIF_ADOPT_SUCCESS = "CgACAgQAAyEFAATHcBuEAAIFlGl1mYmjGD1fiSICUHCb7cMXs6kGAALRAwACWsiFUHrQMp0NU8q6OAQ"
GIF_DISOWN = "CgACAgQAAyEFAATHcBuEAAIFl2l1mccxaEpjzmhE1jS0pTXMhQABcwACCQMAAokzBFPNK5Q1uVODAAE4BA"
GIF_RUNAWAY = "CgACAgQAAyEFAATHcBuEAAIFmml1mi5CWeLANRH_oIBft0DNiRWYAAJ-BwACx0zNUMqZZyrp8yMGOAQ"

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

    # --- FIX: Updated callback_data to match handler logic ---
    keyboard = [
        [
            InlineKeyboardButton("👤 Profile", callback_data="game:profile"), 
            InlineKeyboardButton("🎒 Inventory", callback_data="game:menu:assets") 
        ],
        [
            InlineKeyboardButton("💼 Work", callback_data="game:action:work"),      
            InlineKeyboardButton("🚜 Farm", callback_data="game:action:farm")        
        ],
        [
            # Yahan sahi data 'game:menu:pvp' aur 'game:menu:gamble' use kiya hai
            InlineKeyboardButton("⚔️ Arena", callback_data="game:menu:pvp"),       
            InlineKeyboardButton("🎰 Gamble", callback_data="game:menu:gamble")         
        ],
        [
            InlineKeyboardButton("🏪 Shop", callback_data="game:menu:shop"),         
            InlineKeyboardButton("🏦 Bank", callback_data="game:menu:bank")          
        ],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="game:menu:leaderboard")] 
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
# (See `handle_slots` further below — that's the version actually wired to /slots.)

async def shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Laila Black Market Menu — categories match the real SHOP_CATALOG buy flow."""
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
        [InlineKeyboardButton("⬅️ Back to Game", callback_data="game:menu:main")]
    ]
    text = "🏪 **Laila Black Market**\nSelect a category to browse and buy:"

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


async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Text version of the inventory/assets screen — usable directly as /inventory or /bag."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return

    weapon_data = _find_item("weapons", player_data.get("Weapon", ""))
    pet_data = _find_item("pets", player_data.get("Pet", ""))

    text = "🎒 **Your Inventory**\n━━━━━━━━━━━━━━━━━━\n"
    text += f"⚔️ **Weapon:** {weapon_data['name'] if weapon_data else 'None'}\n"
    text += f"🐾 **Pet:** {pet_data['name'] if pet_data else 'None'}\n\n"

    text += "**Consumables:**\n"
    inv = player_data.get("Inventory", {})
    has_items = False
    for item_id, count in inv.items():
        if count and count > 0:
            item_data = _find_item("items", item_id)
            name = item_data["name"] if item_data else item_id.title()
            text += f"• {name} x{count}\n"
            has_items = True
    if not has_items:
        text += "_Empty — visit `/shop` to stock up!_\n"

    text += "\n**Properties:**\n"
    assets = player_data.get("Assets", {})
    has_assets = False
    for category, item_list in assets.items():
        if not isinstance(item_list, list):
            continue
        for item_id in item_list:
            item_data = _find_item(category, item_id)
            name = item_data["name"] if item_data else f"{category}:{item_id}"
            text += f"• {name}\n"
            has_assets = True
    if not has_assets:
        text += "_None yet — flex a little, buy a Ferrari 🏎️_\n"

    await update.message.reply_text(text, parse_mode='Markdown')

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
# --- Shared job/action engine, used by BOTH the direct slash commands
#     (/work /farm /mine /crime /task) and the /game button menu, so the
#     numbers and cooldowns can never drift out of sync between the two. ---

JOB_FLAVOR = {
    "work":  ("👷‍♀️", "Work", ["clocked in and crushed it", "hustled hard at the office", "picked up a solid shift"]),
    "farm":  ("🚜", "Farm", ["harvested a great crop", "sold a truckload of veggies", "had a productive day on the farm"]),
    "mine":  ("⛏️", "Mine", ["struck a nice vein of ore", "hauled up a good load from the mine", "found some shiny gems"]),
    "task":  ("📋", "Task", ["completed a side gig", "finished an odd job", "delivered a package on time"]),
}

async def _perform_job_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action_name: str):
    """Runs a cooldown-gated earning action (work/farm/mine/task) and replies with the result."""
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    if not data:
        await update.effective_message.reply_text("❌ Error: Could not retrieve your data.")
        return

    last_key = f"Last{action_name.capitalize()}"
    is_ready, time_left = _check_cooldown(data.get(last_key, 0), COOLDOWNS[action_name])
    if not is_ready:
        emoji, label, _ = JOB_FLAVOR.get(action_name, ("⏳", action_name.capitalize(), [""]))
        await update.effective_message.reply_text(
            f"{emoji} You're still tired from your last **{label}**! Try again in `{time_left}`.",
            parse_mode='Markdown'
        )
        return

    gain = random.randint(*EARNINGS[action_name])
    xp_gain = random.randint(20, 50)

    bonus_text = ""
    if random.random() < 0.05:
        bonus = random.randint(500, 1500)
        gain += bonus
        bonus_text = f"\n✨ **Lucky break!** +${bonus:,} bonus!"

    data["Money"] += gain
    data["XP"] += xp_gain
    data[last_key] = time.time()

    old_level = data.get("Level", 1)
    new_level = (data["XP"] // 1000) + 1
    data["Level"] = new_level

    success = await update_player_data(data)
    if not success:
        await update.effective_message.reply_text("❌ Database update failed. Please try again.")
        return

    emoji, label, flavor_lines = JOB_FLAVOR.get(action_name, ("✅", action_name.capitalize(), ["got it done"]))
    flavor = random.choice(flavor_lines)
    msg = (
        f"{emoji} **{label} Complete!**\n"
        f"You {flavor} and earned `${gain:,}`!\n"
        f"⭐ XP: +{xp_gain}"
        f"{bonus_text}"
    )
    if new_level > old_level:
        msg += f"\n\n🎊 **LEVEL UP!** You're now Level {new_level}! (+$5,000 bonus banked on your next /profile check)"

    await update.effective_message.reply_text(msg, parse_mode='Markdown')


async def _perform_crime_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs /crime — a higher-risk, higher-reward action with a success/fail chance."""
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    if not data:
        await update.effective_message.reply_text("❌ Error: Could not retrieve your data.")
        return

    is_ready, time_left = _check_cooldown(data.get("LastCrime", 0), COOLDOWNS["crime"])
    if not is_ready:
        await update.effective_message.reply_text(
            f"🚔 The heat is still on you! Try again in `{time_left}`.", parse_mode='Markdown'
        )
        return

    data["LastCrime"] = time.time()

    if random.randint(1, 100) <= CRIME_RATES["chance"]:
        amount = random.randint(*CRIME_RATES["success"])
        data["Money"] += amount
        data["XP"] = data.get("XP", 0) + 40
        msg = f"😈 **Crime Successful!**\nYou pulled it off and scored `${amount:,}`!\n⭐ XP: +40"
    else:
        amount = random.randint(*CRIME_RATES["fail"])
        data["Money"] = max(0, data["Money"] - amount)
        msg = f"🚓 **Busted!**\nThe cops caught you and fined you `${amount:,}`."

    await update_player_data(data)
    await update.effective_message.reply_text(msg, parse_mode='Markdown')


async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _perform_job_action(update, context, "work")

async def farm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _perform_job_action(update, context, "farm")

async def mine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _perform_job_action(update, context, "mine")

async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _perform_job_action(update, context, "task")

async def crime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _perform_crime_action(update, context)


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
GIF_PROPOSE = "CgACAgQAAyEFAATHcBuEAAIFnml1m1e8hWcuovXtyGvmxh59RqjrAAJgBAAC1uOdUAx8PitI8A4EOAQ"
GIF_MARRY_SUCCESS = "CgACAgQAAyEFAATHcBuEAAIFoWl1m3stcC2wNxbKHs0iMgkHXCQTAAKkBwACifodU213DI59q0fMOAQ"
GIF_MARRY_REJECT = "CgACAgQAAyEFAATHcBuEAAIFpGl1m7PRD4P5ph0UzbWMYE33CH8nAAKbAwACmSQtUmq-XbExyEIgOAQ"

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
    
async def create_clan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new clan for $100,000."""
    user = update.effective_user
    
     # 1. Input Validation
    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/create_clan <Clan Name>`\nExample: `/create_clan Peaky Blinders`", parse_mode='Markdown')
        return

    clan_name = " ".join(context.args)
    
    # Limit clan name length
    if len(clan_name) > 20:
        await update.message.reply_text("❌ Clan name is too long! (Max 20 characters)")
        return

    # 2. Fetch Player Data
    data = await get_player_data(user.id, user.full_name)
    if not data:
        await update.message.reply_text("❌ Error loading your profile.")
        return

    # 3. Check Constraints
    current_clan = data.get('ClanName', 'None')
    if current_clan != "None" and current_clan != "0":
        await update.message.reply_text(f"❌ You are already in a clan: **{current_clan}**.\nYou must leave it first.", parse_mode='Markdown')
        return

    CLAN_COST = 100000
    if data['Money'] < CLAN_COST:
        await update.message.reply_text(f"💸 You need **${CLAN_COST:,}** to register a clan!\nYour balance: `${data['Money']:,}`", parse_mode='Markdown')
        return

    # 4. Process Transaction
    data['Money'] -= CLAN_COST
    data['ClanName'] = clan_name
    data['ClanRole'] = "Leader"

    # 5. Save Data
    if await update_player_data(data):
        msg = (
            f"🏴‍☠️ **CLAN ESTABLISHED!** 🏴‍☠️\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏰 **Clan Name:** {clan_name}\n"
            f"👑 **Leader:** {user.first_name}\n"
            f"💰 **Cost:** ${CLAN_COST:,}\n\n"
            f"⚠️ *Note: Other players can join if they know the exact name.*"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Database error. Clan creation failed.")


async def leave_clan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows a user to leave their current clan."""
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    if data.get('ClanName', 'None') == "None":
        await update.message.reply_text("❌ You are not in a clan!")
        return

    old_clan = data['ClanName']
    data['ClanName'] = "None"
    data['ClanRole'] = "None"
    
    await update_player_data(data)
    await update.message.reply_text(f"👋 You have left **{old_clan}**.", parse_mode='Markdown')


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

    # 4. Defense Check (Inventory is a dict of item_id -> count)
    inventory = target_data.get("Inventory", {})
    if isinstance(inventory, str):  # Handle if sheet returns a raw JSON string
        try:
            inventory = json.loads(inventory) if inventory else {}
        except Exception:
            inventory = {}
    if not isinstance(inventory, dict):
        inventory = {}

    if inventory.get("bodyguard", 0) > 0:
        inventory["bodyguard"] -= 1
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
            "CgACAgQAAyEFAATHcBuEAAIDlmlx4XZbdLsI-AGxmqlBcidUQbtGAAJTBgAC0SVEUJA3IrvmNBz6OAQ",
            "CgACAgQAAyEFAATHcBuEAAIDl2lx4XdkuWN7w6-fjVdZ7vGrvBgtAALsAgACu8gUU6xvuGs1-sZeOAQ"
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
        # --- FAIL -
        hp_loss = 30
        killer_data["Health"] = max(0, int(killer_data.get("Health", 100)) - hp_loss)
        await update_player_data(killer_data)
        
        await update.message.reply_text(
            f"Your assassination attempt on {_mention(target.id, target.full_name)} failed! 💥\n"
            f"You were injured in the struggle and lost **{hp_loss} HP**.",
            parse_mode='Markdown'
        )




async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    
    # --- 1. TRANSLATION LAYER (Legacy Fixes) ---
    # Standardize legacy buttons to new format
    if data == "game:shop" or data == "game_shop":
        data = "game:menu:shop"
    elif data == "game:bank" or data == "game_bank":
        data = "game:menu:bank"
    elif data == "game:work" or data == "game_work":
        data = "game:action:work"
    elif data == "game:farm" or data == "game_farm":
        data = "game:action:farm"
    elif data == "game:leaderboard":
        data = "game:menu:leaderboard"
    elif data == "game:pvp_menu" or data == "game_pvp_menu": 
        data = "game:menu:pvp"
    elif data == "game:gamble":
        data = "game:menu:gamble"

    parts = data.split(":")

    # --- 2. MAIN MENU HANDLER ---
    if data == "game:menu:main" or data == "game_main":
        await handle_game_menu(update, context)
        await query.answer()
        return

    # --- 3. PROFILE HANDLER (Fixed Markdown Crash) ---
    if data == "game:profile":
        player_data = await get_player_data(user.id, user.full_name)
        if not player_data:
            await query.answer("Error loading profile", show_alert=True)
            return
            
        badges = await get_badges(player_data)
        
        # CLEAN THE NAME TO PREVENT CRASHES
        safe_name = re.sub(r'[_*\[\]()~`>#+-=|{}.!]', '', user.first_name)
        
        profile_ui = (
            f"👤 **PLAYER PROFILE**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"NAME: **{safe_name}**\n"
            f"RANK: `{badges}`\n"
            f"LEVEL: `Lv. {player_data.get('Level', 1)}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"❤️ HEALTH: `{player_data['Health']}/100`\n"
            f"💰 WALLET: `${player_data['Money']:,}`\n"
            f"🏦 BANK: `${player_data['Bank']:,}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚔️ KILLS: `{player_data.get('Kills', 0)}` | 💀 DEATHS: `{player_data.get('Deaths', 0)}`\n"
            f"🏴‍☠️ CLAN: `{player_data.get('ClanName', 'None')}`"
        )
        kb = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="game:menu:main")]]
        await query.edit_message_text(profile_ui, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    # --- 4. GAMBLE MENU HANDLER ---
    if data == "game:menu:gamble":
        text = (
            "🎰 **LAILA CASINO** 🎰\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Feeling lucky? Test your fate here!\n\n"
            "**Available Games:**\n"
            "🔹 **Slots:** Spin the machine to win big!\n"
            "   Command: `/slots <amount>`\n"
            "   _Example: /slots 100_\n\n"
            "⚠️ _Warning: The house always wins... eventually._"
        )
        kb = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="game:menu:main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    # --- 5. PVP / ARENA MENU HANDLER (Consolidated) ---
    if data == "game:menu:pvp":
        text = (
            "⚔️ **BATTLE ARENA** ⚔️\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Rules of the streets:\n\n"
            "🔫 **Robbing:** Steal cash from others.\n"
            "   `/rob` (Reply to message)\n\n"
            "💀 **Killing:** End someone's game.\n"
            "   `/kill` (Reply to message)\n\n"
            "🛡️ **Defense:** Buy Bodyguards in Shop."
        )
        buttons = [
            [InlineKeyboardButton("🕵️ How to Rob", callback_data="game:help:rob")], # You can add handlers for these later
            [InlineKeyboardButton("🎯 How to Bounty", callback_data="game:help:bounty")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="game:menu:main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        return
        
    # --- 6. ACTIONS HANDLER (Work, Farm, Crime, etc.) ---
    if len(parts) > 2 and parts[1] == "action":
        action_name = parts[2]
        
        if action_name == 'heal':
            await handle_heal(update, context)
            await query.answer()
            return

        player_data = await get_player_data(user.id, user.full_name)
        if not player_data:
            await query.answer("Error loading data.", show_alert=True)
            return

        last_time_key = f"Last{action_name.capitalize()}"
        cooldown_time = COOLDOWNS.get(action_name, 0)
        is_ready, time_left = _check_cooldown(player_data.get(last_time_key, 0), cooldown_time)
        
        if not is_ready:
            await query.answer(f"⏳ Wait {time_left} before doing this again!", show_alert=True)
            return

        # Execute Action Logic
        player_data[last_time_key] = time.time()
        result_msg = ""
        xp_gain = random.randint(10, 50)
        
        if action_name in EARNINGS: 
            min_earn, max_earn = EARNINGS[action_name]
            amount = random.randint(min_earn, max_earn)
            if action_name == "daily":
                streak = player_data.get('StreakCount', 0) + 1
                player_data['StreakCount'] = streak
                amount = int(amount * (1 + (streak * 0.1)))
                result_msg = f"🎁 Daily Claimed! Streak: {streak} | Earned: ${amount:,}"
            else:
                result_msg = f"✅ {action_name.capitalize()} Successful! Earned: ${amount:,}"
            
            player_data["Money"] += amount
            player_data["XP"] += xp_gain

        elif action_name == "crime":
            if random.randint(1, 100) <= CRIME_RATES["chance"]:
                min_earn, max_earn = CRIME_RATES["success"]
                amount = random.randint(min_earn, max_earn)
                player_data["Money"] += amount
                player_data["XP"] += xp_gain
                result_msg = f"😈 Crime Successful! You stole ${amount:,}"
            else:
                min_loss, max_loss = CRIME_RATES["fail"]
                amount = random.randint(min_loss, max_loss)
                player_data["Money"] = max(0, player_data["Money"] - amount)
                result_msg = f"🚓 Busted! Police fined you ${amount:,}"

        await update_player_data(player_data)
        await handle_game_callback(update, context) # Refresh menu
        try:
             await query.answer(result_msg, show_alert=True)
        except:
             pass
        return

    # --- 7. SUB-MENUS (Actions, Bank, Assets, Leaderboard) ---
    
    # ACTIONS MENU
    if data == "game:menu:actions":
        player_data = await get_player_data(user.id, user.full_name)
        # Calculate cooldowns for display
        cd_display = {}
        for act in ["work", "farm", "mine", "crime", "task", "daily"]:
            _, t_left = _check_cooldown(player_data.get(f"Last{act.capitalize()}", 0), COOLDOWNS[act])
            cd_display[act] = t_left

        action_text = (
            f"⚡ **ACTIONS MENU** ⚡\n"
            f"Choose a job to earn money:\n\n"
            f"**Cooldown Status:**\n"
            f"🎁 **Daily**: `{cd_display['daily']}`\n"
            f"💼 **Work**: `{cd_display['work']}`\n"
            f"🚜 **Farm**: `{cd_display['farm']}`\n"
            f"⛏️ **Mine**: `{cd_display['mine']}`\n"
            f"🔫 **Crime**: `{cd_display['crime']}`\n"
            f"📋 **Task**: `{cd_display['task']}`"
        )
        keyboard = [
            [InlineKeyboardButton(f"🎁 Daily Reward", callback_data="game:action:daily")],
            [
                InlineKeyboardButton(f"💼 Work", callback_data="game:action:work"),
                InlineKeyboardButton(f"🚜 Farm", callback_data="game:action:farm"),
                InlineKeyboardButton(f"⛏️ Mine", callback_data="game:action:mine")
            ],
            [
                InlineKeyboardButton(f"🔫 Crime", callback_data="game:action:crime"),
                InlineKeyboardButton(f"📋 Task", callback_data="game:action:task")
            ],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]
        ]
        await query.edit_message_text(action_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # BANK MENU
    if data == "game:menu:bank":
        player_data = await get_player_data(user.id, user.full_name)
        bank_text = (
            f"🏦 **City Bank**\n"
            f"Secure your funds here.\n\n"
            f"💵 **Wallet:** `${player_data['Money']:,}`\n"
            f"💳 **Bank:** `${player_data['Bank']:,}`\n\n"
            f"**Commands:**\n"
            f"`/deposit <amount>`\n"
            f"`/withdraw <amount>`\n"
            f"`/gift <amount>` (Reply to user)"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
        await query.edit_message_text(bank_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # ASSETS MENU
    if data == "game:menu:assets":
        player_data = await get_player_data(user.id, user.full_name)
        assets_text = "**🎒 Inventory & Assets**\n\n**Items:**\n"
        for item_id, count in player_data.get("Inventory", {}).items():
            if count > 0: assets_text += f"• {item_id.title()}: x{count}\n"
        assets_text += "\n**Properties:**\n"
        for cat, items in player_data.get("Assets", {}).items():
            if items: assets_text += f"• {cat.title()}: {len(items)} items\n"

        keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
        await query.edit_message_text(assets_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # LEADERBOARD MENUS
    if data == "game:menu:leaderboard":
        await show_leaderboard_menu(update, context)
        return
    if len(parts) > 2 and parts[1] == "lb":
        await display_leaderboard(update, context, parts[2])
        return

    # --- 8. SHOP SYSTEM ---
    if data == "game:menu:shop":
        shop_text = "🏪 **Laila Black Market**\nSelect a category:"
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
        await query.edit_message_text(shop_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # Shop Category View
    if len(parts) > 3 and parts[1] == "shop" and parts[2] == "category":
        category = parts[3]
        if category not in SHOP_CATALOG:
            await query.answer("Empty Category", show_alert=True)
            return

        cat_text = f"🛒 **Shop: {category.replace('_', ' ').title()}**\n\n"
        keyboard = []
        for item in SHOP_CATALOG[category]:
            cat_text += f"▪️ **{item['name']}** - ${item['price']:,}\n_{item['description']}_\n\n"
            keyboard.append([InlineKeyboardButton(f"Buy {item['name']} (${item['price']:,})", callback_data=f"game:buy:{category}:{item['id']}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back to Shop", callback_data="game:menu:shop")])
        await query.edit_message_text(cat_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # Buy Item Handler
    if len(parts) > 3 and parts[1] == "buy":
        category, item_id = parts[2], parts[3]
        item_data = _find_item(category, item_id)
        if not item_data:
            await query.answer("Item not found.", show_alert=True)
            return

        player_data = await get_player_data(user.id, user.full_name)
        price = item_data['price']

        if player_data['Money'] < price:
            await query.answer(f"❌ Not enough money! You need ${price:,}", show_alert=True)
            return

        # Deduct Money & Add Item
        player_data['Money'] -= price
        
        if category == "items":
            if "Inventory" not in player_data: player_data["Inventory"] = {}
            player_data["Inventory"][item_id] = player_data["Inventory"].get(item_id, 0) + 1
        elif category == "weapons":
            player_data["Weapon"] = item_id
        elif category == "pets":
            player_data["Pet"] = item_id
        else: # Assets
            if "Assets" not in player_data: player_data["Assets"] = {}
            if category not in player_data["Assets"]: player_data["Assets"][category] = []
            if item_id in player_data["Assets"][category]:
                player_data['Money'] += price # Refund
                await query.answer("You already own this!", show_alert=True)
                return
            player_data["Assets"][category].append(item_id)

        await update_player_data(player_data)
        await query.answer(f"✅ Bought {item_data['name']}!", show_alert=True)
        return     

    


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

    
