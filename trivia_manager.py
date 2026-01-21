import asyncio
import random
import logging
import requests
import html
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- 🖼️ EMOJI GAME DATA ---
# Yahan aap apne pasand ke photos aur answers add kar sakte hain
EMOJI_GUESS_DATA = [
    {"img": "https://i.ibb.co/3yk8m2W/movie-quiz.jpg", "a": "Spider-Man", "options": ["Spider-Man", "Batman", "Iron Man"]},
    {"img": "https://i.ibb.co/6R2M3nS/fruit-emoji.jpg", "a": "Strawberry", "options": ["Apple", "Strawberry", "Cherry"]},
    {"img": "https://i.ibb.co/4P6fQv3/country-quiz.jpg", "a": "India", "options": ["India", "Italy", "Mexico"]},
    {"img": "https://i.ibb.co/m0vYmS8/disney-quiz.jpg", "a": "Mickey Mouse", "options": ["Donald Duck", "Mickey Mouse", "Goofy"]},
]

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "trivia" # Pehla round Trivia se start hoga
        self.start_times = {} # Har message ka time track karne ke liye

    def get_api_question(self):
        """API se naya sawal fetch karne ke liye"""
        try:
            url = "https://opentdb.com/api.php?amount=1&type=multiple&difficulty=easy"
            data = requests.get(url, timeout=5).json()
            if data['response_code'] == 0:
                item = data['results'][0]
                q = html.unescape(item['question'])
                correct = html.unescape(item['correct_answer'])
                options = [html.unescape(ans) for ans in item['incorrect_answers']] + [correct]
                random.shuffle(options)
                return {"q": q, "options": options, "a": correct}
        except: 
            pass
        return {"q": "Which is the largest planet?", "options": ["Earth", "Jupiter", "Mars"], "a": "Jupiter"}

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Jab koi button dabaye"""
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        data = query.data.split(":") # trivia:yes/no:Answer
        
        # Kitne der mein answer diya
        end_time = time.time()
        start_time_val = self.start_times.get(msg_id, end_time)
        time_taken = round(end_time - start_time_val, 2)

        if data[1] == "yes":
            await query.answer(f"🎉 Correct, {user.first_name}!", show_alert=True)
            
            result_text = (
                f"🏆 **WINNER FOUND!**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **User:** {user.mention_markdown_v2()}\n"
                f"✅ **Answer:** {data[2]}\n"
                f"⚡ **Solved In:** `{time_taken}s`\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Next challenge in 30 minutes\!"
            )
            
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=result_text, parse_mode='MarkdownV2')
                else:
                    await query.edit_message_text(text=result_text, parse_mode='MarkdownV2')
                
                # Time data saaf karein
                if msg_id in self.start_times: del self.start_times[msg_id]
            except: pass
        else:
            await query.answer(f"❌ Wrong! Try again, {user.first_name}", show_alert=False)

    async def start_loop(self):
        """Background Loop (Render support)"""
        logger.info("Game Loop Started!")
        await asyncio.sleep(60) # Bot start ke 1 min baad shuru
        
        while True:
            try:
                # Sirf Groups ko filter karein
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                
                if self.current_mode == "trivia":
                    # --- MODE: TRIVIA (TEXT) ---
                    q_data = self.get_api_question()
                    text = f"🧩 **LAILA'S TRIVIA QUIZ**\n\n{q_data['q']}"
                    kb = [[InlineKeyboardButton(opt, callback_data=f"trivia:{'yes' if opt==q_data['a'] else 'no'}:{opt}")] for opt in q_data['options']]
                    
                    for chat_id in active_chats:
                        try:
                            msg = await self.application.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
                            self.start_times[msg.message_id] = time.time()
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            if "Chat not found" in str(e) or "Forbidden" in str(e):
                                self.known_users.remove(chat_id)
                    
                    self.current_mode = "emoji" # Agla mode emoji
                    
                else:
                    # --- MODE: EMOJI (PHOTO) ---
                    e_data = random.choice(EMOJI_GUESS_DATA)
                    caption = "🖼 **EMOJI GUESSING GAME**\n\nGuess the correct name from the photo\!"
                    kb = [[InlineKeyboardButton(opt, callback_data=f"trivia:{'yes' if opt==e_data['a'] else 'no'}:{opt}")] for opt in e_data['options']]
                    
                    for chat_id in active_chats:
                        try:
                            msg = await self.application.bot.send_photo(chat_id=chat_id, photo=e_data['img'], caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode='MarkdownV2')
                            self.start_times[msg.message_id] = time.time()
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            if "Chat not found" in str(e) or "Forbidden" in str(e):
                                self.known_users.remove(chat_id)
                    
                    self.current_mode = "trivia" # Agla mode trivia

            except Exception as e:
                logger.error(f"Game Loop Error: {e}")

            await asyncio.sleep(1800) # 30 minutes wait
