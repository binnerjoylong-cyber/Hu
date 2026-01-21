import logging
import datetime
import asyncio
from groq import Groq
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# --- CONFIG ---
GROQ_API_KEY = "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" # Groq Cloud se key lein

class SummaryManager:
    def __init__(self, application, known_users_list):
        self.app = application
        self.known_users = known_users_list
        self.ai_client = Groq(api_key=GROQ_API_KEY)

    async def fetch_and_summarize(self):
        """Raat 7:50 baje chat history uthakar 8 baje post karna"""
        logger.info("Laila is scanning the last 24 hours of history...")
        
        # Sirf Groups ko filter karein
        active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
        
        for chat_id in active_chats:
            try:
                # 1. Pichle 24 ghante ke messages fetch karna (Limit: 2000 messages)
                messages = []
                async for message in self.app.bot.get_chat_history(chat_id, limit=2000):
                    # Check if message is within last 24 hours
                    if message.date < datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1):
                        break
                    if message.text and not message.text.startswith('/'):
                        messages.append(f"{message.from_user.first_name}: {message.text}")
                
                if not messages or len(messages) < 5:
                    continue

                # Reverse taaki chronological order (shuruat se ant tak) rahe
                messages.reverse()
                formatted_logs = "\n".join(messages)

                # 2. AI Prompt (Storytelling + Medium Size)
                prompt = (
                    f"Narrate the highlights of this chat from the last 24 hours as a witty and elite story. "
                    f"Title: 'THE DAILY CHRONICLES'. "
                    f"Format: Medium-sized (not too long, not too short). "
                    f"Mention the main drama, funny interactions, and key topics. "
                    f"End with 'STAR OF THE NIGHT' naming the most impactful user. "
                    f"Language: Sophisticated English with an elite vibe.\n\nLOGS:\n{formatted_logs}"
                )

                # 3. Groq AI se summary generate karna
                completion = self.ai_client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                summary = completion.choices[0].message.content
                
                final_post = (
                    f"🏛 <b>THE DAILY CHRONICLES</b> 🏛\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{summary}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚜️ <i>Curated by Laila. See you tomorrow!</i>"
                )

                # 4. 8:00 PM tak wait karna (agar 7:50 par start hua hai)
                # (Simple sleep logic ya direct send agar time ho gaya ho)
                
                sent_msg = await self.app.bot.send_message(chat_id, final_post, parse_mode='HTML')
                await self.app.bot.pin_chat_message(chat_id, sent_msg.message_id)
                logger.info(f"Summary pinned in {chat_id}")

            except Exception as e:
                logger.error(f"Error in {chat_id}: {e}")

    async def run_scheduler(self):
        """Raat 7:50 PM par trigger hone ka scheduler"""
        while True:
            now = datetime.datetime.now()
            # 19:50 means 7:50 PM
            target = now.replace(hour=19, minute=50, second=0, microsecond=0)
            
            if now >= target:
                target += datetime.timedelta(days=1)
            
            wait_time = (target - now).total_seconds()
            logger.info(f"Laila will scan chat in {wait_time/3600:.2f} hours.")
            
            await asyncio.sleep(wait_time)
            await self.fetch_and_summarize()
