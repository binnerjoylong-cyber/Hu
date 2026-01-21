import logging
import datetime
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from groq import Groq
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MONGO_URI = "mongodb+srv://Lailamongo:Adhyan134@laila.o7zkcis.mongodb.net/?appName=Laila"
GROQ_API_KEY = "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"
class SummaryManager:
    def __init__(self, application, known_users_list): # 2 arguments
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client["laila_summaries"]
        self.app = application
        self.known_users = known_users_list
        self.ai_client = Groq(api_key=GROQ_API_KEY)

    async def record_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat or update.effective_chat.type == "private":
            return
        msg = update.effective_message
        if not msg or not msg.text or len(msg.text) < 2 or msg.text.startswith('/'):
            return

        chat_id = update.effective_chat.id
        try:
            await self.db[f"chat_{chat_id}"].insert_one({
                "user": msg.from_user.first_name,
                "text": msg.text,
                "time": datetime.datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"DB Record Error: {e}")

    async def prepare_summaries(self):
        logger.info("--- 7:50 PM: PREPARING SUMMARIES ---")
        collections = await self.db.list_collection_names()
        for coll_name in collections:
            if not coll_name.startswith("chat_"): continue
            
            chat_id = int(coll_name.replace("chat_", ""))
            messages = await self.db[coll_name].find().sort("time", 1).to_list(length=3000)
            
            if not messages or len(messages) < 5: continue

            formatted_logs = "\n".join([f"{m['user']}: {m['text']}" for m in messages])
            
            prompt = (
                f"Narrate today's highlights as a witty storyteller. Title: 'THE DAILY CHRONICLES'. "
                f"Rule: Short chat = 50-100 words, Long chat = 500-600 words. "
                f"Tone: Elite British English. Mention key users and 'STAR OF THE NIGHT'.\n\nLOGS:\n{formatted_logs}"
            )

            try:
                completion = self.ai_client.chat.completions.create(
                    model="llama-3.3-70b-specdec",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                    temperature=0.7,
                )
                await self.db["pending_summaries"].update_one(
                    {"chat_id": chat_id},
                    {"$set": {"summary": completion.choices[0].message.content, "status": "ready"}},
                    upsert=True
                )
                await self.db[coll_name].delete_many({})
                logger.info(f"✅ Summary ready for {chat_id}")
            except Exception as e:
                logger.error(f"AI Prep Error: {e}")

    async def deliver_summaries(self):
        logger.info("--- 8:00 PM: DELIVERING SUMMARIES ---")
        cursor = self.db["pending_summaries"].find({"status": "ready"})
        pending = await cursor.to_list(length=100)
        
        for item in pending:
            chat_id = item["chat_id"]
            try:
                final_post = (
                    f"🏛 <b>THE DAILY CHRONICLES</b> 🏛\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{item['summary']}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚜️ <i>Archives pinned.</i>"
                )
                sent_msg = await self.app.bot.send_message(chat_id, final_post, parse_mode='HTML')
                await self.app.bot.pin_chat_message(chat_id, sent_msg.message_id)
                await self.db["pending_summaries"].delete_one({"chat_id": chat_id})
            except Exception as e:
                logger.error(f"Post Error: {e}")

    async def test_summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        status = await update.message.reply_text("🧐 Analyzing logs...")
        messages = await self.db[f"chat_{chat_id}"].find().sort("time", 1).to_list(length=500)
        
        if not messages:
            await status.edit_text("❌ No logs found! Send messages first.")
            return

        formatted_logs = "\n".join([f"{m['user']}: {m['text']}" for m in messages])
        try:
            completion = self.ai_client.chat.completions.create(
                model="llama-3.3-70b-specdec",
                messages=[{"role": "user", "content": f"Briefly summarize this in elite story style: {formatted_logs}"}],
                max_tokens=500
            )
            await update.message.reply_text(f"🧪 <b>TEST SUMMARY:</b>\n\n{completion.choices[0].message.content}", parse_mode='HTML')
            await status.delete()
        except Exception as e:
            await status.edit_text(f"Error: {e}")

    async def run_scheduler(self):
        while True:
            now = datetime.datetime.now()
            # 7:50 PM Prep
            prep_time = now.replace(hour=19, minute=50, second=0, microsecond=0)
            if now < prep_time:
                await asyncio.sleep((prep_time - now).total_seconds())
                await self.prepare_summaries()
            
            # 8:00 PM Post
            now = datetime.datetime.now()
            post_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now < post_time:
                await asyncio.sleep((post_time - now).total_seconds())
                await self.deliver_summaries()
            
            await asyncio.sleep(60)
