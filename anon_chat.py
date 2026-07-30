# anon_chat.py
# --- Anonymous 1-on-1 Random Chat feature (ported from TelegramChatBot) ---
# Users can DM the bot with /pair to get randomly matched with another user
# for a fully anonymous chat, /skip to find a new partner, and /unpair to stop.
# Ported to use Motor (async MongoDB) since Laila is fully async (PTB v20+),
# instead of the original project's blocking sqlite3 calls.

import logging
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


class UserStatus:
    COUPLED = "coupled"
    IDLE = "idle"
    IN_SEARCH = "in_search"
    PARTNER_LEFT = "partner_left"


class AnonChat:
    """Self-contained anonymous chat manager, mirrors SummaryManager/TriviaGame style."""

    def __init__(self, application, mongo_client: AsyncIOMotorClient = None):
        self.app = application
        self.enabled = mongo_client is not None
        if self.enabled:
            self.db = mongo_client["laila_anon_chat"]
            self.users = self.db["users"]
        else:
            logger.warning("MONGO_URI not set — /pair anonymous chat feature is disabled.")
            self.db = None
            self.users = None

    # ---------- DB helpers ----------

    async def _get_user(self, user_id: int):
        doc = await self.users.find_one({"_id": user_id})
        if doc is None:
            doc = {"_id": user_id, "status": UserStatus.IDLE, "partner_id": None}
            await self.users.insert_one(doc)
        return doc

    async def _set_status(self, user_id: int, status: str):
        await self.users.update_one({"_id": user_id}, {"$set": {"status": status}}, upsert=True)

    async def _set_partner(self, user_id: int, partner_id):
        await self.users.update_one({"_id": user_id}, {"$set": {"partner_id": partner_id}}, upsert=True)

    async def _find_search_partner(self, current_user_id: int):
        """Find another user currently IN_SEARCH (not the current one)."""
        doc = await self.users.find_one({
            "status": UserStatus.IN_SEARCH,
            "_id": {"$ne": current_user_id}
        })
        return doc["_id"] if doc else None

    async def _couple(self, user_a: int, user_b: int):
        await self.users.update_one({"_id": user_a}, {"$set": {"status": UserStatus.COUPLED, "partner_id": user_b}})
        await self.users.update_one({"_id": user_b}, {"$set": {"status": UserStatus.COUPLED, "partner_id": user_a}})

    async def _uncouple(self, user_id: int, partner_id: int):
        await self.users.update_one({"_id": user_id}, {"$set": {"status": UserStatus.IDLE, "partner_id": None}})
        await self.users.update_one({"_id": partner_id}, {"$set": {"status": UserStatus.IDLE, "partner_id": None}})

    # ---------- Commands ----------

    async def pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.enabled:
            await update.message.reply_text("⚠️ Anonymous chat is currently unavailable.")
            return
        if update.effective_chat.type != "private":
            await update.message.reply_text("🔒 Please DM me directly to use /pair — this feature only works in private chat.")
            return

        user_id = update.effective_user.id
        user = await self._get_user(user_id)

        if user["status"] == UserStatus.COUPLED:
            await update.message.reply_text("💬 You're already in a chat! Use /skip to find someone new, or /unpair to leave.")
            return
        if user["status"] == UserStatus.IN_SEARCH:
            await update.message.reply_text("🔎 Still searching for a partner... hang tight!")
            return

        await self._set_status(user_id, UserStatus.IN_SEARCH)
        await update.message.reply_text("🔎 Searching for a random partner...")

        partner_id = await self._find_search_partner(user_id)
        if partner_id is not None:
            await self._couple(user_id, partner_id)
            await context.bot.send_message(chat_id=user_id, text="✅ You've been paired! Say hi 👋 (Use /unpair to leave)")
            await context.bot.send_message(chat_id=partner_id, text="✅ You've been paired! Say hi 👋 (Use /unpair to leave)")

    async def unpair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.enabled:
            return
        user_id = update.effective_user.id
        user = await self._get_user(user_id)

        if user["status"] != UserStatus.COUPLED or not user.get("partner_id"):
            await self._set_status(user_id, UserStatus.IDLE)
            await update.message.reply_text("🤖 You're not in a chat right now. Use /pair to find a partner.")
            return

        partner_id = user["partner_id"]
        await self._uncouple(user_id, partner_id)
        await update.message.reply_text("🔚 You left the chat.")
        await context.bot.send_message(chat_id=partner_id, text="🔚 Your partner has left the chat. Use /pair to find someone new.")

    async def skip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.enabled:
            await update.message.reply_text("⚠️ Anonymous chat is currently unavailable.")
            return
        user_id = update.effective_user.id
        user = await self._get_user(user_id)

        if user["status"] == UserStatus.COUPLED and user.get("partner_id"):
            partner_id = user["partner_id"]
            await self._uncouple(user_id, partner_id)
            await context.bot.send_message(chat_id=partner_id, text="🔚 Your partner skipped to a new chat. Use /pair to find someone new.")

        await self.pair_command(update, context)

    async def anonstats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin-only stats — wrap this with check_sudo_wrapper() when registering."""
        if not self.enabled:
            await update.message.reply_text("⚠️ Anonymous chat is currently unavailable.")
            return
        total = await self.users.count_documents({})
        paired = await self.users.count_documents({"status": UserStatus.COUPLED})
        searching = await self.users.count_documents({"status": UserStatus.IN_SEARCH})
        await update.message.reply_text(
            f"📊 *Anonymous Chat Stats*\n"
            f"Total users: `{total}`\n"
            f"Currently paired: `{paired}`\n"
            f"Currently searching: `{searching}`",
            parse_mode="Markdown"
        )

    # ---------- Message relay (must run BEFORE the general AI handler) ----------

    async def relay_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Registered in an early handler group (e.g. group=-1) with filter:
        filters.ChatType.PRIVATE & (filters.TEXT | filters.CAPTION | filters.Sticker.ALL
        | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL) & ~filters.COMMAND

        If the user is currently paired, relays the message to their partner
        and stops all further handlers (so the AI / summary logic never sees it).
        If the user is not paired, does nothing and lets the update fall through
        to the normal handlers (AI chat, etc.) in later groups.
        """
        if not self.enabled or not update.message:
            return

        user_id = update.effective_user.id
        user = await self._get_user(user_id)

        if user["status"] != UserStatus.COUPLED or not user.get("partner_id"):
            return  # not paired — let it fall through to normal handlers

        partner_id = user["partner_id"]
        try:
            await update.effective_chat.copy_message(
                chat_id=partner_id,
                message_id=update.message.message_id,
                protect_content=True,
            )
        except Exception as e:
            logger.error(f"anon_chat relay failed ({user_id} -> {partner_id}): {e}")

        # Stop propagation so the AI chat handler / summary logger don't also fire
        raise ApplicationHandlerStop
