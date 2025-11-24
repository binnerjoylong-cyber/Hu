# game.py
import logging
import gspread
import json
import time
import random
import re
import asyncio
import math
from gspread import WorksheetNotFound
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes

# --- Global Game Variables ---
game_sheet = None
logger = logging.getLogger(__name__)

# --- CONFIGURATION & CONSTANTS ---
GAME_SHEET_NAME = "laila_game_v3_ultimate" # Sheet name change ki taki naya data fresh bane
STARTING_MONEY = 500
STARTING_BANK = 0
STARTING_HEALTH = 100
STARTING_LEVEL = 1
STARTING_XP = 0

# --- 🖼️ GIF & MEDIA MANAGER (PLACEHOLDERS) ---
# यहाँ अपनी मरज़ी के जितने चाहे उतने GIF लिंक्स डाल दो। कोड अपने आप रैंडमली उठा लेगा।
GAME_MEDIA = {
    "kill_success": [
        "https://media.giphy.com/media/l3vRkvDA9uZYh2dGg/giphy.gif", # Sniper
        "https://media.giphy.com/media/xT39CZobfRXAATy9oY/giphy.gif", # Hitman
        # Aur link yaha add karo...
    ],
    "kill_fail": [
        "https://media.giphy.com/media/26tP3M3i03hoIQL6M/giphy.gif", # Missed shot
        # Aur link yaha add karo...
    ],
    "rob_success": [
        "https://media.giphy.com/media/l2Je2pKj5hS8r2EZa/giphy.gif", # Money bag
        # Aur link yaha add karo...
    ],
    "rob_fail": [
        "https://media.giphy.com/media/10HK0u8b5Lz9PTl/giphy.gif", # Police arrest
        "https://media.giphy.com/media/rOYB3xBQM0Pjq/giphy.gif", # Caught
        # Aur link yaha add karo...
    ],
    "jail": [
        "https://media.giphy.com/media/P2xf5nPyu5WP6/giphy.gif", # Jail bars
    ],
    "work": [
        "https://media.giphy.com/media/wyb2chhSFxjoxUAlgT/giphy.gif", # Working hard
    ],
    "level_up": [
        "https://media.giphy.com/media/3o7qDEq2bMbcbPRQ2c/giphy.gif", # Celebration
    ],
    "wasted": [
        "https://media.giphy.com/media/l2Je3qSgD6uQuyKha/giphy.gif", # GTA Wasted
    ]
}

# --- COOLDOWNS (Seconds) ---
COOLDOWNS = {
    "work": 20 * 60,
    "farm": 30 * 60,
    "crime": 15 * 60,
    "mine": 45 * 60,
    "rob": 30 * 60,
    "kill": 4 * 60 * 60,
    "heal": 5 * 60,
    "task": 3 * 60 * 60,
    "daily": 23 * 60 * 60
}

# --- GAME MECHANICS ---
EARNINGS = {
    "work": (200, 800),
    "farm": (100, 1000),
    "mine": (500, 2500),
    "task": (1000, 5000),
    "daily": (5000, 10000)
}

# XP REWARDS
XP_REWARDS = {
    "work": 10, "farm": 15, "mine": 30, "crime": 25, "rob": 50, "kill": 100, "daily": 50
}

CRIME_RATES = {"chance": 60, "success": (500, 2000), "fail_fine": (300, 1000), "jail_time": 10 * 60} # 10 min jail
ROB_RATES = {"chance": 45, "success_pct": (0.1, 0.40), "fail_hp_loss": 20, "jail_time": 15 * 60}
KILL_RATES = {"chance": 35, "cost": 10000, "fail_hp_loss": 100, "jail_time": 30 * 60} # Fail = Death (100 dmg)

# --- SHOP CATALOG ---
SHOP_CATALOG = {
    "items": [
        {"id": "bandage", "name": "Bandage 🩹", "price": 200, "description": "Heals 15 HP.", "value": 15},
        {"id": "medkit", "name": "Medkit ✚", "price": 1000, "description": "Heals 60 HP.", "value": 60},
        {"id": "bodyguard", "name": "Bodyguard 🛡️", "price": 50000, "description": "Blocks 1 Rob/Kill attempt."}
    ],
    "weapons": [
        {"id": "knife", "name": "Knife 🔪", "price": 2500, "description": "+10% Crime/Rob Chance.", "value": 10},
        {"id": "glock", "name": "Glock 19 🔫", "price": 15000, "description": "+25% Crime/Rob Chance.", "value": 25}
    ],
    "pets": [
        {"id": "dog", "name": "Guard Dog 🐕", "price": 20000, "description": "-10% Rob Chance against you.", "effect": "defense"},
        {"id": "cat", "name": "Lucky Cat 🐱", "price": 25000, "description": "Gives $500 passive income/hour.", "effect": "income", "value": 500}
    ],
    "vehicles": [
        {"id": "bike", "name": "Bicycle 🚲", "price": 5000, "description": "-2% Work Cooldown.", "value": 2},
        {"id": "car", "name": "Sedan 🚗", "price": 50000, "description": "-10% Work Cooldown.", "value": 10},
        {"id": "supercar", "name": "Lambo 🏎️", "price": 500000, "description": "-25% Work Cooldown.", "value": 25}
    ],
    "real_estate": [
        {"id": "shack", "name": "Shack 🏚️", "price": 10000, "description": "Safe place to sleep.", "income": 0},
        {"id": "apartment", "name": "Apartment 🏢", "price": 200000, "description": "$1000 passive income/hour.", "income": 1000}
    ]
}

# --- DATA MODEL (UPDATED WITH NEW FEATURES) ---
PLAYER_HEADERS = [
    "UserID", "UserName", "Money", "Bank", "Health", "Level", "XP", 
    "MarriedToID", "ChildrenIDs", "Pet", "Inventory", "Assets", "Weapon", 
    "LastWork", "LastFarm", "LastCrime", "LastMine", "LastRob", "LastKill", 
    "LastHeal", "LastTask", "LastDaily", "LastPassive", "JailUntil",
    "Kills", "Deaths"
]

proposals = { "marry": defaultdict(int), "adopt": defaultdict(int) }

# --- INITIALIZATION ---
def init_game_module(spreadsheet: gspread.Spreadsheet):
    global game_sheet
    try:
        game_sheet = spreadsheet.worksheet(GAME_SHEET_NAME)
        logger.info(f"Connected to {GAME_SHEET_NAME}")
    except WorksheetNotFound:
        game_sheet = spreadsheet.add_worksheet(GAME_SHEET_NAME, rows="2000", cols=len(PLAYER_HEADERS))
        game_sheet.append_row(PLAYER_HEADERS)
        logger.info(f"Created {GAME_SHEET_NAME}")
    except Exception as e:
        logger.error(f"Init error: {e}")

# --- HELPERS ---
def _format_time(seconds: int) -> str:
    if seconds <= 0: return "Ready"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

def _check_cooldown(last_time: float, cooldown: int) -> (bool, str):
    rem = cooldown - (time.time() - last_time)
    if rem <= 0: return True, "Ready"
    return False, _format_time(rem)

def _find_item(cat, item_id):
    if cat in SHOP_CATALOG:
        for i in SHOP_CATALOG[cat]:
            if i["id"] == item_id: return i
    return None

def _get_random_gif(category):
    if category in GAME_MEDIA and GAME_MEDIA[category]:
        return random.choice(GAME_MEDIA[category])
    return None # No GIF if empty

# --- CORE DATA FUNCTIONS ---
async def get_player_data(user_id: int, user_name: str) -> dict:
    cell = await asyncio.to_thread(game_sheet.find, str(user_id), in_column=1)
    
    default_data = {
        "UserID": str(user_id), "UserName": user_name, "Money": STARTING_MONEY,
        "Bank": STARTING_BANK, "Health": STARTING_HEALTH, "Level": STARTING_LEVEL, "XP": STARTING_XP,
        "MarriedToID": 0, "ChildrenIDs": "[]", "Pet": "", "Inventory": "{}", "Assets": "{}", "Weapon": "",
        "LastWork": 0.0, "LastFarm": 0.0, "LastCrime": 0.0, "LastMine": 0.0, "LastRob": 0.0, 
        "LastKill": 0.0, "LastHeal": 0.0, "LastTask": 0.0, "LastDaily": 0.0, "LastPassive": 0.0,
        "JailUntil": 0.0, "Kills": 0, "Deaths": 0
    }

    if cell:
        row_values = await asyncio.to_thread(game_sheet.row_values, cell.row)
        data = {h: (row_values[i] if i < len(row_values) else "") for i, h in enumerate(PLAYER_HEADERS)}
    else:
        new_row = [default_data[h] for h in PLAYER_HEADERS]
        await asyncio.to_thread(game_sheet.append_row, new_row)
        data = default_data

    # Type Conversion
    for k in ["Money", "Bank", "Health", "Level", "XP", "Kills", "Deaths", "MarriedToID"]:
        try: data[k] = int(data[k])
        except: data[k] = default_data[k]
    
    for k in [h for h in PLAYER_HEADERS if h.startswith("Last") or h == "JailUntil"]:
        try: data[k] = float(data[k])
        except: data[k] = 0.0

    for k in ["ChildrenIDs", "Inventory", "Assets"]:
        try: data[k] = json.loads(data[k])
        except: data[k] = default_data[k] if isinstance(default_data[k], dict) else []

    if data["UserName"] != user_name and cell:
         data["UserName"] = user_name
         # Update name silently later
    
    return data

async def update_player_data(data: dict) -> bool:
    try:
        cell = await asyncio.to_thread(game_sheet.find, str(data["UserID"]), in_column=1)
        if not cell: return False
        
        save_data = data.copy()
        for k in ["ChildrenIDs", "Inventory", "Assets"]:
            save_data[k] = json.dumps(save_data[k])
            
        final_values = [str(save_data.get(h, "")) for h in PLAYER_HEADERS]
        await asyncio.to_thread(game_sheet.update, f"A{cell.row}", [final_values])
        return True
    except Exception as e:
        logger.error(f"Update failed: {e}")
        return False

# --- LOGIC HANDLERS ---

# 1. Level System
def calculate_xp_level(data):
    # Logic: Level requires XP = Level * 100
    needed = data["Level"] * 100
    if data["XP"] >= needed:
        data["Level"] += 1
        data["XP"] -= needed
        return True, data["Level"]
    return False, 0

# 2. Passive Income Check
def process_passive_income(data):
    now = time.time()
    if now - data["LastPassive"] < 3600: # 1 Hour
        return 0
    
    hours = int((now - data["LastPassive"]) / 3600)
    income = 0
    
    # Pet Income
    if data["Pet"] == "cat":
        income += 500 * hours
        
    # Real Estate Income
    if "real_estate" in data["Assets"]:
        for house in data["Assets"]["real_estate"]:
            item = _find_item("real_estate", house)
            if item and "income" in item:
                income += item["income"] * hours
                
    if income > 0:
        data["Money"] += income
        data["LastPassive"] = now
    
    return income

# 3. Status Check (Jail/Dead)
async def check_player_status(update, data):
    # Check Dead
    if data["Health"] <= 0:
        gif = _get_random_gif("wasted")
        await update.effective_message.reply_animation(
            gif, 
            caption=f"💀 **तुम मर चुके हो!**\n\nतुम्हारा स्वास्थ्य 0 है। तुम कोई काम नहीं कर सकते।\n\n`/heal` लिखकर हॉस्पिटल जाओ और इलाज कराओ (खर्चा लगेगा)।",
            parse_mode='Markdown'
        )
        return False

    # Check Jail
    if time.time() < data["JailUntil"]:
        rem = int(data["JailUntil"] - time.time())
        gif = _get_random_gif("jail")
        await update.effective_message.reply_animation(
            gif,
            caption=f"🔒 **तुम जेल में हो!**\n\nपुलिस ने तुम्हें पकड़ रखा है। तुम {_format_time(rem)} तक कुछ नहीं कर सकते।",
            parse_mode='Markdown'
        )
        return False
        
    return True

# --- NEW COMMANDS ---

async def handle_heal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    if data["Health"] >= 100:
        await update.message.reply_text("तुम पूरी तरह स्वस्थ हो!")
        return
        
    cost = 500 if data["Health"] > 0 else 2000 # More expensive if dead
    
    if data["Money"] < cost:
        await update.message.reply_text(f"हॉस्पिटल का बिल ${cost} है, और तुम्हारे पास पैसे नहीं हैं। जाओ कुछ बेचो!")
        return
        
    data["Money"] -= cost
    data["Health"] = 100
    data["Deaths"] = data["Deaths"] # Stat maintain
    
    await update_player_data(data)
    await update.message.reply_text(f"🏥 **हॉस्पिटल:**\n\nडॉक्टर ने तुम्हें ठीक कर दिया है। बिल: `${cost}`\nस्वास्थ्य: 100/100")

async def handle_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("उपयोग: `/slots <amount>`")
        return
        
    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("सही रकम डालो।")
        return
        
    data = await get_player_data(user.id, user.full_name)
    
    if not await check_player_status(update, data): return
    if bet <= 0 or data["Money"] < bet:
        await update.message.reply_text("पैसे नहीं हैं या गलत रकम है।")
        return
        
    data["Money"] -= bet
    
    # Slot Logic
    fruits = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
    a, b, c = random.choice(fruits), random.choice(fruits), random.choice(fruits)
    
    msg = await update.message.reply_text(f"🎰 **SLOTS** 🎰\n\n🔄 ...")
    await asyncio.sleep(1)
    
    winnings = 0
    result = "हार गए! 😢"
    
    if a == b == c:
        mult = 10 if a == "7️⃣" else 5
        winnings = bet * mult
        result = f"JACKPOT! 🎉 ${winnings}"
    elif a == b or b == c or a == c:
        winnings = int(bet * 1.5)
        result = f"छोटी जीत! 😃 ${winnings}"
        
    data["Money"] += winnings
    await update_player_data(data)
    
    await msg.edit_text(f"🎰 **SLOTS** 🎰\n\n| {a} | {b} | {c} |\n\n**{result}**")


# --- UPDATED ACTIONS & CALLBACKS ---

async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("game:"): return
    
    user = query.from_user
    parts = query.data.split(":")
    data = await get_player_data(user.id, user.full_name)
    
    if not data: 
        await query.edit_message_text("Error loading data.")
        return

    # 1. Main Menu
    if parts[2] == "main":
        await start_game(update, context) # Re-use start logic
        return

    # 2. Passive Income Check on Menu Open
    passive = process_passive_income(data)
    if passive > 0:
        await update_player_data(data)
        await query.message.reply_text(f"💰 **Passive Income:** तुमने अनुपस्थिति में ${passive} कमाए!")

    # 3. Handle Actions
    if parts[1] == "action":
        action = parts[2]
        
        # Check Status
        if data["Health"] <= 0:
            await query.answer("तुम मर चुके हो! /heal करो।", show_alert=True)
            return
        if time.time() < data["JailUntil"]:
            await query.answer("तुम जेल में हो!", show_alert=True)
            return
            
        # Cooldown Check with Vehicle Bonus
        cd_time = COOLDOWNS.get(action, 0)
        # Apply Vehicle Bonus (Only for work)
        if action == "work" and "vehicles" in data["Assets"]:
            bonus = 0
            for v_id in data["Assets"]["vehicles"]:
                item = _find_item("vehicles", v_id)
                if item: bonus = max(bonus, item.get("value", 0))
            # Reduce cooldown by percentage
            cd_time = int(cd_time * (1 - (bonus/100)))

        is_ready, wait_msg = _check_cooldown(data[f"Last{action.capitalize()}"], cd_time)
        if not is_ready:
            await query.answer(f"रुको! {wait_msg} बाकी है।", show_alert=True)
            return
            
        # Execute Action
        data[f"Last{action.capitalize()}"] = time.time()
        
        # --- MINIGAMES & LOGIC ---
        reward = 0
        msg = ""
        gif = None
        
        if action == "work":
            reward = random.randint(*EARNINGS["work"]) * data["Level"] # Level Multiplier
            msg = f"🧑‍💻 तुमने काम किया और ${reward} कमाए!"
            gif = _get_random_gif("work")
            
        elif action == "crime":
            # Crime Logic with Jail
            chance = CRIME_RATES["chance"]
            if data["Weapon"]: chance += 10 # Weapon bonus
            
            if random.randint(1, 100) <= chance:
                reward = random.randint(*CRIME_RATES["success"]) * data["Level"]
                msg = f"🕵️‍♂️ क्राइम सफल! ${reward} मिले।"
            else:
                fine = random.randint(*CRIME_RATES["fail_fine"])
                data["Money"] -= fine
                data["JailUntil"] = time.time() + CRIME_RATES["jail_time"]
                msg = f"🚔 पुलिस ने पकड़ लिया! ${fine} जुर्माना और 10 मिनट की जेल।"
                gif = _get_random_gif("jail")

        # ... (Other actions like farm, mine same pattern) ...
        
        # Add XP
        xp = XP_REWARDS.get(action, 10)
        data["XP"] += xp
        data["Money"] += reward
        
        # Level Up Check
        leveled_up, new_lvl = calculate_xp_level(data)
        if leveled_up:
            msg += f"\n🆙 **LEVEL UP!** अब तुम Level {new_lvl} पर हो!"
            await query.message.reply_animation(_get_random_gif("level_up"))

        await update_player_data(data)
        
        text_response = f"{msg}\n\n(+{xp} XP)"
        if gif and action != "crime": # Crime sends gif inside logic
            await query.edit_message_text(text_response) # Text only update usually better for buttons
            await query.message.reply_animation(gif)
        else:
            await query.edit_message_text(text_response, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="game:menu:actions")]]))
            
    # 4. Use Item Handler
    if parts[1] == "use":
        item_id = parts[3]
        if item_id in data["Inventory"] and data["Inventory"][item_id] > 0:
            item = _find_item("items", item_id)
            used = False
            
            if item_id in ["bandage", "medkit"]:
                if data["Health"] >= 100:
                    await query.answer("Full Health!", show_alert=True)
                    return
                data["Health"] = min(100, data["Health"] + item["value"])
                used = True
                msg = f"🩹 स्वास्थ्य अब {data['Health']}/100 है।"

            if used:
                data["Inventory"][item_id] -= 1
                if data["Inventory"][item_id] == 0: del data["Inventory"][item_id]
                await update_player_data(data)
                await query.answer(msg, show_alert=True)
                # Refresh Inventory UI here (simplified)
                await query.edit_message_text(f"✅ इस्तेमाल किया: {item['name']}\n{msg}")

# --- UPDATED ROB/KILL COMMANDS ---
async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (Copy validations from old code...)
    killer = update.effective_user
    target = update.message.reply_to_message.from_user
    
    k_data = await get_player_data(killer.id, killer.full_name)
    t_data = await get_player_data(target.id, target.full_name)
    
    if not await check_player_status(update, k_data): return

    # Check Bodyguard
    if t_data["Inventory"].get("bodyguard", 0) > 0:
        t_data["Inventory"]["bodyguard"] -= 1
        await update_player_data(t_data)
        await update.message.reply_text("🛡️ **BLOCK!** टारगेट के बॉडीगार्ड ने हमला रोक दिया!")
        return

    # Calculate Chance
    chance = KILL_RATES["chance"]
    # Weapon Bonus
    wep = _find_item("weapons", k_data["Weapon"])
    if wep: chance += wep["value"]
    # Pet Defense
    pet = _find_item("pets", t_data["Pet"])
    if pet and pet.get("effect") == "defense": chance -= 10
    
    if k_data["Money"] < KILL_RATES["cost"]:
        await update.message.reply_text("पैसे नहीं हैं सुपारी देने के लिए!")
        return

    k_data["Money"] -= KILL_RATES["cost"]
    
    if random.randint(1, 100) <= chance:
        t_data["Health"] = 0
        t_data["Deaths"] += 1
        k_data["Kills"] += 1
        k_data["XP"] += XP_REWARDS["kill"]
        
        await update_player_data(t_data)
        await update_player_data(k_data)
        
        gif = _get_random_gif("kill_success")
        await update.message.reply_animation(gif, caption=f"💀 **KILL CONFIRMED**\n{killer.full_name} ने {target.full_name} को उड़ा दिया!")
    else:
        k_data["Health"] -= KILL_RATES["fail_hp_loss"] # Instant Death or heavy dmg
        k_data["JailUntil"] = time.time() + KILL_RATES["jail_time"]
        
        await update_player_data(k_data)
        gif = _get_random_gif("kill_fail")
        await update.message.reply_animation(gif, caption=f"❌ **FAILED!**\nहमला फेल हुआ! पुलिस ने तुम्हें पकड़ लिया और पब्लिक ने मारा।")

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main Menu Updated with Level"""
    user = update.effective_user
    data = await get_player_data(user.id, user.full_name)
    
    # Process Passive Income silently
    passive = process_passive_income(data)
    if passive > 0: await update_player_data(data)

    txt = (
        f"🌆 **CITY LIFE V3** 🌆\n"
        f"👤 {user.full_name} | ⭐ Lvl {data['Level']} ({data['XP']} XP)\n"
        f"❤️ HP: {data['Health']}/100\n"
        f"💵 Cash: ${data['Money']:,} | 🏦 Bank: ${data['Bank']:,}\n"
    )
    if passive > 0: txt += f"\n💰 **Offline Earnings:** ${passive:,}\n"
    
    kb = [
        [InlineKeyboardButton("🔫 Actions", callback_data="game:menu:actions"), InlineKeyboardButton("🎒 Inventory", callback_data="game:menu:assets")],
        [InlineKeyboardButton("🏪 Shop", callback_data="game:menu:shop"), InlineKeyboardButton("🎰 Gambling", callback_data="game:menu:gamble")],
        [InlineKeyboardButton("🏥 Hospital", callback_data="game:action:heal_menu")] # Placeholder link
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ... (Previous Shop/Bank logic remains similar, just ensure variable names match) ...
