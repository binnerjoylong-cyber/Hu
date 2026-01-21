import asyncio
import random
import logging
import html
import time
import io
import requests
from datetime import datetime, timedelta
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

# Random Reactions for the Congratulations Message
REACTION_POOL = ["❤️", "🔥", "🎉", "👏", "🤩", "👀", "🏆"]

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

    # --- CLEANUP LOGIC ---
    async def auto_delete_task(self, chat_id, quiz_msg_id, correct_answer):
        # --- PHASE 1: 15 MINUTES (GAMEPLAY) ---
        await asyncio.sleep(900) 
        
        timeout_msg_id = None
        if quiz_msg_id in self.active_games:
            game = self.active_games[quiz_msg_id]
            
            # If no winner yet
            if not game.get('winner'):
                try:
                    text = f"⏰ <b>TIME OUT!</b>\n\nThe correct answer was <b>{correct_answer}</b>. Nobody found it! ⚡"
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
            
            # 2. Timeout msg delete (if sent)
            if timeout_msg_id:
                await self.application.bot.delete_message(chat_id=chat_id, message_id=timeout_msg_id)
            
            # 3. Congrats msg delete (if won)
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
        data = query.data.split(":") 

        if msg_id not in self.active_games:
            await query.answer("This game has already ended!", show_alert=True)
            return

        game = self.active_games[msg_id]
        
        if game.get('winner'):
            await query.answer(f"Oops! {game['winner_name']} already found it!", show_alert=True)
            return

        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer("Correct Answer! 🔥", show_alert=False)
            
            congrats_msg = f"🏆 {user.mention_html()} found <b>{data[2]}</b> in {time_taken}s!"
            
            try:
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id, 
                    text=congrats_msg, 
                    reply_to_message_id=msg_id, 
                    parse_mode='HTML'
                )
                
                game['congrats_id'] = sent_msg.message_id
                
                # --- FIXED REACTION LOGIC ---
                try:
                    chosen_emoji = random.choice(REACTION_POOL)
                    # We use a delay because sometimes TG doesn't register the message ID immediately
                    await asyncio.sleep(0.2) 
                    
                    await context.bot.set_message_reaction(
                        chat_id=chat_id, 
                        message_id=sent_msg.message_id, 
                        reaction=[{"type": "emoji", "emoji": chosen_emoji}],
                        is_big=False
                    )
                    logger.info(f"✅ Reaction {chosen_emoji} added to msg {sent_msg.message_id}")
                except Exception as react_err:
                    logger.error(f"❌ Reaction Failed: {react_err}")

            except Exception as e:
                logger.error(f"Post-Win Error: {e}")
            
        else:
            await query.answer("Wrong! ❌ Try again.", show_alert=False)
   
    # --- TIME CALCULATION FOR :00 AND :30 ---
    def get_seconds_until_next_slot(self):
        """Calculates seconds remaining until the next HH:00 or HH:30"""
        now = datetime.now()
        
        # Determine next target minute (0 or 30)
        if now.minute < 30:
            target_minute = 30
            next_hour = now.hour
        else:
            target_minute = 0
            next_hour = (now.hour + 1) % 24
            
        # Create target datetime object
        if target_minute == 0 and next_hour == 0:
            # Handle midnight crossover
            target_time = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            target_time = now.replace(hour=next_hour, minute=target_minute, second=0, microsecond=0)
            
        # Calculate difference
        delta = target_time - now
        return delta.total_seconds()

    # --- MAIN LOOP ---
    async def start_loop(self):
        logger.info("🔥 Ultimate Trivia Loop Started! (Synced to IST :00/:30)")
        
        while True:
            # 1. CALCULATE SLEEP TIME FIRST (Precise Timing)
            sleep_seconds = self.get_seconds_until_next_slot()
            
            # If we are too close (e.g., < 10 seconds) to the slot, wait for the *next* one to avoid double posting
            if sleep_seconds < 10:
                sleep_seconds += 1800 # Add 30 mins
                
            logger.info(f"⏳ Sleeping for {int(sleep_seconds)} seconds until next scheduled slot...")
            await asyncio.sleep(sleep_seconds)

            # 2. START SENDING QUIZ
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                logger.info(f"🚀 Sending Game to {len(active_chats)} chats...")

                if self.current_mode == "emoji":
                    # --- EMOJI HUNT MODE ---
                    target = random.choice(EMOJI_POOL)
                    photo = await self.create_emoji_image(target)
                    
                    if photo:
                        distractions = random.sample([e for e in EMOJI_POOL if e != target], 8)
                        grid_opts = distractions + [target]
                        random.shuffle(grid_opts)
                        
                        kb = []
                        row = []
                        for e in grid_opts:
                            is_correct = 'yes' if e == target else 'no'
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{is_correct}:{e}"))
                            if len(row) == 3:
                                kb.append(row)
                                row = []
                        
                        for cid in active_chats:
                            try:
                                photo.seek(0)
                                msg = await self.application.bot.send_photo(
                                    cid, 
                                    photo=photo, 
                                    caption="🖼 <b>EMOJI HUNT!</b>\nTap photo to reveal and find the emoji!", 
                                    reply_markup=InlineKeyboardMarkup(kb), 
                                    parse_mode='HTML',
                                    has_spoiler=True
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                                asyncio.create_task(self.auto_delete_task(cid, msg.message_id, target))
                                # Small delay to prevent flood limits
                                await asyncio.sleep(0.5) 
                                
                            except Exception as e:
                                if "Forbidden" in str(e) or "Chat not found" in str(e):
                                    self.known_users.discard(cid)

                    self.current_mode = "trivia"

                else:
                    # --- TRIVIA QUIZ MODE ---
                    q = self.get_api_question()
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
                            asyncio.create_task(self.auto_delete_task(cid, msg.message_id, q['a']))
                            # Small delay to prevent flood limits
                            await asyncio.sleep(0.5)

                        except Exception as e:
                            if "Forbidden" in str(e): self.known_users.discard(cid)

                    self.current_mode = "emoji"

            except Exception as e: 
                logger.error(f"Global Loop Error: {e}")
