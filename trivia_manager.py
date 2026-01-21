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

# --- CONFIG ---
EMOJI_POOL = ["🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀"]
BG_IMAGE_URL = "https://i.ibb.co/3yk8m2W/movie-quiz.jpg" 

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "emoji" # Sabse pehle Emoji game aayega
        self.active_games = {} # {msg_id: {data...}}

    def create_emoji_image(self, target_emoji):
        try:
            response = requests.get(BG_IMAGE_URL)
            img = Image.open(io.BytesIO(response.content)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            # Font size 150 for visibility
            try: font = ImageFont.truetype("arial.ttf", 150)
            except: font = ImageFont.load_default()
            
            width, height = img.size
            x, y = random.randint(50, width-200), random.randint(50, height-200)
            draw.text((x, y), target_emoji, font=font, fill=(255, 255, 255, 255))
            
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
                ans = html.unescape(item['correct_answer'])
                opts = [html.unescape(o) for o in item['incorrect_answers']] + [ans]
                random.shuffle(opts)
                return {"q": q, "options": opts, "a": ans}
        except: pass
        return {"q": "Which is the red planet?", "options": ["Mars", "Earth", "Venus"], "a": "Mars"}

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        data = query.data.split(":") # trivia:yes/no:answer

        if msg_id not in self.active_games:
            await query.answer("This game is no longer active!", show_alert=True)
            return

        game = self.active_games[msg_id]

        # 1. Check if already solved
        if game.get('winner'):
            await query.answer(f"⚠️ Quiz already solved by {game['winner_name']}!", show_alert=True)
            return

        # 2. Check Expiry
        if time.time() > game['expires_at']:
            await query.answer("⏰ Time up! Game expired.", show_alert=True)
            return

        # 3. Process Answer
        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer(f"🎉 Correct, {user.first_name}!", show_alert=True)
            
            status_text = (
                f"🏆 <b>QUIZ SOLVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Winner:</b> {user.mention_html()}\n"
                f"🎯 <b>Answer:</b> <code>{data[2]}</code>\n"
                f"⚡ <b>Time:</b> <code>{time_taken}s</code>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Next challenge in 30 minutes!</i>"
            )
            
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=status_text, parse_mode='HTML', reply_markup=query.message.reply_markup)
                else:
                    await query.edit_message_text(text=status_text, parse_mode='HTML', reply_markup=query.message.reply_markup)
            except: pass
        else:
            await query.answer("❌ Wrong! Try again.", show_alert=False)

    async def send_alerts(self, chat_id, msg_id):
        """10 min aur 5 min left ke alerts ke liye"""
        try:
            await asyncio.sleep(300) # 5 min baad
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⏳ <b>Trivia Alert:</b> 10 minutes left to solve!", parse_mode='HTML')
            
            await asyncio.sleep(300) # Aur 5 min baad
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⏳ <b>Trivia Alert:</b> Only 5 minutes remaining!", parse_mode='HTML')
        except: pass

    async def start_loop(self):
        logger.info("Universal Game Loop (Advanced) Started!")
        await asyncio.sleep(10) # Pehla game 10 sec baad
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                expiry = time.time() + 900 # 15 mins
                
                if self.current_mode == "emoji":
                    target = random.choice(EMOJI_POOL)
                    photo = self.create_emoji_image(target)
                    if photo:
                        opts = random.sample(EMOJI_POOL, 11)
                        if target not in opts: opts.append(target)
                        random.shuffle(opts)
                        kb = []
                        row = []
                        for e in opts:
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{'yes' if e==target else 'no'}:{e}"))
                            if len(row) == 4: kb.append(row); row = []
                        
                        for cid in active_chats:
                            photo.seek(0)
                            msg = await self.application.bot.send_photo(cid, photo=photo, caption="🖼 <b>EMOJI HUNT!</b>\nFind the emoji on the photo below!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                            asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    self.current_mode = "trivia"
                else:
                    q = self.get_api_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    for cid in active_chats:
                        msg = await self.application.bot.send_message(cid, f"🧩 <b>QUIZ TIME</b>\n\n{q['q']}", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                        self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                        asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    self.current_mode = "emoji"

            except Exception as e: logger.error(f"Loop Error: {e}")
            await asyncio.sleep(1800) # 30 min wait
