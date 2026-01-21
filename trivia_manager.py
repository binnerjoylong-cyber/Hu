import asyncio
import random
import logging
import requests
import html
import time
import io
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- 🎭 CONFIGURATION ---
EMOJI_POOL = ["🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀"]
BG_IMAGE_URL = "https://i.ibb.co/3yk8m2W/movie-quiz.jpg" # Background photo link

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "trivia"
        self.game_data = {} # Stores {msg_id: {start_time, correct_answer, expires_at}}

    def create_emoji_image(self, target_emoji):
        """Pillow library se background par emoji chipkane ke liye"""
        try:
            # 1. Background download karein
            response = requests.get(BG_IMAGE_URL)
            img = Image.open(io.BytesIO(response.content)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            
            # 2. Font load karein (System font use karein ya .ttf file path dein)
            # Unicode emojis ke liye 'Symbola' ya 'Apple Color Emoji' best hote hain
            try:
                font = ImageFont.truetype("arial.ttf", 150) 
            except:
                font = ImageFont.load_default()

            # 3. Emoji ko random position par chipkayein
            width, height = img.size
            x = random.randint(50, width - 150)
            y = random.randint(50, height - 150)
            
            # Draw emoji
            draw.text((x, y), target_emoji, font=font, fill=(255, 255, 255, 255))
            
            # 4. Image ko bytes mein convert karein
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Pillow Error: {e}")
            return None

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
        return {"q": "Which is the largest planet?", "options": ["Jupiter", "Mars", "Saturn"], "a": "Jupiter"}

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        data = query.data.split(":") # trivia:yes/no:Answer
        
        if msg_id not in self.game_data:
            await query.answer("This game session is closed!", show_alert=True)
            return

        game = self.game_data[msg_id]
        
        # Check Expiry (15 Mins)
        if time.time() > game['expires_at']:
            await query.answer("⏰ Time's up! Game expired.", show_alert=True)
            try: await query.edit_message_caption(caption="❌ **Game Expired!**\nNo one guessed in 15 minutes.")
            except: pass
            del self.game_data[msg_id]
            return

        if data[1] == "yes":
            time_taken = round(time.time() - game['start_time'], 2)
            await query.answer(f"🎉 Correct, {user.first_name}!", show_alert=True)
            
            result_text = (
                f"✨ <b>CHAMPION DECLARED!</b> ✨\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>User:</b> {user.mention_html()}\n"
                f"🎯 <b>Answer:</b> <code>{data[2]}</code>\n"
                f"⚡ <b>Solved In:</b> <code>{time_taken}s</code>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Next surprise game in 30 mins!</i>"
            )
            
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=result_text, parse_mode='HTML')
                else:
                    await query.edit_message_text(text=result_text, parse_mode='HTML')
                del self.game_data[msg_id]
            except: pass
        else:
            await query.answer(f"❌ No! Try again, {user.first_name}!", show_alert=False)

    async def start_loop(self):
        logger.info("Universal Game Loop (Pillow Edition) Started!")
        await asyncio.sleep(30)
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                expiry_time = 900 # 15 Min Limit
                
                if self.current_mode == "trivia":
                    # --- MODE: TRIVIA ---
                    q_data = self.get_api_question()
                    text = f"🧩 <b>LAILA'S IQ CHALLENGE</b>\n\n<b>Q:</b> <code>{q_data['q']}</code>\n\n⏱ <i>15 minutes left!</i>"
                    kb = [[InlineKeyboardButton(opt, callback_data=f"trivia:{'yes' if opt==q_data['a'] else 'no'}:{opt}")] for opt in q_data['options']]
                    
                    for chat_id in active_chats:
                        try:
                            msg = await self.application.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                            self.game_data[msg.message_id] = {"start_time": time.time(), "expires_at": time.time() + expiry_time}
                        except: continue
                    self.current_mode = "emoji"
                    
                else:
                    # --- MODE: EMOJI (PILLOW IMAGE) ---
                    target_emoji = random.choice(EMOJI_POOL)
                    photo_bytes = self.create_emoji_image(target_emoji)
                    
                    if photo_bytes:
                        caption = "🖼 <b>EMOJI HUNTING!</b>\n\nFind the emoji shown on the photo in the buttons below\!"
                        
                        # Emoji Grid (12 random emojis including correct one)
                        grid_emojis = random.sample(EMOJI_POOL, 11)
                        if target_emoji not in grid_emojis: grid_emojis.append(target_emoji)
                        random.shuffle(grid_emojis)

                        kb = []
                        row = []
                        for emo in grid_emojis:
                            row.append(InlineKeyboardButton(emo, callback_data=f"trivia:{'yes' if emo==target_emoji else 'no'}:{emo}"))
                            if len(row) == 4:
                                kb.append(row)
                                row = []

                        for chat_id in active_chats:
                            try:
                                photo_bytes.seek(0)
                                msg = await self.application.bot.send_photo(chat_id=chat_id, photo=photo_bytes, caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                                self.game_data[msg.message_id] = {"start_time": time.time(), "expires_at": time.time() + expiry_time}
                            except: continue
                    
                    self.current_mode = "trivia"

            except Exception as e:
                logger.error(f"Loop Error: {e}")

            await asyncio.sleep(1800) # 30 Mins
