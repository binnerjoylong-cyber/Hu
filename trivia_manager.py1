import asyncio
import random
import logging
import html
import time
import io
import requests
from PIL import Image, ImageDraw
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- CONFIG ---
# In Emojis ke liye hum Google ki image API use karenge
EMOJI_POOL = ["🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸"]

# Apni Frame ki File ID yahan daalein
FRAME_FILE_ID = "AgACAgUAAyEFAATHcBuEAAICvGlwh5iWzzYJvgSuOE-EPOtjTa7XAAJnDWsb5FOJVwFVYd7UN29_AQADAgADeQADOAQ" 

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "emoji"
        self.active_games = {} 
        self.cached_frame = None

    async def get_frame_from_telegram(self):
        if self.cached_frame is None:
            try:
                file = await self.application.bot.get_file(FRAME_FILE_ID)
                photo_bytes = await file.download_as_bytearray()
                self.cached_frame = bytes(photo_bytes)
                logger.info("✅ Frame Cached!")
            except Exception as e:
                logger.error(f"❌ Frame Error: {e}")
        return self.cached_frame

    def get_emoji_image_url(self, emoji):
        """Emoji ko image me convert karne ke liye Google ki repo use karte hain"""
        # Emoji ka hex code nikalte hain
        hex_code = "-".join([f"{ord(c):x}" for c in emoji])
        return f"https://raw.githubusercontent.com/googlefonts/noto-emoji/master/png/512/emoji_u{hex_code}.png"

    async def create_emoji_image(self, target_emoji):
        try:
            # 1. Frame load karein
            frame_data = await self.get_frame_from_telegram()
            if not frame_data: return None
            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            
            # 2. Emoji ki HD Image download karein
            emoji_url = self.get_emoji_image_url(target_emoji)
            emoji_resp = requests.get(emoji_url, timeout=5)
            emoji_img = Image.open(io.BytesIO(emoji_resp.content)).convert("RGBA")
            
            # 3. Emoji ka size bada karein (Frame ke hisab se 250x250 ya 300x300)
            emoji_img = emoji_img.resize((250, 250), Image.Resampling.LANCZOS)
            
            # 4. Center Calculation
            width, height = img.size
            ew, eh = emoji_img.size
            x = (width - ew) // 2
            y = (height - eh) // 2
            
            # 5. Emoji ko Frame par chipka do
            img.alpha_composite(emoji_img, (x, y))
            
            # PNG me save karein taaki quality bani rahe
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
            
        except Exception as e:
            logger.error(f"Pillow Image Fix Error: {e}")
            return None

    # ... [Baki ka code: get_api_question, handle_callback, start_loop pehle jaisa hi rahega] ...
    # Bus 'create_emoji_image' ko upar wale se replace kar dena.
            
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
        chat_id = query.message.chat_id
        data = query.data.split(":") 

        if msg_id not in self.active_games:
            await query.answer("This gaming session has concluded!", show_alert=True)
            return

        game = self.active_games[msg_id]

        if game.get('winner'):
            await query.answer(f"Status: This challenge was already claimed by {game['winner_name']}.", show_alert=True)
            return

        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer(f"Excellent work, {user.first_name}!", show_alert=False)
            
            # 1. Update Main Game Message with a sleek look
            status_text = (
                f"🏛 <b>CHALLENGE ARCHIVED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Claimed By:</b> {user.mention_html()}\n"
                f"🎯 <b>Objective:</b> <code>{data[2]}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Stand by for the next elite challenge.</i>"
            )
            
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=status_text, parse_mode='HTML', reply_markup=query.message.reply_markup)
                else:
                    await query.edit_message_text(text=status_text, parse_mode='HTML', reply_markup=query.message.reply_markup)
            except: pass

            # 2. Grand Victory Shoutout (Proper English)
            congrats_msg = (
                f"✨ <b>PRESTIGIOUS VICTORY!</b> ✨\n\n"
                f"A round of applause for {user.mention_html()}! 🏆\n\n"
                f"With remarkable precision, you identified <b>'{data[2]}'</b> in a staggering <code>{time_taken}s</code>.\n\n"
                f"⚜️ <i>Laila acknowledges your superior observation skills. You have set a new benchmark for the group!</i> 🧿"
            )
            
            try:
                # Sending the separate elite shoutout
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=congrats_msg,
                    reply_to_message_id=msg_id,
                    parse_mode='HTML'
                )
                
                # 3. High-Intensity Reaction Burst (10 Premium Reactions)
                # Note: We send the most important ones first
                reactions_list = [
                    {"type": "emoji", "emoji": e} 
                    for e in ["🔥", "🏆", "👏", "⚡", "👑", "✨", "🎊", "😎", "💃", "🌟"]
                ]
                
                try:
                    await context.bot.set_message_reaction(
                        chat_id=chat_id,
                        message_id=sent_msg.message_id,
                        reaction=reactions_list
                    )
                except Exception as e:
                    logger.error(f"Failed to set reactions: {e}")
                    
            except Exception as e:
                logger.error(f"Error sending congrats: {e}")

        else:
            await query.answer("Incorrect attempt. Focus and try again!", show_alert=False)
            
    async def send_alerts(self, chat_id, msg_id):
        """Countdown: 10m aur 5m bache hone par alerts"""
        try:
            await asyncio.sleep(300) 
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⏳ <b>10 Minutes Left!</b>", parse_mode='HTML')
            await asyncio.sleep(300) 
            if msg_id in self.active_games and not self.active_games[msg_id].get('winner'):
                await self.application.bot.send_message(chat_id, "⚠️ <b>Only 5 Minutes Left!</b>", parse_mode='HTML')
        except: pass

    async def start_loop(self):
        logger.info("Advanced Trivia Loop Started!")
        await asyncio.sleep(10) # Pehla game 10 sec baad
        
        while True:
            try:
                # Sirf Groups ko filter karein
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
                            try:
                                photo.seek(0)
                                msg = await self.application.bot.send_photo(
                                    cid, photo=photo, 
                                    caption="🖼 <b>EMOJI HUNT!</b>\nFind the emoji in the frame and click below!", 
                                    reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                                asyncio.create_task(self.send_alerts(cid, msg.message_id))
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                if "Chat not found" in str(e) or "Forbidden" in str(e):
                                    self.known_users.discard(cid) # Invalid chat hata do
                    self.current_mode = "trivia"
                else:
                    q = self.get_api_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    for cid in active_chats:
                        try:
                            msg = await self.application.bot.send_message(cid, f"🧩 <b>TRIVIA QUIZ</b>\n\n{q['q']}", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                            asyncio.create_task(self.send_alerts(cid, msg.message_id))
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            if "Chat not found" in str(e) or "Forbidden" in str(e):
                                self.known_users.discard(cid)
                    self.current_mode = "emoji"

            except Exception as e: logger.error(f"Loop Error: {e}")
            await asyncio.sleep(1800) # 30 min wait
