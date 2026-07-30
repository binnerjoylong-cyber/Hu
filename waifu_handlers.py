# waifu_handlers.py
"""
Telegram-facing handlers for the waifu/character collection mini-game.

The actual game logic (Jikan API fetching, Postgres storage, rarity math)
already existed in game_logic.py but was never wired up to any command —
this module is the missing bridge. Requires a `DATABASE_URL` (Postgres)
env var; if it's not set, these commands politely say the feature is
unavailable instead of crashing.
"""
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import game_logic

logger = logging.getLogger(__name__)

# How often (roughly) a random message in an active group triggers a spawn.
# 1 in 130 messages by default — tune to taste.
AUTO_SPAWN_CHANCE = 1 / 130


def _db_ready() -> bool:
    return game_logic.db_pool is not None


async def maybe_auto_spawn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Call this from the main text-message handler for group chats.
    Occasionally spawns a random anime character for the group to /claim.
    Silently does nothing if the waifu DB isn't configured, a spawn is
    already active in this chat, or the dice roll doesn't land.
    """
    if not _db_ready():
        return
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    if chat.id in game_logic.active_spawns:
        return
    if random.random() > AUTO_SPAWN_CHANCE:
        return

    character = await game_logic.spawn_character(chat.id)
    if not character:
        return

    caption = (
        f"✨ **A wild character appeared!** ✨\n\n"
        f"**{character['name']}**\n"
        f"_{character['series']}_\n"
        f"Rarity: {character['rarity']}\n\n"
        f"First to type `/claim` gets them! 💫"
    )
    try:
        await context.bot.send_photo(
            chat_id=chat.id,
            photo=character["image_url"],
            caption=caption,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Could not send spawn photo, falling back to text: {e}")
        await context.bot.send_message(chat_id=chat.id, text=caption, parse_mode="Markdown")


async def force_spawn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sudo-only: force a spawn right now, e.g. to test the feature or liven up a quiet chat."""
    if not _db_ready():
        await update.message.reply_text(
            "💔 The waifu collection game isn't configured — a `DATABASE_URL` (Postgres) "
            "environment variable is needed for `/spawn`, `/claim`, and `/harem` to work."
        )
        return

    chat_id = update.effective_chat.id
    if chat_id in game_logic.active_spawns:
        await update.message.reply_text("There's already an active character here — someone needs to `/claim` them first!")
        return

    character = await game_logic.spawn_character(chat_id)
    if not character:
        await update.message.reply_text("⚠️ Couldn't fetch a character right now (API might be down). Try again shortly.")
        return

    caption = (
        f"✨ **A wild character appeared!** ✨\n\n"
        f"**{character['name']}**\n"
        f"_{character['series']}_\n"
        f"Rarity: {character['rarity']}\n\n"
        f"First to type `/claim` gets them! 💫"
    )
    await update.message.reply_photo(photo=character["image_url"], caption=caption, parse_mode="Markdown")


async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Claims the currently active spawned character in this chat."""
    if not _db_ready():
        await update.message.reply_text(
            "💔 The waifu collection game isn't configured on this bot yet."
        )
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    result_text = await game_logic.claim_character(chat_id, user.id, user.full_name)
    await update.message.reply_text(result_text, parse_mode="Markdown")


async def harem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the user's collected characters, sorted by rarity."""
    if not _db_ready():
        await update.message.reply_text(
            "💔 The waifu collection game isn't configured on this bot yet."
        )
        return

    user = update.effective_user
    harem = await game_logic.view_harem(user.id)

    if not harem:
        await update.message.reply_text(
            "💔 You haven't claimed anyone yet!\n\nCharacters randomly appear in group chats — "
            "keep an eye out and be the first to `/claim` them.",
            parse_mode="Markdown",
        )
        return

    lines = [f"💖 **{user.first_name}'s Harem** ({len(harem)} total)\n"]
    for char in harem[:25]:
        lines.append(f"• **{char['name']}** ({char['rarity']}) — _{char['series']}_")
    if len(harem) > 25:
        lines.append(f"\n...and {len(harem) - 25} more!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
