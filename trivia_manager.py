import asyncio
import random
import logging
import html
import time
import io
import requests
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji
from telegram.ext import ContextTypes, Application

# Enable Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---

# 1. Emoji Pool
EMOJI_POOL = [
    "🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸",
    "🍍", "🦚", "🎲", "🛸", "🍟", "🍿", "🛹", "🎯", "🎭", "🎬", "🎨", "🧩", "🎤", "🎧", "🎷", "🎸", "🎺", "🎻", "🎬", "🏹",
    "🌋", "🛰", "🎡", "🎢", "🚢", "🛫", "🪐", "🌟", "🌙", "🥨", "🥓", "🍔", "🍣", "🌮", "🍭", "🍫", "🍯", "🥂", "🥃", "🧉"
]

# 2. Reactions for Winners
REACTION_POOL = ["❤️", "🔥", "🎉", "👏", "🤩", "👀", "🏆"]

# 3. Neon Colors for Word Game
NEON_COLORS = ["#FF00FF", "#00FFFF", "#00FF00", "#FFFF00", "#FF0099", "#9D00FF", "#FFA500"]

# 4. FILE IDs (Replace with your actual Telegram File IDs)
FRAME_FILE_ID = "AgACAgUAAyEFAATHcBuEAAICvGlwh5iWzzYJvgSuOE-EPOtjTa7XAAJnDWsb5FOJVwFVYd7UN29_AQADAgADeQADOAQ" 
WORD_FRAME_FILE_ID = "YOUR_WORD_FRAME_FILE_ID_HERE" # <--- PASTE YOUR WORD GAME PHOTO ID HERE

class TriviaGame:
    def __init__(self, application: Application, known_users_list):
        self.application = application
        self.known_users = known_users_list
        # Cycle: emoji -> trivia -> word -> emoji...
        self.game_modes = ["emoji", "trivia", "word"]
        self.current_mode_index = 0
        self.active_games = {} 
        self.cached_frame = None
        self.cached_word_frame = None
        self.custom_font = None

    # --- HELPER: GET TELEGRAM FILE ---
    async def get_cached_file(self, file_id, type_key):
        """Generic function to cache background images from Telegram"""
        target_cache = self.cached_frame if type_key == "emoji" else self.cached_word_frame
        
        if target_cache is None:
            try:
                # If user hasn't set the Word ID yet, use the Emoji one as fallback
                if file_id == "YOUR_WORD_FRAME_FILE_ID_HERE":
                    file_id = FRAME_FILE_ID
                    
                file = await self.application.bot.get_file(file_id)
                photo_bytes = await file.download_as_bytearray()
                
                if type_key == "emoji":
                    self.cached_frame = bytes(photo_bytes)
                    target_cache = self.cached_frame
                else:
                    self.cached_word_frame = bytes(photo_bytes)
                    target_cache = self.cached_word_frame
                    
                logger.info(f"✅ {type_key.upper()} Frame Cached!")
            except Exception as e:
                logger.error(f"❌ Frame Error ({type_key}): {e}")
        return target_cache

    # --- HELPER: LOAD FONT ---
    def get_font(self, size=60):
        """Downloads a bold font from Google Fonts for the Neon look"""
        if self.custom_font is None:
            try:
                # Using 'Lilita One' - a nice thick font for games
                font_url = "https://github.com/google/fonts/raw/main/ofl/lilitaone/LilitaOne-Regular.ttf"
                resp = requests.get(font_url, timeout=10)
                self.custom_font = io.BytesIO(resp.content)
            except:
                logger.error("Failed to download font, using default")
                return None # Will trigger default load
        
        try:
            return ImageFont.truetype(self.custom_font, size)
        except:
            return ImageFont.load_default()

    # --- IMAGE GENERATOR: EMOJI ---
    def get_emoji_image_url(self, emoji):
        hex_code = "-".join([f"{ord(c):x}" for c in emoji])
        return f"https://raw.githubusercontent.com/googlefonts/noto-emoji/master/png/512/emoji_u{hex_code}.png"

    async def create_emoji_image(self, target_emoji):
        try:
            frame_data = await self.get_cached_file(FRAME_FILE_ID, "emoji")
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
            
            img.alpha_composite(emoji_img, (x, y))
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Emoji Image Error: {e}")
            return None

    # --- IMAGE GENERATOR: WORD (NEON) ---
    async def create_word_image(self, text):
        try:
            frame_data = await self.get_cached_file(WORD_FRAME_FILE_ID, "word")
            if not frame_data: return None

            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            width, height = img.size

            # Font setup
            font_size = 80 if len(text) < 6 else 60
            font = self.get_font(font_size)
            
            # Text Centering
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x, y = (width - text_w) / 2, (height - text_h) / 2

            # Neon Effect (Draw thick outline + center)
            neon_color = random.choice(NEON_COLORS)
            
            # 1. Dark Shadow
            draw.text((x+3, y+3), text, font=font, fill="black")
            
            # 2. Main Color
            draw.text((x, y), text, font=font, fill=neon_color)

            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Word Image Error: {e}")
            return None

    # --- API HELPERS ---
    def get_trivia_question(self):
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
        return {"q": "Which planet is known as the Red Planet?", "options": ["Mars", "Earth", "Venus"], "a": "Mars"}

    def get_word_data(self):
        try:
            # Get 3 random words
            url = "https://random-word-api.herokuapp.com/word?number=3&length=5"
            words = requests.get(url, timeout=5).json()
            target = words[0].upper()
            
            # Scramble the target
            temp_list = list(target)
            random.shuffle(temp_list)
            scrambled = "".join(temp_list)
            
            # Options (Target + 2 others)
            options = [w.upper() for w in words]
            random.shuffle(options)
            
            return {"scrambled": scrambled, "correct": target, "options": options}
        except Exception as e:
            logger.error(f"Word API Error: {e}")
            # Fallback
            return {"scrambled": "ELPPA", "correct": "APPLE", "options": ["APPLE", "GRAPE", "MANGO"]}

    # --- CLEANUP LOGIC ---
    async def auto_delete_task(self, chat_id, quiz_msg_id, correct_answer):
        # 15 Minutes Play Time
        await asyncio.sleep(900) 
        
        timeout_msg_id = None
        if quiz_msg_id in self.active_games:
            game = self.active_games[quiz_msg_id]
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
                except: pass

        # 5 Minutes Buffer (Total 20 mins from start)
        await asyncio.sleep(300) 
        
        try:
            await self.application.bot.delete_message(chat_id=chat_id, message_id=quiz_msg_id)
            if timeout_msg_id:
                await self.application.bot.delete_message(chat_id=chat_id, message_id=timeout_msg_id)
            
            if quiz_msg_id in self.active_games and self.active_games[quiz_msg_id].get('congrats_id'):
                await self.application.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=self.active_games[quiz_msg_id]['congrats_id']
                )
            
            if quiz_msg_id in self.active_games:
                del self.active_games[quiz_msg_id]
            
        except Exception as e:
            logger.error(f"Cleanup Error: {e}")

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
            await query.answer(f"Oops! {game['winner_name']} already won!", show_alert=True)
            return

        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer("Correct! 🔥", show_alert=False)
            
            congrats_msg = f"🏆 {user.mention_html()} guessed <b>{data[2]}</b> in {time_taken}s!"
            
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
                    await asyncio.sleep(0.2) 
                    
                    # Use ReactionTypeEmoji() instead of raw dict
                    await context.bot.set_message_reaction(
                        chat_id=chat_id, 
                        message_id=sent_msg.message_id, 
                        reaction=[ReactionTypeEmoji(chosen_emoji)],
                        is_big=False
                    )
                except Exception as react_err:
                    logger.error(f"❌ Reaction Failed: {react_err}")

            except Exception as e:
                logger.error(f"Post-Win Error: {e}")
            
        else:
            await query.answer("Wrong! ❌ Try again.", show_alert=False)
   
    # --- TIME CALCULATION ---
    def get_seconds_until_next_slot(self):
        now = datetime.now()
        if now.minute < 30:
            target_minute = 30
            next_hour = now.hour
        else:
            target_minute = 0
            next_hour = (now.hour + 1) % 24
            
        if target_minute == 0 and next_hour == 0:
            target_time = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            target_time = now.replace(hour=next_hour, minute=target_minute, second=0, microsecond=0)
            
        return (target_time - now).total_seconds()

    # --- MAIN LOOP ---
    async def start_loop(self):
        logger.info("🔥 Ultimate Game Loop Started! (Emoji -> Trivia -> Word)")
        
        while True:
            sleep_seconds = self.get_seconds_until_next_slot()
            if sleep_seconds < 10: sleep_seconds += 1800
                
            logger.info(f"⏳ Sleeping for {int(sleep_seconds)} seconds...")
            await asyncio.sleep(sleep_seconds)

            current_mode = self.game_modes[self.current_mode_index]
            # Advance mode for next time
            self.current_mode_index = (self.current_mode_index + 1) % len(self.game_modes)

            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                logger.info(f"🚀 Starting Mode: {current_mode.upper()}")

                # --- 1. EMOJI HUNT ---
                if current_mode == "emoji":
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
                                await asyncio.sleep(0.5) 
                            except: pass

                # --- 2. TRIVIA QUIZ ---
                elif current_mode == "trivia":
                    q = self.get_trivia_question()
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
                            await asyncio.sleep(0.5)
                        except: pass

                # --- 3. WORD GUESSER (NEW) ---
                elif current_mode == "word":
                    data = self.get_word_data()
                    photo = await self.create_word_image(data['scrambled'])
                    
                    if photo:
                        kb = []
                        for opt in data['options']:
                            is_correct = 'yes' if opt == data['correct'] else 'no'
                            # Store truncated data if word is long to avoid limits
                            kb.append([InlineKeyboardButton(opt, callback_data=f"trivia:{is_correct}:{data['correct']}")])
                        
                        for cid in active_chats:
                            try:
                                photo.seek(0)
                                msg = await self.application.bot.send_photo(
                                    cid,
                                    photo=photo,
                                    caption=f"🔠 <b>UNSCRAMBLE THE WORD!</b>\n\nI have scrambled a word in Neon.\nTap the correct option below! 👇",
                                    reply_markup=InlineKeyboardMarkup(kb),
                                    parse_mode='HTML'
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                                asyncio.create_task(self.auto_delete_task(cid, msg.message_id, data['correct']))
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                logger.error(f"Word Send Error: {e}")

            except Exception as e: 
                logger.error(f"Global Loop Error: {e}")
