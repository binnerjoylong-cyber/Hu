import asyncio
import random
import logging
import requests
import html
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- 🎮 EMOJI GAME DATA ---
# Aap yahan aur emojis add kar sakte hain
EMOJI_GUESS_DATA = [
    {"img": "https://i.ibb.co/3yk8m2W/movie-quiz.jpg", "a": "Spider-Man", "options": ["Spider-Man", "Batman", "Iron Man"]},
    {"img": "https://i.ibb.co/6R2M3nS/fruit-emoji.jpg", "a": "Strawberry", "options": ["Apple", "Strawberry", "Cherry"]},
    {"img": "https://i.ibb.co/4P6fQv3/country-quiz.jpg", "a": "India", "options": ["India", "Italy", "Mexico"]},
]

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "trivia" # Toggle karne ke liye
        self.start_times = {} # Har message ka start time track karne ke liye

    def get_api_question(self):
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
        except: pass
        return {"q": "Which planet is Red?", "options": ["Mars", "Earth", "Venus"], "a": "Mars"}

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        data = query.data.split(":") # trivia:yes/no:Answer
        
        # Calculate time taken
        end_time = time.time()
        start_time_val = self.start_times.get(msg_id, end_time)
        time_taken = round(end_time - start_time_val, 2)

        if data[1] == "yes":
            await query.answer(f"🎉 Correct, {user.first_name}!", show_alert=True)
            
            result_text = (
                f"🏆 **CHAMPION FOUND!**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **User:** {user.first_name}\n"
                f"✅ **Answer:** {data[2]}\n"
                f"⚡ **Time Taken:** `{time_taken} seconds`\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👏 Well done! Next game in 30 minutes."
            )
            
            # Agar photo wala message hai (Emoji), toh edit_caption karein
            if query.message.photo:
                await query.edit_message_caption(caption=result_text, parse_mode='Markdown')
            else:
                await query.edit_message_text(text=result_text, parse_mode='Markdown')
            
            # Message ID clean up
            if msg_id in self.start_times: del self.start_times[msg_id]
        else:
            await query.answer(f"❌ Wrong choice, {user.first_name}! Try again.", show_alert=False)

    async def start_loop(self):
        logger.info("Universal Game Loop Started!")
        await asyncio.sleep(10) 
        
        while True:
            try:
                chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                
                if self.current_mode == "trivia":
                    # --- MODE: TRIVIA ---
                    q_data = self.get_api_question()
                    text = f"🧩 **LAILA'S TRIVIA QUIZ**\n\n{q_data['q']}"
                    kb = [[InlineKeyboardButton(opt, callback_data=f"trivia:{'yes' if opt==q_data['a'] else 'no'}:{opt}")] for opt in q_data['options']]
                    
                    for chat_id in chats:
                        msg = await self.application.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
                        self.start_times[msg.message_id] = time.time()
                    
                    self.current_mode = "emoji" # Agla round emoji
                    
                else:
                    # --- MODE: EMOJI GUESS ---
                    e_data = random.choice(EMOJI_GUESS_DATA)
                    caption = "🖼 **EMOJI GUESSING GAME**\n\nGuess the name from the emojis in the photo!"
                    kb = [[InlineKeyboardButton(opt, callback_data=f"trivia:{'yes' if opt==e_data['a'] else 'no'}:{opt}")] for opt in e_data['options']]
                    
                    for chat_id in chats:
                        msg = await self.application.bot.send_photo(chat_id=chat_id, photo=e_data['img'], caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
                        self.start_times[msg.message_id] = time.time()
                    
                    self.current_mode = "trivia" # Agla round trivia

            except Exception as e:
                logger.error(f"Game Loop Error: {e}")

            await asyncio.sleep(1800) # 30 Minutes
