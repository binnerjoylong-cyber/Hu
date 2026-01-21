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
EMOJI_POOL = ["🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸"]
BG_IMAGE_URL = "https://i.postimg.cc/02tYm8P8/game-bg.jpg" # Maine ek HD background link dala hai

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "emoji" # Sabse pehle Emoji game check karne ke liye
        self.active_games = {} 

    def create_emoji_image(self, target_emoji):
        try:
            # 1. Background download aur resize
            response = requests.get(BG_IMAGE_URL, timeout=10)
            img = Image.open(io.BytesIO(response.content)).convert("RGBA")
            
            # Agar image choti hai toh use 800x500 kar do taaki randrange error na aaye
            if img.width < 500 or img.height < 300:
                img = img.resize((800, 500))
            
            draw = ImageDraw.Draw(img)
            
            # 2. Font load logic
            try:
                # Render/Linux par fonts path alag ho sakta hai
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 120)
            except:
                try: font = ImageFont.truetype("arial.ttf", 120)
                except: font = ImageFont.load_default()
            
            # 3. Safe random positioning (Error Fix)
            width, height = img.size
            x = random.randint(50, max(60, width - 150))
            y = random.randint(50, max(60, height - 150))
            
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
        return {"q": "Which planet is known as the Red Planet?", "options": ["Mars", "Venus", "Jupiter"], "a": "Mars"}

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        data = query.data.split(":") # trivia:yes/no:answer

        if msg_id not in self.active_games:
            await query.answer("This game session is closed!", show_alert=True)
            return

        game = self.active_games[msg_id]

        if game.get('winner'):
            await query.answer(f"⚠️ Already solved by {game['winner_name']}!", show_alert=True)
            return

        if time.time() > game['expires_at']:
            await query.answer("⏰ Time expired! 15 minutes are over.", show_alert=True)
            return

        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer(f"🎉 Correct, {user.first_name}!", show_alert=True)
            
            status_text = (
                f"✨ <b>CHAMPION FOUND!</b> ✨\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Winner:</b> {user.mention_html()}\n"
                f"🎯 <b>Answer:</b> <code>{data[2]}</code>\n"
                f"⚡ <b>Reaction Time:</b> <code>{time_taken}s</code>\n"
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
        """Countdown alerts: 10 min aur 5 min bache hone par"""
        try:
            # 5 min baad (10 min bache hain)
            await asyncio.sleep(300) 
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⏳ <b>10 MINUTES LEFT!</b>\nSolve the quiz before time runs out!", parse_mode='HTML')
            
            # Aur 5 min baad (5 min bache hain)
            await asyncio.sleep(300) 
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⚠️ <b>HURRY UP!</b>\nOnly 5 minutes remaining!", parse_mode='HTML')
        except: pass

    async def start_loop(self):
        logger.info("Advanced Game Loop Started!")
        await asyncio.sleep(10) # 10 seconds baad pehla game check karne ke liye
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                expiry = time.time() + 900 # 15 min total time
                
                if self.current_mode == "emoji":
                    target = random.choice(EMOJI_POOL)
                    photo = self.create_emoji_image(target)
                    
                    if photo:
                        # 15 random emojis ka grid
                        grid_opts = random.sample(EMOJI_POOL, 15)
                        if target not in grid_opts: grid_opts[0] = target
                        random.shuffle(grid_opts)
                        
                        kb = []
                        row = []
                        for e in grid_opts:
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{'yes' if e==target else 'no'}:{e}"))
                            if len(row) == 5: # 5 emojis per row
                                kb.append(row)
                                row = []
                        
                        for cid in active_chats:
                            photo.seek(0)
                            msg = await self.application.bot.send_photo(
                                cid, 
                                photo=photo, 
                                caption="🖼 <b>EMOJI HUNTING!</b>\nFind the emoji hidden in the photo and click it below!", 
                                reply_markup=InlineKeyboardMarkup(kb), 
                                parse_mode='HTML'
                            )
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                            asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    
                    self.current_mode = "trivia" # Agla mode toggle
                    
                else:
                    # --- MODE: TRIVIA ---
                    q = self.get_api_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    
                    for cid in active_chats:
                        msg = await self.application.bot.send_message(
                            cid, 
                            f"🧩 <b>INTELLIGENCE QUIZ</b>\n\n{q['q']}\n\n⏱ <i>15 minutes left!</i>", 
                            reply_markup=InlineKeyboardMarkup(kb), 
                            parse_mode='HTML'
                        )
                        self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                        asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    
                    self.current_mode = "emoji" # Agla mode toggle

            except Exception as e:
                logger.error(f"Loop Error: {e}")
            
            await asyncio.sleep(1800) # 30 min wait
