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
            # Jyada purane messages na ho isliye limit 2000-3000 sahi hai
            messages = await self.db[coll_name].find().sort("time", 1).to_list(length=3000)
            
            if not messages or len(messages) < 5: continue

            # Logs format karna
            formatted_logs = "\n".join([f"{m['user']}: {m['text']}" for m in messages])
            
            # --- DESI STORYTELLER PROMPT ---
            system_prompt = (
                "You are a funny and chill Hinglish Storyteller for a Telegram group. "
                "Your job is to tell today's chat highlights like a spicy story (kahani). "
                "Rules:\n"
                "1. Strictly NO bullet points. Write 2-3 smooth paragraphs.\n"
                "2. Use very simple Hinglish/English (like talking to a friend).\n"
                "3. ALWAYS write User Names in BOLD like <b>Name</b>.\n"
                "4. Make it interesting and funny. Use emojis naturally.\n"
                "5. Start with a catchy headline like 'Bhaiyo aur Behno, aaj ka kissa suno...'"
            )

            try:
                completion = self.ai_client.chat.completions.create(
                    model="llama-3.1-8b-instant", # Best for natural language
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Bhai, is chat ka ek mast summary story bana de: \n\n{formatted_logs}"}
                    ],
                    max_tokens=1000,
                    temperature=0.8, # Thoda creative banane ke liye
                )

                summary_text = completion.choices[0].message.content

                # Pending summaries mein save karna
                await self.db["pending_summaries"].update_one(
                    {"chat_id": chat_id},
                    {"$set": {"summary": summary_text, "status": "ready"}},
                    upsert=True
                )
                
                # Collection saaf karna taaki kal naye messages aayein
                await self.db[coll_name].delete_many({})
                logger.info(f"✅ Desi Story Summary ready for {chat_id}")

            except Exception as e:
                logger.error(f"AI Prep Error for {chat_id}: {e}")
   
   
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
        
        # Ek mast reacting message
        status = await update.message.reply_text("🧐 Ruko bhai, poore din ka kissa nikaal rahi hoon...")
        
        # Logs uthana
        try:
            messages = await self.db[f"chat_{chat_id}"].find().sort("time", 1).to_list(length=500)
        except Exception as db_err:
            logger.error(f"DB Error: {db_err}")
            messages = []

        if not messages:
            await status.edit_text("❌ Abe yaar, group mein koi baat hi nahi hui! Pehle thoda gup-shup karo.")
            return

        formatted_logs = "\n".join([f"{m.get('user', 'Unknown')}: {m.get('text', '')}" for m in messages])
        
        try:
            # AI se story banwana
            completion = self.ai_client.chat.completions.create(
                model="llama-3.1-8b-instant", # Groq ka naya aur tez model
                messages=[
                    {
                        "role": "system", 
                        "content": """You are a chill Hinglish storyteller. 
                        Narrate the chat history as a short, funny, and spicy story.
                        Rules:
                        1. No bullet points. Use 2-3 small paragraphs.
                        2. Use very simple Hinglish/English. No hard words.
                        3. ALWAYS wrap User Names in <b>Name</b> tags.
                        4. Headline should be catchy. 
                        5. Make it feel like 'Group ki Gossip'."""
                    },
                    {
                        "role": "user", 
                        "content": f"Bhai, is chat ki ek mast Hinglish story bana de simple words mein. Names bold rakhna: {formatted_logs}"
                    }
                ],
                max_tokens=800,
                temperature=0.8
            )
            
            story_result = completion.choices[0].message.content

            # Final message bhejte waqt HTML mode zaroori hai
            await status.edit_text(
                text=story_result, 
                parse_mode='HTML'
            )
            logger.info(f"✅ Test summary sent to {chat_id}")

        except Exception as e:
            logger.error(f"❌ Test Summary Error: {e}")
            await status.edit_text("⚠️ Arre baap re! AI thoda thak gaya hai, baad mein try karo.")   

    

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
