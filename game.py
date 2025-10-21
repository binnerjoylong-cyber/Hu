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

# Cooldowns in seconds
COOLDOWNS = {
    "work": 20 * 60,    # 20 minutes
    "farm": 30 * 60,    # 30 minutes
    "crime": 15 * 60,   # 15 minutes
    "mine": 45 * 60,    # 45 minutes
    "rob": 60 * 60,     # 1 hour
    "kill": 6 * 60 * 60, # 6 hours
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
ROB_RATES = {"chance": 40, "success_pct": (0.1, 0.3), "fail_hp_loss": 10}
KILL_RATES = {"chance": 30, "cost": 5000, "success_hp_loss": 100, "fail_hp_loss": 25}

# --- ITEM CATALOG (FOR VARIETY) ---
SHOP_CATALOG = {
    "items": {
        "bandage": {"name": "Bandage 🩹", "price": 100, "description": "Heals 10 HP.", "value": 10},
        "medkit": {"name": "Medkit ✚", "price": 500, "description": "Heals 50 HP.", "value": 50}
    },
    "weapons": {
        "knife": {"name": "Knife 🔪", "price": 1000, "description": "+5% Rob/Kill chance.", "value": 5},
        "pistol": {"name": "Pistol 🔫", "price": 5000, "description": "+10% Rob/Kill chance.", "value": 10}
    },
    "pets": {
        "dog": {"name": "Dog 🐶", "price": 10000, "description": "A loyal friend. -5% rob chance against you."},
        "cat": {"name": "Cat 🐱", "price": 10000, "description": "A cute companion. Gives $1-100 every hour."}
    },
    "vehicles": {
        "car": {"name": "Used Car 🚗", "price": 25000, "description": "Needed for some tasks."},
        "plane": {"name": "Private Plane ✈️", "price": 1000000, "description": "Flex on everyone."},
        "yacht": {"name": "Yacht 🛥️", "price": 3000000, "description": "Rule the seas."}
    },
    "real_estate": {
        "house": {"name": "House 🏡", "price": 150000, "description": "A place to call home."},
        "villa": {"name": "Villa 🏰", "price": 750000, "description": "Live in luxury."},
        "island": {"name": "Private Island 🏝️", "price": 10000000, "description": "The ultimate asset."}
    }
}

# --- NEW DATA MODEL (22 Columns) ---
PLAYER_HEADERS = [
    "UserID", "UserName", "Money", "Bank", "Health", "MarriedToID", "ChildrenIDs",
    "Pet", "Inventory", "Assets", "Weapon", "LastWork", "LastFarm", "LastCrime",
    "LastMine", "LastRob", "LastKill", "LastHeal", "LastTask", "LastDaily",
    "Kills", "Deaths"
]

# --- In-memory proposal cache ---
# proposals["marry"]["target_id"] = "proposer_id"
# proposals["adopt"]["target_id"] = "proposer_id"
proposals = {
    "marry": defaultdict(int),
    "adopt": defaultdict(int)
}

# --- Game Initialization ---
def init_game_module(spreadsheet: gspread.Spreadsheet):
    """Initializes the game_sheet from the main bot."""
    global game_sheet
    try:
        game_sheet = spreadsheet.worksheet(GAME_SHEET_NAME)
        logger.info(f"Connected to existing game sheet: '{GAME_SHEET_NAME}'")
    except WorksheetNotFound:
        try:
            game_sheet = spreadsheet.add_worksheet(GAME_SHEET_NAME, rows="2000", cols=len(PLAYER_HEADERS))
            game_sheet.append_row(PLAYER_HEADERS)
            logger.info(f"Created new game sheet: '{GAME_SHEET_NAME}'")
        except Exception as e:
            logger.error(f"Failed to create new game sheet: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to initialize game module: {e}", exc_info=True)

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
            "Inventory": "{}",
            "Assets": "{}",
            "Weapon": "",
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
        player_data["ChildrenIDs"] = json.loads(player_data["ChildrenIDs"])
        player_data["Inventory"] = json.loads(player_data["Inventory"])
        player_data["Assets"] = json.loads(player_data["Assets"])
        
        return player_data

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Data corruption for user {user_id}. Resetting corrupt fields. Error: {e}")
        # This is a fallback to prevent crashes.
        player_data["Inventory"] = player_data.get("Inventory", {}) if isinstance(player_data.get("Inventory"), dict) else {}
        player_data["Assets"] = player_data.get("Assets", {}) if isinstance(player_data.get("Assets"), dict) else {}
        player_data["ChildrenIDs"] = player_data.get("ChildrenIDs", []) if isinstance(player_data.get("ChildrenIDs"), list) else []
        player_data["Health"] = int(player_data.get("Health", STARTING_HEALTH))
        return player_data

async def update_player_data(player_data: dict) -> bool:
    """Updates a player's account data in the sheet."""
    if not game_sheet:
        logger.error("game_sheet not initialized. Cannot update data.")
        return False
        
    try:
        # Find row (this is the only blocking call we need)
        cell = await asyncio.to_thread(_get_player_row, player_data["UserID"])
        if not cell:
            logger.error(f"Cannot update data: User {player_data['UserID']} not found in sheet.")
            return False

        # --- Type Conversion and JSON Serialization ---
        data_to_save = player_data.copy()
        data_to_save["ChildrenIDs"] = json.dumps(data_to_save["ChildrenIDs"])
        data_to_save["Inventory"] = json.dumps(data_to_save["Inventory"])
        data_to_save["Assets"] = json.dumps(data_to_save["Assets"])

        # Build the final list of values in the correct order
        final_values = [str(data_to_save.get(h, "")) for h in PLAYER_HEADERS]
        
        # Update the row in a thread
        await asyncio.to_thread(
            game_sheet.update,
            f'A{cell.row}:{gspread.utils.rowcol_to_a1(cell.row, len(PLAYER_HEADERS))}',
            [final_values]
        )
        return True
        
    except Exception as e:
        logger.error(f"Error in update_player_data for {player_data['UserID']}: {e}", exc_info=True)
        return False

# --- Main Game Command Handlers ---

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
            InlineKeyboardButton("🏪 Shop", callback_data="game:menu:shop")
        ],
        [
            InlineKeyboardButton("👨‍👩‍👧‍👦 Family", callback_data="game:menu:family"),
            InlineKeyboardButton("📋 My Assets", callback_data="game:menu:assets")
        ],
        [InlineKeyboardButton("🏆 Global Leaderboard", callback_data="game:menu:leaderboard")]
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

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the top 10 richest users (Money + Bank)."""
    msg_text = "🏆 **Global Rich List** 🏆\n\nFetching data..."
    
    # Send or edit message
    if update.callback_query:
        query = update.callback_query
        await query.edit_message_text(text=msg_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(text=msg_text, parse_mode='Markdown')

    try:
        # Fetch all data in a thread
        all_data = await asyncio.to_thread(game_sheet.get_all_values)
        if len(all_data) < 2:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=update.effective_message.message_id, text="No one is on the leaderboard yet!")
            return
            
        header = all_data[0]
        rows = all_data[1:]
        
        # Find indices
        name_idx = header.index("UserName")
        money_idx = header.index("Money")
        bank_idx = header.index("Bank")
        
        leaderboard = []
        for row in rows:
            try:
                name = row[name_idx]
                total_money = int(row[money_idx]) + int(row[bank_idx])
                leaderboard.append((name, total_money))
            except (ValueError, IndexError):
                continue # Skip bad rows
                
        leaderboard.sort(key=lambda x: x[1], reverse=True)
        
        response_text = "🏆 **Global Rich List** 🏆\n_(Based on Money + Bank)_\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (name, total) in enumerate(leaderboard[:10]):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            response_text += f"{prefix} {name} - `${total:,}`\n"
            
        # Add back button if it was a callback
        keyboard = None
        if update.callback_query:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]])
            
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, 
            message_id=update.effective_message.message_id, 
            text=response_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Error in /leaderboard: {e}", exc_info=True)
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=update.effective_message.message_id, text="Error fetching leaderboard.")

# --- Family Command Handlers ---

async def handle_marry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proposes marriage to a replied-to user."""
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

    # Get data for both
    proposer_data = await get_player_data(proposer.id, proposer.full_name)
    target_data = await get_player_data(target.id, target.full_name)

    if not proposer_data or not target_data:
        await update.message.reply_text("Error accessing accounts. Please try again.")
        return

    if proposer_data["MarriedToID"] != 0:
        await update.message.reply_text(f"You are already married! Use `/divorce` first.")
        return
    if target_data["MarriedToID"] != 0:
        await update.message.reply_text(f"{target.full_name} is already married.")
        return
        
    # Store proposal
    proposals["marry"][target.id] = proposer.id
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"game:marry:accept:{proposer.id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"game:marry:decline:{proposer.id}")
        ]
    ]
    await update.message.reply_text(
        f"Hey {_mention(target.id, target.full_name)}! 💍\n\n"
        f"{_mention(proposer.id, proposer.full_name)} is proposing to you! Do you accept?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_adopt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proposes to adopt a replied-to user."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the user you want to adopt with `/adopt`.")
        return

    proposer = update.effective_user
    target = update.message.reply_to_message.from_user

    if proposer.id == target.id:
        await update.message.reply_text("You can't adopt yourself.")
        return
    if target.is_bot:
        await update.message.reply_text("You can't adopt a bot.")
        return

    proposer_data = await get_player_data(proposer.id, proposer.full_name)
    if not proposer_data:
        await update.message.reply_text("Error accessing your account.")
        return
        
    if proposer_data["MarriedToID"] == 0:
        await update.message.reply_text("You must be married to adopt a child.")
        return

    # Check if target is already someone's child (complex, requires checking all other players)
    # For simplicity, we'll skip this check. A user can be adopted by multiple families.

    # Store proposal
    proposals["adopt"][target.id] = proposer.id
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"game:adopt:accept:{proposer.id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"game:adopt:decline:{proposer.id}")
        ]
    ]
    await update.message.reply_text(
        f"Hey {_mention(target.id, target.full_name)}! 👶\n\n"
        f"{_mention(proposer.id, proposer.full_name)} wants to adopt you into their family! Do you accept?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_divorce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Divorces the user's current spouse."""
    user = update.effective_user
    player_data = await get_player_data(user.id, user.full_name)
    
    if not player_data:
        await update.message.reply_text("Error accessing your account.")
        return
        
    if player_data["MarriedToID"] == 0:
        await update.message.reply_text("You are not married.")
        return

    spouse_id = player_data["MarriedToID"]
    
    # Get spouse data to update them too
    spouse_data = await get_player_data(spouse_id, "Spouse") # Name doesn't matter here

    # Update both players
    player_data["MarriedToID"] = 0
    await update_player_data(player_data)
    
    if spouse_data:
        spouse_data["MarriedToID"] = 0
        await update_player_data(spouse_data)
        
    await update.message.reply_text(f"You have successfully divorced {_mention(spouse_id, 'your ex-partner')}. 💔", parse_mode='Markdown')

# --- Main Callback Query Handler ---

async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses for the game."""
    query = update.callback_query
    await query.answer()  # Acknowledge the press
    
    user = query.from_user
    data = query.data
    
    if not data.startswith("game:"):
        # Not a game callback, ignore
        return

    # --- Parse callback data ---
    # format: "game:menu:main"
    # format: "game:action:farm"
    # format: "game:buy:item:bandage"
    # format: "game:marry:accept:12345"
    parts = data.split(':')
    
    try:
        # --- Main Menu Navigation ---
        if data == "game:menu:main":
            # Pass the update object so it can edit the message
            await start_game(update, context)
            return

        if data == "game:menu:actions":
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.edit_message_text("Error loading your data.")
                return
            
            # Build text with cooldowns
            cd_text = "Ready"
            
            _, work_cd = _check_cooldown(player_data["LastWork"], COOLDOWNS["work"])
            _, farm_cd = _check_cooldown(player_data["LastFarm"], COOLDOWNS["farm"])
            _, crime_cd = _check_cooldown(player_data["LastCrime"], COOLDOWNS["crime"])
            _, mine_cd = _check_cooldown(player_data["LastMine"], COOLDOWNS["mine"])
            _, task_cd = _check_cooldown(player_data["LastTask"], COOLDOWNS["task"])
            _, daily_cd = _check_cooldown(player_data["LastDaily"], COOLDOWNS["daily"])
            
            action_text = (
                f"**Actions Menu**\n\n"
                f"What would you like to do?\n\n"
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
                [InlineKeyboardButton("🏡 Real Estate", callback_data="game:shop:category:real_estate")],
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
            
            assets_text += "**Inventory:**\n"
            if not player_data["Inventory"]:
                assets_text += "  • Empty\n"
            for item_id, count in player_data["Inventory"].items():
                item_name = SHOP_CATALOG.get("items", {}).get(item_id, {}).get("name", item_id)
                assets_text += f"  • {item_name} (x{count})\n"
                
            assets_text += "\n**Weapon:**\n"
            weapon_name = SHOP_CATALOG.get("weapons", {}).get(player_data["Weapon"], {}).get("name", "None")
            assets_text += f"  • {weapon_name}\n"

            assets_text += "\n**Pet:**\n"
            pet_name = SHOP_CATALOG.get("pets", {}).get(player_data["Pet"], {}).get("name", "None")
            assets_text += f"  • {pet_name}\n"

            assets_text += "\n**Properties & Vehicles:**\n"
            if not player_data["Assets"]:
                assets_text += "  • Empty\n"
            for asset_type, asset_id in player_data["Assets"].items():
                asset_name = SHOP_CATALOG.get(asset_type, {}).get(asset_id, {}).get("name", asset_id)
                assets_text += f"  • {asset_name}\n"

            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="game:menu:main")]]
            await query.edit_message_text(assets_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return
            
        # --- Action Handlers ---
        if parts[1] == "action":
            action_name = parts[2]
            player_data = await get_player_data(user.id, user.full_name)
            if not player_data:
                await query.answer("Error loading your data.", show_alert=True)
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
            
            if action_name in EARNINGS:
                min_earn, max_earn = EARNINGS[action_name]
                amount = random.randint(min_earn, max_earn)
                player_data["Money"] += amount
                reply_text = f"You {action_name}ed and earned `${amount:,}`!"
            
            elif action_name == "crime":
                if random.randint(1, 100) <= CRIME_RATES["chance"]:
                    min_earn, max_earn = CRIME_RATES["success"]
                    amount = random.randint(min_earn, max_earn)
                    player_data["Money"] += amount
                    reply_text = f"Crime successful! You got `${amount:,}`."
                else:
                    min_loss, max_loss = CRIME_RATES["fail"]
                    amount = random.randint(min_loss, max_loss)
                    player_data["Money"] -= amount
                    reply_text = f"Crime failed! You were fined `${amount:,}`."
            
            # --- Handle Rob / Kill / Heal ---
            # These are complex and need a target.
            # We'll make them commands for now, not inline buttons.
            # But we can implement 'heal'
            elif action_name == "heal":
                if player_data["Health"] >= STARTING_HEALTH:
                    await query.answer("You are already at full health.", show_alert=True)
                    return # Don't trigger cooldown

                if "bandage" in player_data["Inventory"] and player_data["Inventory"]["bandage"] > 0:
                    player_data["Inventory"]["bandage"] -= 1
                    heal_amount = SHOP_CATALOG["items"]["bandage"]["value"]
                    player_data["Health"] = min(STARTING_HEALTH, player_data["Health"] + heal_amount)
                    reply_text = f"You used a Bandage 🩹 and healed {heal_amount} HP."
                elif "medkit" in player_data["Inventory"] and player_data["Inventory"]["medkit"] > 0:
                    player_data["Inventory"]["medkit"] -= 1
                    heal_amount = SHOP_CATALOG["items"]["medkit"]["value"]
                    player_data["Health"] = min(STARTING_HEALTH, player_data["Health"] + heal_amount)
                    reply_text = f"You used a Medkit ✚ and healed {heal_amount} HP."
                else:
                    await query.answer("You have no healing items! Buy them from the shop.", show_alert=True)
                    return # Don't trigger cooldown
            
            else:
                reply_text = "This action is not implemented yet."

            # Save data and notify user
            await update_player_data(player_data)
            await query.answer(reply_text, show_alert=True)
            
            # Refresh the actions menu to show new cooldown
            await handle_game_callback(update, context) # Re-call self to refresh
            return

        # --- Shop Navigation ---
        if parts[1] == "shop" and parts[2] == "category":
            category = parts[3]
            if category not in SHOP_CATALOG:
                await query.edit_message_text("Invalid shop category.")
                return

            shop_text = f"🏪 **Shop - {category.title()}**\n\n"
            keyboard = []
            
            for item_id, item_data in SHOP_CATALOG[category].items():
                shop_text += f"• **{item_data['name']}**\n"
                shop_text += f"  *Price*: `${item_data['price']:,}`\n"
                shop_text += f"  *Info*: {item_data['description']}\n\n"
                
                # Add a buy button for this item
                keyboard.append([
                    InlineKeyboardButton(f"Buy {item_data['name']}", callback_data=f"game:buy:{category}:{item_id}")
                ])
                
            keyboard.append([InlineKeyboardButton("⬅️ Back to Shop", callback_data="game:menu:shop")])
            await query.edit_message_text(shop_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        # --- Buy Handlers ---
        if parts[1] == "buy":
            category, item_id = parts[2], parts[3]
            
            if category not in SHOP_CATALOG or item_id not in SHOP_CATALOG[category]:
                await query.answer("This item does not exist.", show_alert=True)
                return

            item_data = SHOP_CATALOG[category][item_id]
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
                if player_data["Weapon"] == item_id:
                    await query.answer(f"You already have this weapon equipped.", show_alert=True)
                    return # Refund money
                player_data["Weapon"] = item_id
            
            elif category == "pets":
                if player_data["Pet"] == item_id:
                    await query.answer(f"You already have this pet.", show_alert=True)
                    return
                player_data["Pet"] = item_id

            elif category in ["vehicles", "real_estate"]:
                if player_data["Assets"].get(category) == item_id:
                    await query.answer(f"You already own this.", show_alert=True)
                    return
                player_data["Assets"][category] = item_id

            # Save and notify
            await update_player_data(player_data)
            await query.answer(reply_text, show_alert=True)
            return

        # --- Family Proposal Handlers ---
        if parts[1] == "marry":
            action, proposer_id_str = parts[2], parts[3]
            proposer_id = int(proposer_id_str)
            target = user # The user clicking the button
            
            # Check if proposal is valid
            if proposals["marry"].get(target.id) != proposer_id:
                await query.edit_message_text("This proposal has expired or is invalid.")
                return

            del proposals["marry"][target.id] # Clear proposal
            
            if action == "decline":
                await query.edit_message_text(f"{_mention(target.id, target.full_name)} has declined the marriage proposal from {_mention(proposer_id, 'user')}.", parse_mode='Markdown')
                return

            if action == "accept":
                # Get data for both
                proposer_data = await get_player_data(proposer_id, "Proposer")
                target_data = await get_player_data(target.id, target.full_name)
                
                # Double-check they are still single
                if proposer_data["MarriedToID"] != 0 or target_data["MarriedToID"] != 0:
                    await query.edit_message_text("One of you is already married. Proposal cancelled.")
                    return
                    
                # Success!
                proposer_data["MarriedToID"] = target.id
                target_data["MarriedToID"] = proposer_id
                
                await update_player_data(proposer_data)
                await update_player_data(target_data)
                
                await query.edit_message_text(f"🎉 **Congratulations!** 🎉\n\n{_mention(proposer_id, proposer_data['UserName'])} and {_mention(target.id, target_data['UserName'])} are now married!", parse_mode='Markdown')
                return

        if parts[1] == "adopt":
            action, proposer_id_str = parts[2], parts[3]
            proposer_id = int(proposer_id_str)
            target = user # The user clicking the button
            
            if proposals["adopt"].get(target.id) != proposer_id:
                await query.edit_message_text("This adoption offer has expired or is invalid.")
                return

            del proposals["adopt"][target.id] # Clear proposal
            
            if action == "decline":
                await query.edit_message_text(f"{_mention(target.id, target.full_name)} has declined the adoption.", parse_mode='Markdown')
                return

            if action == "accept":
                proposer_data = await get_player_data(proposer_id, "Proposer")
                
                if proposer_data["MarriedToID"] == 0:
                    await query.edit_message_text("The adopter is no longer married. Offer cancelled.")
                    return
                    
                # Success!
                if target.id not in proposer_data["ChildrenIDs"]:
                    proposer_data["ChildrenIDs"].append(target.id)
                    await update_player_data(proposer_data)
                
                await query.edit_message_text(f"🎉 **Welcome to the Family!** 🎉\n\n{_mention(target.id, target.full_name)} has been adopted by {_mention(proposer_id, proposer_data['UserName'])}!", parse_mode='Markdown')
                return

    except Exception as e:
        logger.error(f"Error in game callback handler: {e}", exc_info=True)
        try:
            await query.answer("An unexpected error occurred. Please try again.", show_alert=True)
        except:
            pass
