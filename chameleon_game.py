"""
chameleon_game.py
A group-chat version of "The Chameleon" board game for Laila.

Rules recap:
- Everyone gets the same secret word, except the Chameleon (who only sees the topic).
- Players take turns saying ONE word/phrase that hints at the secret word.
- After everyone has gone, the group votes on who they think the Chameleon is.
- If the group catches the Chameleon, the Chameleon gets one guess at the secret word.
  Guess right -> Chameleon still wins. Guess wrong -> the group wins.
- If the group accuses the wrong person -> the Chameleon wins.
"""

import os
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

MIN_PLAYERS = 3
MAX_PLAYERS = 10

# --- Load the word deck (topic -> list of words) ---
_DECK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chameleon_deck.json")
try:
    with open(_DECK_PATH, "r", encoding="utf-8") as f:
        WORD_DECK = json.load(f)
except FileNotFoundError:
    WORD_DECK = {"Animals": ["Dog", "Cat", "Lion", "Elephant", "Tiger"]}

# --- Global state: one game per chat_id ---
# games[chat_id] = {
#   "phase": "lobby" | "describing" | "voting" | "reveal",
#   "host_id": int,
#   "players": {user_id: name},
#   "order": [user_id, ...],
#   "turn_index": int,
#   "topic": str,
#   "secret_word": str,
#   "chameleon_id": int,
#   "clues": {user_id: clue},
#   "votes": {voter_id: target_id},
#   "lobby_msg_id": int,
# }
games = {}


def _players_text(game):
    if not game["players"]:
        return "No one has joined yet."
    return "\n".join(f"• {name}" for name in game["players"].values())


def _lobby_markup(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Join", callback_data=f"cham_join_{chat_id}")],
        [InlineKeyboardButton("▶️ Start Game", callback_data=f"cham_start_{chat_id}")],
        [InlineKeyboardButton("🛑 Cancel", callback_data=f"cham_cancel_{chat_id}")],
    ])


async def chameleon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/chameleon - open a new lobby in this group."""
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("🦎 Chameleon can only be played in a group chat!")
        return

    if chat.id in games:
        await update.message.reply_text("A Chameleon game is already active here! Use /endchameleon to stop it.")
        return

    games[chat.id] = {
        "phase": "lobby",
        "host_id": user.id,
        "players": {user.id: user.first_name},
        "order": [],
        "turn_index": 0,
        "topic": None,
        "secret_word": None,
        "chameleon_id": None,
        "clues": {},
        "votes": {},
        "lobby_msg_id": None,
    }
    game = games[chat.id]

    text = (
        "🦎 <b>The Chameleon</b> lobby is open!\n\n"
        f"Host: {user.first_name}\n\n"
        f"{_players_text(game)}\n\n"
        f"Need {MIN_PLAYERS}-{MAX_PLAYERS} players. Tap Join, then the host taps Start."
    )
    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=_lobby_markup(chat.id))
    game["lobby_msg_id"] = msg.message_id


async def end_chameleon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/endchameleon - abort the current game (host or admin only)."""
    chat = update.effective_chat
    user = update.effective_user
    game = games.get(chat.id)
    if not game:
        await update.message.reply_text("There's no active Chameleon game here.")
        return

    is_host = user.id == game["host_id"]
    is_admin = False
    try:
        member = await chat.get_member(user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        pass

    if not (is_host or is_admin):
        await update.message.reply_text("Only the host or a group admin can end the game.")
        return

    del games[chat.id]
    await update.message.reply_text("🛑 The Chameleon game was ended.")


async def _advance_turn(chat_id, context):
    game = games[chat_id]
    if game["turn_index"] >= len(game["order"]):
        await _start_voting(chat_id, context)
        return

    uid = game["order"][game["turn_index"]]
    name = game["players"][uid]
    await context.bot.send_message(
        chat_id,
        f"🗣️ It's <b>{name}</b>'s turn! Send one word/short phrase describing the topic in the group.",
        parse_mode="HTML",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Passive text handler: only acts if this chat is mid-game and it's the sender's turn.
    Register this with its own handler group so it never blocks other handlers."""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    game = games.get(chat.id)
    if not game or game["phase"] != "describing":
        return
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if game["turn_index"] >= len(game["order"]):
        return
    expected_uid = game["order"][game["turn_index"]]
    if user.id != expected_uid:
        return

    clue = update.message.text.strip()
    if not clue or clue.startswith("/"):
        return

    game["clues"][user.id] = clue
    game["turn_index"] += 1
    try:
        await update.message.set_reaction("👍")
    except Exception:
        pass
    await _advance_turn(chat.id, context)


async def _start_voting(chat_id, context):
    game = games[chat_id]
    game["phase"] = "voting"
    game["votes"] = {}

    clue_lines = "\n".join(
        f"• {game['players'][uid]}: {clue}" for uid, clue in game["clues"].items()
    )
    buttons = [
        [InlineKeyboardButton(f"🫵 {name}", callback_data=f"cham_vote_{chat_id}_{uid}")]
        for uid, name in game["players"].items()
    ]
    await context.bot.send_message(
        chat_id,
        f"🗳️ Everyone has spoken!\n\n{clue_lines}\n\nNow vote for who you think the Chameleon is:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def chameleon_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all cham_* inline button presses."""
    query = update.callback_query
    data = query.data
    user = query.from_user
    parts = data.split("_")
    action = parts[1]
    chat_id = int(parts[2])

    game = games.get(chat_id)
    if not game:
        await query.answer("This game isn't active anymore.", show_alert=True)
        return

    # --- Lobby actions ---
    if action == "join":
        if game["phase"] != "lobby":
            await query.answer("The game already started.", show_alert=True)
            return
        if user.id in game["players"]:
            await query.answer("You already joined!")
            return
        if len(game["players"]) >= MAX_PLAYERS:
            await query.answer("Lobby is full!", show_alert=True)
            return
        game["players"][user.id] = user.first_name
        await query.answer("Joined the game! 🦎")
        text = (
            "🦎 <b>The Chameleon</b> lobby is open!\n\n"
            f"Host: {game['players'][game['host_id']]}\n\n"
            f"{_players_text(game)}\n\n"
            f"Need {MIN_PLAYERS}-{MAX_PLAYERS} players. Tap Join, then the host taps Start."
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=_lobby_markup(chat_id))
        return

    if action == "cancel":
        if user.id != game["host_id"]:
            await query.answer("Only the host can cancel.", show_alert=True)
            return
        del games[chat_id]
        await query.answer("Game cancelled.")
        await query.edit_message_text("🛑 The Chameleon lobby was cancelled.")
        return

    if action == "start":
        if user.id != game["host_id"]:
            await query.answer("Only the host can start the game.", show_alert=True)
            return
        if len(game["players"]) < MIN_PLAYERS:
            await query.answer(f"Need at least {MIN_PLAYERS} players!", show_alert=True)
            return

        topic = random.choice(list(WORD_DECK.keys()))
        word = random.choice(WORD_DECK[topic])
        chameleon_id = random.choice(list(game["players"].keys()))
        order = list(game["players"].keys())
        random.shuffle(order)

        game.update({
            "phase": "describing",
            "topic": topic,
            "secret_word": word,
            "chameleon_id": chameleon_id,
            "order": order,
            "turn_index": 0,
            "clues": {},
        })

        await query.answer("Game started!")
        await query.edit_message_text(
            f"🎬 Game starting! Topic: <b>{topic}</b>\n\nTap the button below to privately see your role.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔍 Show me my word", callback_data=f"cham_word_{chat_id}_0")]]
            ),
        )
        await _advance_turn(chat_id, context)
        return

    if action == "word":
        if user.id not in game["players"]:
            await query.answer("You're not in this game.", show_alert=True)
            return
        if user.id == game["chameleon_id"]:
            await query.answer(
                f"You are the CHAMELEON! 🦎\nTopic: {game['topic']}\nYou don't know the secret word — blend in!",
                show_alert=True,
            )
        else:
            await query.answer(
                f"Topic: {game['topic']}\nSecret word: {game['secret_word']}",
                show_alert=True,
            )
        return

    # --- Voting ---
    if action == "vote":
        target_id = int(parts[3])
        if user.id not in game["players"]:
            await query.answer("You're not in this game.", show_alert=True)
            return
        if game["phase"] != "voting":
            await query.answer("Voting isn't open right now.", show_alert=True)
            return
        game["votes"][user.id] = target_id
        await query.answer(f"Vote registered for {game['players'][target_id]}!")

        if len(game["votes"]) >= len(game["players"]):
            await _reveal(chat_id, context)
        return

    # --- Chameleon's final guess ---
    if action == "guess":
        guess_word = "_".join(parts[3:])
        if user.id != game["chameleon_id"]:
            await query.answer("Only the Chameleon guesses!", show_alert=True)
            return
        await query.answer("Guess locked in!")
        if guess_word.lower() == game["secret_word"].lower():
            result = f"😈 The Chameleon guessed <b>{guess_word}</b> — correct! The Chameleon wins!"
        else:
            result = (
                f"🎉 The Chameleon guessed <b>{guess_word}</b> — wrong! "
                f"The secret word was <b>{game['secret_word']}</b>. The group wins!"
            )
        await query.edit_message_text(result, parse_mode="HTML")
        del games[chat_id]
        return


async def _reveal(chat_id, context):
    game = games[chat_id]
    game["phase"] = "reveal"

    tally = {}
    for target in game["votes"].values():
        tally[target] = tally.get(target, 0) + 1
    accused_id = max(tally, key=tally.get)
    accused_name = game["players"][accused_id]
    vote_lines = "\n".join(
        f"• {game['players'][voter]} → {game['players'][target]}"
        for voter, target in game["votes"].items()
    )

    if accused_id == game["chameleon_id"]:
        words = WORD_DECK[game["topic"]]
        buttons = [
            [InlineKeyboardButton(w, callback_data=f"cham_guess_{chat_id}_{w}")]
            for w in words
        ]
        await context.bot.send_message(
            chat_id,
            f"{vote_lines}\n\n🦎 The group accused <b>{accused_name}</b> — and they WERE the Chameleon!\n\n"
            f"{accused_name}, pick the secret word to steal the win:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        chameleon_name = game["players"][game["chameleon_id"]]
        await context.bot.send_message(
            chat_id,
            f"{vote_lines}\n\n❌ The group accused <b>{accused_name}</b>, but the real Chameleon was "
            f"<b>{chameleon_name}</b>!\nSecret word was <b>{game['secret_word']}</b>. The Chameleon wins! 🦎",
            parse_mode="HTML",
        )
        del games[chat_id]
