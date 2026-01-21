import asyncio
import random
import logging
import html
import time
import io
import requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# 50+ Fresh Emojis for the pool
EMOJI_POOL = [
    "🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸",
    "🍍", "🦚", "🎲", "🛸", "🍟", "🍿", "🛹", "🎯", "🎭", "🎬", "🎨", "🧩", "🎤", "🎧", "🎷", "🎸", "🎺", "🎻", "🎬", "🏹",
    "🌋", "🛰", "🎡", "🎢", "🚢", "🛫", "🪐", "🌟", "🌙", "🥨", "🥓", "🍔", "🍣", "🌮", "🍭", "🍫", "🍯", "🥂", "🥃", "🧉"
]

# Your Frame File ID
FRAME_FILE_ID = "AgACAgUAAyEFAATHcBuEAAICvGlwh5iWzzYJvgSuOE-EPOtjTa7XAAJnDWsb5FOJVwFVYd7UN29_AQADAgADeQADOAQ" 

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        self.current_mode = "emoji" # Toggles between 'emoji' and 'trivia'
        self.active_games = {} 
        self.cached_frame = None

    # --- IMAGE GENERATION HELPERS ---
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
        hex_code = "-".join([f"{ord(c):x}" for c in emoji])
        return f"https://raw.githubusercontent.com/googlefonts/noto-emoji/master/png/512/emoji_u{hex_code}.png"

    async def create_emoji_image(self, target_emoji):
        try:
            frame_data = await self.get_frame_from_telegram()
            if not frame_data: return None
            
            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            
            # Fetch Emoji
            emoji_url = self.get_emoji_image_url(target_emoji)
            emoji_resp = requests.get(emoji_url, timeout=5)
            emoji_img = Image.open(io.BytesIO(emoji_resp.content)).convert("RGBA")
            
            # Resize and Center
            emoji_img = emoji_img.resize((250, 250), Image.Resampling.LANCZOS)
            width, height = img.size
            ew, eh = emoji_img.size
            x, y = (width - ew) // 2, (height - eh) // 2
            
            # Paste
            img.alpha_composite(emoji_img, (x, y))
            
            # Save to buffer
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Image Creation Error: {e}")
            return None

    # --- TRIVIA API HELPER ---
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
        # Fallback question
        return {"q": "Which planet is known as the Red Planet?", "options": ["Mars", "Earth", "Venus"], "a": "Mars"}

    # --- CLEANUP LOGIC (15m Timeout -> 20m Delete) ---
    async def auto_delete_task(self, chat_id, quiz_msg_id, correct_answer):
        """
        1. Wait 15 mins (900s). Check for winner. If no winner, send Time Out.
        2. Wait 5 mins (300s).
        3. Delete Quiz, Timeout Msg, and Congrats Msg.
        """
        
        # --- PHASE 1: 15 MINUTES (GAMEPLAY) ---
        await asyncio.sleep(900) 
        
        timeout_msg_id = None
        if quiz_msg_id in self.active_games:
            game = self.active_games[quiz_msg_id]
            
            # Agar abhi tak koi nahi jita
            if not game.get('winner'):
                try:
                    text = f"⏰ <b>TIME OUT!</b>\n\nSahi jawab <b>{correct_answer}</b> tha. Koi bhi ise dhund nahi paaya! ⚡"
                    sent_msg = await self.application.bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        reply_to_message_id=quiz_msg_id, 
                        parse_mode='HTML'
                    )
                    timeout_msg_id = sent_msg.message_id
                except Exception as e:
                    logger.error(f"Timeout Msg Error: {e}")

        # --- PHASE 2: 5 MINUTES (BUFFER) ---
        await asyncio.sleep(300) 
        
        # --- PHASE 3: DELETE EVERYTHING ---
        try:
            # 1. Main Quiz/Photo delete
            await self.application.bot.delete_message(chat_id=chat_id, message_id=quiz_msg_id)
            
            # 2. Timeout msg delete (agar bheja tha)
            if timeout_msg_id:
                await self.application.bot.delete_message(chat_id=chat_id, message_id=timeout_msg_id)
            
            # 3. Congrats msg delete (agar koi jita tha)
            if quiz_msg_id in self.active_games and self.active_games[quiz_msg_id].get('congrats_id'):
                await self.application.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=self.active_games[quiz_msg_id]['congrats_id']
                )
            
            # Memory clear
            if quiz_msg_id in self.active_games:
                del self.active_games[quiz_msg_id]
            
            logger.info(f"🗑 Cleaned up game in chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Cleanup Error (Check Admin Rights): {e}")

    # --- BUTTON HANDLER ---
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        msg_id = query.message.message_id
        chat_id = query.message.chat_id
        data = query.data.split(":") # format: trivia:yes/no:answer

        if msg_id not in self.active_games:
            await query.answer("Ye game khatam ho chuka hai!", show_alert=True)
            return

        game = self.active_games[msg_id]
        
        # Agar pehle hi koi jeet chuka hai
        if game.get('winner'):
            await query.answer(f"Arre! {game['winner_name']} ne pehle hi dhund liya!", show_alert=True)
            return

        # Correct Answer Logic
        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer("Sahi Jawab! 🔥", show_alert=False)
            
            # Short 1-line congrats message
            congrats_msg = f"🏆 {user.mention_html()} ne <b>{data[2]}</b> ko {time_taken}s mein dhund nikaala!"
            
            try:
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id, 
                    text=congrats_msg, 
                    reply_to_message_id=msg_id, 
                    parse_mode='HTML'
                )
                
                # Store ID to delete it later
                game['congrats_id'] = sent_msg.message_id
                
                # Fire Reaction
                try:
                    await context.bot.set_message_reaction(
                        chat_id=chat_id, 
                        message_id=sent_msg.message_id, 
                        reaction=[{"type": "emoji", "emoji": "🔥"}]
                    )
                except: pass
            except: pass
            
        # Wrong Answer Logic
        else:
            await query.answer("Galat! ❌ Phir se try karo.", show_alert=False)

    # --- MAIN LOOP ---
    async def start_loop(self):
        logger.info("🔥 Ultimate Trivia Loop Started!")
        await asyncio.sleep(10) # Initial buffer
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                # 30 mins wait logic is at the end
                
                if self.current_mode == "emoji":
                    # --- EMOJI HUNT MODE ---
                    target = random.choice(EMOJI_POOL)
                    photo = await self.create_emoji_image(target)
                    
                    if photo:
                        # 8 Random distinct distractions + 1 Target
                        distractions = random.sample([e for e in EMOJI_POOL if e != target], 8)
                        grid_opts = distractions + [target]
                        random.shuffle(grid_opts)
                        
                        # 3x3 Grid Construction
                        kb = []
                        row = []
                        for e in grid_opts:
                            # Callback data: trivia:yes:🍎 or trivia:no:🚀
                            is_correct = 'yes' if e == target else 'no'
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{is_correct}:{e}"))
                            if len(row) == 3:
                                kb.append(row)
                                row = []
                        
                        # Send to all groups
                        for cid in active_chats:
                            try:
                                photo.seek(0)
                                msg = await self.application.bot.send_photo(
                                    cid, 
                                    photo=photo, 
                                    caption="🖼 <b>EMOJI HUNT!</b>\nTap photo to reveal and find the emoji!", 
                                    reply_markup=InlineKeyboardMarkup(kb), 
                                    parse_mode='HTML',
                                    has_spoiler=True # Blurred photo feature
                                )
                                # Save game state
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                                
                                # Start Independent Timer for this chat
                                asyncio.create_task(self.auto_delete_task(cid, msg.message_id, target))
                                
                            except Exception as e:
                                if "Forbidden" in str(e) or "Chat not found" in str(e):
                                    self.known_users.discard(cid)

                    self.current_mode = "trivia"

                else:
                    # --- TRIVIA QUIZ MODE ---
                    q = self.get_api_question()
                    
                    # Button grid for text quiz (Vertical list or 2x2, here doing vertical for text clarity)
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    
                    for cid in active_chats:
                        try:
                            msg = await self.application.bot.send_message(
                                cid, 
                                f"🧩 <b>TRIVIA QUIZ</b>\n\n{q['q']}", 
                                reply_markup=InlineKeyboardMarkup(kb), 
                                parse_mode='HTML'
                            )
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                            
                            # Start Independent Timer
                            asyncio.create_task(self.auto_delete_task(cid, msg.message_id, q['a']))
                            
                        except Exception as e:
                            if "Forbidden" in str(e): self.known_users.discard(cid)

                    self.current_mode = "emoji"

            except Exception as e: 
                logger.error(f"Global Loop Error: {e}")
            
            # Wait 30 minutes before next game
            await asyncio.sleep(1800)
