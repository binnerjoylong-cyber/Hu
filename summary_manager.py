import logging
import datetime
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from groq import Groq
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MONGO_URI = "YOUR_MONGODB_URI_HERE"
GROQ_API_KEY = "YOUR_GROQ_API_KEY_HERE"

class SummaryManager:
    def __init__(self, application):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client["laila_summaries"]
        self.app = application
        self.ai_client = Groq(api_key=GROQ_API_KEY)

    async def record_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Saves every text message to MongoDB for the 7:50 PM scan"""
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
        """7:50 PM: Scans DB, generates AI story, and stores in Queue"""
        logger.info("--- 7:50 PM: INITIALIZING SUMMARY PREP ---")
        collections = await self.db.list_collection_names()
        
        for coll_name in collections:
            if not coll_name.startswith("chat_"): continue
            
            chat_id = int(coll_name.replace("chat_", ""))
            # Get last 3000 messages
            messages = await self.db[coll_name].find().sort("time", 1).to_list(length=3000)
            
            if not messages or len(messages) < 5:
                logger.info(f"Skipping {chat_id}: Insufficient activity.")
                continue

            formatted_logs = "\n".join([f"{m['user']}: {m['text']}" for m in messages])
            
            # AI Prompt with Dynamic Length Logic
            prompt = (
                f"Narrate today's group chat highlights as a witty, dramatic, and elite storyteller. "
                f"Title: 'THE DAILY CHRONICLES'. "
                f"LENGTH RULE: If the chat is quiet, write a brief summary (50-100 words). "
                f"If the chat is busy, write a detailed story (up to 600 words). "
                f"Style: Elite English. Mention key moments and end with 'STAR OF THE NIGHT'.\n\n"
                f"LOGS:\n{formatted_logs}"
            )

            try:
                completion = self.ai_client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                    temperature=0.7,
                )
                summary_text = completion.choices[0].message.content
                
                # Store in Pending Queue
                await self.db["pending_summaries"].update_one(
                    {"chat_id": chat_id},
                    {"$set": {"summary": summary_text, "status": "ready"}},
                    upsert=True
                )
                # Cleanup raw logs
                await self.db[coll_name].delete_many({})
                logger.info(f"✅ Summary ready for {chat_id}")
            except Exception as e:
                logger.error(f"AI Prep Error for {chat_id}: {e}")

    async def deliver_summaries(self):
        """8:00 PM: Posts all ready summaries from the Queue"""
        logger.info("--- 8:00 PM: DISPATCHING SUMMARIES ---")
        cursor = self.db["pending_summaries"].find({"status": "ready"})
        pending = await cursor.to_list(length=100)
        
        for item in pending:
            chat_id = item["chat_id"]
            text = item["summary"]
            
            try:
                final_post = (
                    f"🏛 <b>THE DAILY CHRONICLES</b> 🏛\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{text}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚜️ <i>Archives updated and pinned.</i>"
                )
                sent_msg = await self.app.bot.send_message(chat_id, final_post, parse_mode='HTML')
                await self.app.bot.pin_chat_message(chat_id, sent_msg.message_id)
                
                # Remove from Queue
                await self.db["pending_summaries"].delete_one({"chat_id": chat_id})
                logger.info(f"🚀 Summary posted in {chat_id}")
            except Exception as e:
                logger.error(f"Delivery Error for {chat_id}: {e}")

    async def test_summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Immediate test for Admins: /testsummary"""
        chat_id = update.effective_chat.id
        status = await update.message.reply_text("🧐 Analyzing current logs... please wait.")
        
        # Prepare and immediately return (is_test=True to keep logs)
        messages = await self.db[f"chat_{chat_id}"].find().sort("time", 1).to_list(length=1000)
        if not messages:
            await status.edit_text("❌ No logs recorded yet. Send some messages first!")
            return

        formatted_logs = "\n".join([f"{m['user']}: {m['text']}" for m in messages])
        try:
            completion = self.ai_client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "user", "content": f"Summarize this briefly: {formatted_logs}"}],
                max_tokens=500
            )
            await update.message.reply_text(f"🧪 <b>TEST SUMMARY:</b>\n\n{completion.choices[0].message.content}", parse_mode='HTML')
            await status.delete()
        except Exception as e:
            await status.edit_text(f"Error: {e}")

    async def run_scheduler(self):
        """The Main Clock"""
        while True:
            now = datetime.datetime.now()
            
            # --- PHASE 1: PREP AT 7:50 PM ---
            prep_time = now.replace(hour=19, minute=50, second=0, microsecond=0)
            if now < prep_time:
                wait_prep = (prep_time - now).total_seconds()
                logger.info(f"Next Prep scheduled in {wait_prep/3600:.2f} hours.")
                await asyncio.sleep(wait_prep)
                await self.prepare_summaries()

            # --- PHASE 2: POST AT 8:00 PM ---
            now = datetime.datetime.now()
            post_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now < post_time:
                wait_post = (post_time - now).total_seconds()
                logger.info(f"Next Posting scheduled in {wait_post/60:.2f} minutes.")
                await asyncio.sleep(wait_post)
                await self.deliver_summaries()

            # Wait for next day
            await asyncio.sleep(60)
