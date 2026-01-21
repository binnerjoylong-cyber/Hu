import asyncio
import random
import logging
import html
import time
import io
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- CONFIG ---
EMOJI_POOL = ["🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸"]

# Yahan apni Frame ki Telegram FILE ID daalein
# (Bot Father ya kisi bhi ID bot se ye ID nikaal sakte hain)
FRAME_FILE_ID = "AgACAgUAAyEFAATHcBuEAAICvGlwh5iWzzYJvgSuOE-EPOtjTa7XAAJnDWsb5FOJVwFVYd7UN29_AQADAgADeQADOAQ" 

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "emoji"
        self.active_games = {} 
        self.cached_frame = None # Memory me frame store karne ke liye

    async def get_frame_from_telegram(self):
        """Telegram server se File ID ke zariye photo bytes fetch karna"""
        if self.cached_frame is None:
            try:
                # File ID se file object lena
                file = await self.application.bot.get_file(FRAME_FILE_ID)
                # Bytes me download karna
                photo_bytes = await file.download_as_bytearray()
                self.cached_frame = bytes(photo_bytes)
                logger.info("Frame cached successfully from Telegram File ID!")
            except Exception as e:
                logger.error(f"Error fetching File ID: {e}")
        return self.cached_frame

    async def create_emoji_image(self, target_emoji):
        try:
            frame_data = await self.get_frame_from_telegram()
            if not frame_data: return None

            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            
            # Font setting (System default ya custom path)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 180)
            except:
                try: font = ImageFont.truetype("arial.ttf", 180)
                except: font = ImageFont.load_default()
            
            # --- Emoji Center Logic ---
            width, height = img.size
            bbox = draw.textbbox((0, 0), target_emoji, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            x = (width - tw) // 2
            y = (height - th) // 2 - 20 # Center adjustment
            
            draw.text((x, y), target_emoji, font=font, fill=(255, 255, 255, 255))
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Pillow Logic Error: {e}")
            return None

    def get_api_question(self):
        try:
            import requests
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
        data = query.data.split(":") 

        if msg_id not in self.active_games:
            await query.answer("This game session is old!", show_alert=True)
            return

        game = self.active_games[msg_id]

        if game.get('winner'):
            await query.answer(f"⚠️ Quiz already solved by {game['winner_name']}!", show_alert=True)
            return

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
                f"⚡ <b>Solved In:</b> <code>{time_taken}s</code>\n"
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
            await query.answer("❌ Galat Jawab! Try again.", show_alert=False)

    async def send_alerts(self, chat_id, msg_id):
        try:
            await asyncio.sleep(300) # 10 Min Alert
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⏳ <b>10 Minutes Left!</b>", parse_mode='HTML')
            await asyncio.sleep(300) # 5 Min Alert
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⚠️ <b>Hurry Up! 5 Minutes Remaining!</b>", parse_mode='HTML')
        except: pass

    async def start_loop(self):
        logger.info("Emoji-ID Frame Loop Started!")
        await asyncio.sleep(5) 
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                expiry = time.time() + 900 
                
                if self.current_mode == "emoji":
                    target = random.choice(EMOJI_POOL)
                    photo = await self.create_emoji_image(target)
                    
                    if photo:
                        grid_opts = random.sample(EMOJI_POOL, 15)
                        if target not in grid_opts: grid_opts[0] = target
                        random.shuffle(grid_opts)
                        
                        kb = []
                        row = []
                        for e in grid_opts:
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{'yes' if e==target else 'no'}:{e}"))
                            if len(row) == 5: kb.append(row); row = []
                        
                        for cid in active_chats:
                            photo.seek(0)
                            msg = await self.application.bot.send_photo(
                                cid, photo=photo, 
                                caption="🖼 <b>EMOJI HUNT!</b>\nIdentify the emoji in the frame and click below!", 
                                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
                            )
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                            asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    self.current_mode = "trivia"
                else:
                    q = self.get_api_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    for cid in active_chats:
                        msg = await self.application.bot.send_message(cid, f"🧩 <b>TRIVIA QUIZ</b>\n\n{q['q']}", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                        self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                        asyncio.create_task(self.send_alerts(cid, msg.message_id))
                    self.current_mode = "emoji"

            except Exception as e: logger.error(f"Loop Error: {e}")
            await asyncio.sleep(1800)
