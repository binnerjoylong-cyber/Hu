import logging
import datetime
import asyncio
import pytz  # pip install pytz
from collections import Counter # Message count karne ke liye
from motor.motor_asyncio import AsyncIOMotorClient
from groq import Groq
from telegram import Update
from telegram.ext import ContextTypes

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MONGO_URI = "mongodb+srv://Lailamongo:Adhyan134@laila.o7zkcis.mongodb.net/?appName=Laila" 
GROQ_API_KEY = "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"

# Timezone Configuration (India Standard Time)
IST = pytz.timezone('Asia/Kolkata')

class SummaryManager:
    def __init__(self, application, known_users_list):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client["laila_summaries"]
        self.app = application
        self.known_users = known_users_list
        self.ai_client = Groq(api_key=GROQ_API_KEY)

    async def record_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Records incoming messages to the database."""
        if not update.effective_chat or update.effective_chat.type == "private":
            return
        
        msg = update.effective_message
        # Filter: Ignore commands, empty messages, or very short messages (spam)
        if not msg or not msg.text or len(msg.text) < 2 or msg.text.startswith('/'):
            return

        chat_id = update.effective_chat.id
        try:
            await self.db[f"chat_{chat_id}"].insert_one({
                "user": msg.from_user.first_name,
                "text": msg.text,
                "time": datetime.datetime.now(datetime.timezone.utc)
            })
        except Exception as e:
            logger.error(f"DB Record Error: {e}")


    async def _generate_summary_text(self, logs, top_user_info):
        """
        Generates a concise, engaging narrative story.
        """
        
        system_prompt = (
            "You are a charismatic Storyteller for a premium Telegram group. "
            "Your goal: Turn today's chat logs into a SHORT, punchy, and engaging 'Daily Story'.\n\n"
            "Style Guidelines:\n"
            "1. **Narrative Flow**: Don't just list facts. Use transitions like 'It all kicked off when...', 'Then things took a turn as...', or 'The vibe shifted when...'.\n"
            "2. **Stick to the Plot**: Only use real events from the logs. Do not invent fake drama.\n"
            "3. **Stay Concise**: Keep it to 2-3 short, high-energy paragraphs. Avoid 'fluff'.\n"
            "4. **Formatting**: Bold user names: <b>Name</b>. Use relevant emojis sparingly.\n"
            "5. **Closing Credits**: End with a dedicated 'Star of the Day' section for the top chatter.\n"
            "6. **Language**: Smooth, modern English."
        )

        user_prompt = (
            f"CHAT LOGS FOR STORYTELLING:\n{logs}\n\n"
            f"ACTIVITY DATA: {top_user_info}\n\n"
            "Write the story now. Keep it short, engaging, and bold the names."
        )

        try:
            completion = self.ai_client.chat.completions.create(
                model="llama-3.1-8b-instant", 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=600, # Kept shorter for better engagement
                temperature=0.7, # Slightly higher for better 'story' flow, but still grounded
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq API Error: {e}")
            return "⚠️ The AI is currently resting. Summary unavailable."


    

    async def prepare_summaries(self):
        """Fetches logs, calculates stats, and generates summaries."""
        logger.info("--- 7:50 PM IST: PREPARING SUMMARIES ---")
        collections = await self.db.list_collection_names()
        
        for coll_name in collections:
            if not coll_name.startswith("chat_"): continue
            
            chat_id = int(coll_name.replace("chat_", ""))
            
            # Fetch messages
            messages = await self.db[coll_name].find().sort("time", 1).to_list(length=3000)
            
            if not messages or len(messages) < 5: 
                continue

            # --- 1. Calculate Chatter of the Day (Python Logic) ---
            # Extract list of users
            all_users = [m.get('user', 'Unknown') for m in messages]
            # Count frequency
            user_counts = Counter(all_users)
            # Get top user
            if user_counts:
                top_name, msg_count = user_counts.most_common(1)[0]
                top_user_info = f"Top Chatter: {top_name} ({msg_count} messages)"
            else:
                top_user_info = "Top Chatter: None"

            # --- 2. Format Logs ---
            formatted_logs = "\n".join([f"{m.get('user', 'Anon')}: {m.get('text', '')}" for m in messages])
            
            # --- 3. Generate Summary with AI ---
            summary_text = await self._generate_summary_text(formatted_logs, top_user_info)

            # Save to 'pending_summaries'
            await self.db["pending_summaries"].update_one(
                {"chat_id": chat_id},
                {"$set": {"summary": summary_text, "status": "ready"}},
                upsert=True
            )
            
            # Clear logs for next day
            await self.db[coll_name].delete_many({})
            logger.info(f"✅ Summary ready for {chat_id} (MVP: {top_name})")

    async def deliver_summaries(self):
        """Delivers the prepared summaries with a cleaner look."""
        logger.info("--- DELIVERING SUMMARIES ---")
        try:
            cursor = self.db["pending_summaries"].find({"status": "ready"})
            pending = await cursor.to_list(length=100)
            
            for item in pending:
                chat_id = item["chat_id"]
                try:
                    # Cleaner, more modern delivery template
                    final_post = (
                        f"✨ <b>THE DAILY CHRONICLE</b> ✨\n"
                        f"━━━━━━━━━━━━━━━━━━\n\n"
                        f"{item['summary']}\n\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"📌 <i>Summarized for the community.</i>"
                    )
                    sent_msg = await self.app.bot.send_message(chat_id, final_post, parse_mode='HTML')
                    
                    try:
                        await self.app.bot.pin_chat_message(chat_id, sent_msg.message_id)
                    except Exception as pin_err:
                        logger.warning(f"Could not pin message: {pin_err}")

                    await self.db["pending_summaries"].delete_one({"chat_id": chat_id})
                except Exception as e:
                    logger.error(f"Delivery Error for chat {chat_id}: {e}")
        except Exception as global_err:
            logger.error(f"Global Delivery Error: {global_err}")
    async def test_summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manual trigger to test logic immediately."""
        chat_id = update.effective_chat.id
        status = await update.message.reply_text("🧐 Counting messages and reading logs...")
        
        try:
            messages = await self.db[f"chat_{chat_id}"].find().sort("time", 1).to_list(length=1000)
        except Exception:
            messages = []

        if not messages:
            await status.edit_text("❌ Not enough data.")
            return

        # Calculate Stats manually for test
        all_users = [m.get('user', 'Unknown') for m in messages]
        user_counts = Counter(all_users)
        if user_counts:
            top_name, msg_count = user_counts.most_common(1)[0]
            top_user_info = f"Top Chatter: {top_name} ({msg_count} messages)"
        else:
            top_user_info = "Top Chatter: None"

        formatted_logs = "\n".join([f"{m.get('user', 'Unknown')}: {m.get('text', '')}" for m in messages])
        
        story_result = await self._generate_summary_text(formatted_logs, top_user_info)

        await status.edit_text(text=story_result, parse_mode='HTML')
        logger.info(f"✅ Test summary sent to {chat_id}")

    async def run_scheduler(self):
        """Runs the loop. Preps at 7:50 PM IST. Sends at 8:00 PM IST or as soon as ready."""
        logger.info("⏳ Scheduler started [Timezone: Asia/Kolkata]")
        
        while True:
            now_ist = datetime.datetime.now(IST)
            
            # Prep Time: 7:50 PM
            prep_time = now_ist.replace(hour=21, minute=50, second=0, microsecond=0)
            # Post Time: 8:00 PM
            post_time = now_ist.replace(hour=22, minute=0, second=0, microsecond=0)

            # --- LOGIC ---
            # 1. Agar 7:50 PM nahi baje: Wait karo.
            if now_ist < prep_time:
                wait_seconds = (prep_time - now_ist).total_seconds()
                logger.info(f"Waiting {int(wait_seconds)}s for Prep Time...")
                await asyncio.sleep(wait_seconds)
                
                # 7:50 PM ho gaya, Prep shuru
                await self.prepare_summaries()

                # Prep khatam. Ab check karo 8:00 PM baja ya nahi.
                now_ist = datetime.datetime.now(IST)
                if now_ist < post_time:
                    wait_for_post = (post_time - now_ist).total_seconds()
                    logger.info(f"Prep done. Waiting {int(wait_for_post)}s for 8:00 PM...")
                    await asyncio.sleep(wait_for_post)
                
                # 8:00 PM (ya usse thoda late), Deliver karo
                await self.deliver_summaries()

            # 2. Agar hum code restart karte hain aur time 7:50 PM - 8:20 PM ke beech mein hai
            elif prep_time <= now_ist < (post_time + datetime.timedelta(minutes=20)):
                 logger.info("Catching up! Running prep and post immediately.")
                 await self.prepare_summaries()
                 await self.deliver_summaries()
                 # Ensure we don't loop instantly, sleep till tomorrow logic hits
                 await asyncio.sleep(3600) 

            # 3. Raat ke 8:20 PM ke baad: Agle din ka wait
            else:
                tomorrow_prep = prep_time + datetime.timedelta(days=1)
                wait_seconds = (tomorrow_prep - now_ist).total_seconds()
                logger.info(f"Done for today. Sleeping {int(wait_seconds)}s until tomorrow.")
                await asyncio.sleep(wait_seconds)
