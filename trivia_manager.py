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
from telegram.ext import ContextTypes, Application, CommandHandler # CommandHandler add kiya

# Enable Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---

EMOJI_POOL = [
    "🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸",
    "🍍", "🦚", "🎲", "🛸", "🍟", "🍿", "🛹", "🎯", "🎭", "🎬", "🎨", "🧩", "🎤", "🎧", "🎷", "🎸", "🎺", "🎻", "🎬", "🏹",
    "🌋", "🛰", "🎡", "🎢", "🚢", "🛫", "🪐", "🌟", "🌙", "🥨", "🥓", "🍔", "🍣", "🌮", "🍭", "🍫", "🍯", "🥂", "🥃", "🧉"
    "🦙", "☠️", "👹", "☃️", "💌", "💅", "🧟", "💐", "🏖️", "🌀", "🌍", "🐱", "🐼", "🐲", "🐘", "🥝", "🫘", "🥙", "🍰", "🥂"
    "🚗", "🚁", "⛩️", "🗺️", "🎎", "🪔", "🪅", "🎄", "🥋", "📸", "📺", "📱", "👘", "💍", "📓", "🔮", "🎵", "🔒", "💣", "🔏"
]

REACTION_POOL = ["❤️", "🔥", "🎉", "👏", "🤩", "👀", "🏆"]
NEON_COLORS = ["#FF00FF", "#00FFFF", "#00FF00", "#FFFF00", "#FF0099", "#9D00FF", "#FFA500"]

FRAME_FILE_ID = "AgACAgUAAyEFAATHcBuEAAICvGlwh5iWzzYJvgSuOE-EPOtjTa7XAAJnDWsb5FOJVwFVYd7UN29_AQADAgADeQADOAQ" 
WORD_FRAME_FILE_ID = "AgACAgUAAxkBAAIY8Wl4kB1kYInYopFFqOUX3mrFrYA0AAI0D2sb5MDAVzJAQU3iWcSqAQADAgADdwADOAQ" 

# ### NEW: Footer Text constant
GAME_FOOTER = "\n\n⚙️ <i>Want to turn off this feature? Use /triviagame</i>"
class TriviaGame:
    def __init__(self, application, known_users, mongo_db=None):
        self.application = application
        self.known_users = known_users
        self.db = mongo_db  # Ye SummaryManager.db hi hai
        self.disabled_chats = set()
        self.active_games = {}
        
        # Collection Setup
        self.collection = None
        if self.db is not None:
            # Note: Database 'laila_summaries' ke andar ek nayi table 'trivia_settings' banegi
            self.collection = self.db["trivia_settings"]
            # Startup par async load task chalana
            asyncio.create_task(self.load_disabled_chats())
        
        # Caches & Modes
        self.cached_frame = None
        self.cached_word_frame = None
        self.custom_font = None
        self.game_modes = ["emoji", "trivia", "word"]
        self.current_mode_index = 0
        
        # Handler setup
        self.application.add_handler(CommandHandler("triviagame", self.toggle_game_status))
        logger.info("✅ TriviaGame Module Initialized with MongoDB")

    async def load_disabled_chats(self):
        """Async MongoDB se data load karega (Motor style)"""
        if self.collection is None: return
        try:
            # Motor me cursor use hota hai
            cursor = self.collection.find({})
            async for doc in cursor:
                self.disabled_chats.add(doc['chat_id'])
            logger.info(f"✅ Loaded {len(self.disabled_chats)} disabled chats from Mongo.")
        except Exception as e:
            logger.error(f"❌ MongoDB Load Error: {e}")

    async def toggle_game_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if self.collection is None:
            await update.message.reply_text("⚠️ Database not connected!")
            return
            
        try:
            if chat_id in self.disabled_chats:
                self.disabled_chats.remove(chat_id)
                await self.collection.delete_one({"chat_id": chat_id})
                await update.message.reply_text("✅ <b>Trivia Game Enabled!</b> Game ab is group me chalega.", parse_mode='HTML')
            else:
                self.disabled_chats.add(chat_id)
                await self.collection.update_one(
                    {"chat_id": chat_id},
                    {"$set": {"chat_id": chat_id, "disabled_at": datetime.now()}},
                    upsert=True
                )
                await update.message.reply_text("❌ <b>Trivia Game Disabled!</b> Ab is group me game nahi aayega.", parse_mode='HTML')
        except Exception as e:
            logger.error(f"MongoDB Update Error: {e}")
            await update.message.reply_text("⚠️ Database Error.")

    # ... get_cached_file aur baki functions wahi rahenge ...



    

    

    # ... (Baaki saara code EXACTLY same rahega: get_cached_file, start_loop, images, etc.) ...
    
    # --- HELPER: GET TELEGRAM FILE ---
    async def get_cached_file(self, file_id, type_key):
        target_cache = self.cached_frame if type_key == "emoji" else self.cached_word_frame
        if target_cache is None:
            try:
                file = await self.application.bot.get_file(file_id)
                photo_bytes = await file.download_as_bytearray()
                if type_key == "emoji":
                    self.cached_frame = bytes(photo_bytes)
                    target_cache = self.cached_frame
                else:
                    self.cached_word_frame = bytes(photo_bytes)
                    target_cache = self.cached_word_frame
            except Exception as e:
                logger.error(f"❌ Frame Error ({type_key}): {e}")
        return target_cache

    # ... (Please include get_font, create_emoji_ima

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





    # --- HELPER: LOAD FONT ---
    def get_font(self, size=60):
        if self.custom_font is None:
            try:
                font_url = "https://github.com/google/fonts/raw/main/ofl/lilitaone/LilitaOne-Regular.ttf"
                resp = requests.get(font_url, timeout=10)
                self.custom_font = io.BytesIO(resp.content)
            except:
                return ImageFont.load_default()
        
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
            
            emoji_url = self.get_emoji_image_url(target_emoji)
            emoji_resp = requests.get(emoji_url, timeout=5)
            emoji_img = Image.open(io.BytesIO(emoji_resp.content)).convert("RGBA")
            
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

    # --- IMAGE GENERATOR: WORD (NEON) --
    async def create_word_image(self, text):
        try:
            frame_data = await self.get_cached_file(WORD_FRAME_FILE_ID, "word")
            if not frame_data: return None
            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            width, height = img.size

        # 1. Define maximum width (leaving some padding on sides)
            max_width = width * 0.90  
        
        # 2. Start with a large font size
            font_size = 250 
            font = self.get_font(font_size)
        
        # 3. Dynamic Scaling Loop
        # Reduce font size until the text width fits inside max_width
            while font_size > 10: # Minimum font size safety
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            
                if text_w <= max_width:
                # Also check if height fits to be safe
                    if text_h < height * 0.8: 
                        break
            
            # Reduce size and try again
                font_size -= 10 
                font = self.get_font(font_size)

        # Recalculate bbox one last time with the final font
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        
        # 4. Calculate Center Logic
        # (width - text_w) / 2 is the margin. 
        # We subtract bbox[0] to account for font offsets.
            x = (width - text_w) / 2 - bbox[0]
            y = (height - text_h) / 2 - bbox[1]

            neon_color = random.choice(NEON_COLORS)
         
        # Draw Shadow/Stroke
            draw.text((x+4, y+4), text, font=font, fill="black") 
        # Draw Main Text
            draw.text((x, y), text, font=font, fill=neon_color)

            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Word Image Error: {e}")
            return None
    

    '''
    async def create_word_image(self, text):
        try:
            frame_data = await self.get_cached_file(WORD_FRAME_FILE_ID, "word")
            if not frame_data: return None

            img = Image.open(io.BytesIO(frame_data)).convert("RGBA")
            draw = ImageDraw.Draw(img)
            width, height = img.size

            font_size = 250 if len(text) < 6 else 180
            font = self.get_font(font_size)
            
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x, y = (width - text_w) / 2, (height - text_h) / 2

            neon_color = random.choice(NEON_COLORS)
            draw.text((x+4, y+4), text, font=font, fill="black") 
            draw.text((x, y), text, font=font, fill=neon_color)

            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr
        except Exception as e:
            logger.error(f"Word Image Error: {e}")
            return None

            '''

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
            url = "https://random-word-api.herokuapp.com/word?number=3&length=5"
            words = requests.get(url, timeout=5).json()
            target = words[0].upper()
            temp_list = list(target)
            random.shuffle(temp_list)
            scrambled = "".join(temp_list)
            options = [w.upper() for w in words]
            random.shuffle(options)
            return {"scrambled": scrambled, "correct": target, "options": options}
        except Exception:
            return {"scrambled": "ELPPA", "correct": "APPLE", "options": ["APPLE", "GRAPE", "MANGO"]}

    # --- CLEANUP & WARNING LOGIC ---
    async def auto_delete_task(self, chat_id, quiz_msg_id, correct_answer):
        warning_msg_ids = []

        await asyncio.sleep(300) 
        if quiz_msg_id in self.active_games and not self.active_games[quiz_msg_id].get('winner'):
            try:
                w_msg = await self.application.bot.send_message(
                    chat_id=chat_id,
                    text="⏳ <b>10 Minutes Remaining!</b>",
                    reply_to_message_id=quiz_msg_id,
                    parse_mode='HTML'
                )
                warning_msg_ids.append(w_msg.message_id)
            except: pass

        await asyncio.sleep(300)
        if quiz_msg_id in self.active_games and not self.active_games[quiz_msg_id].get('winner'):
            try:
                w_msg = await self.application.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>Hurry Up! Only 5 Minutes Left!</b> ⚡",
                    reply_to_message_id=quiz_msg_id,
                    parse_mode='HTML'
                )
                warning_msg_ids.append(w_msg.message_id)
            except: pass

        await asyncio.sleep(300)
        
        timeout_msg_id = None
        if quiz_msg_id in self.active_games:
            game = self.active_games[quiz_msg_id]
            if not game.get('winner'):
                try:
                    text = f"⏰ <b>TIME OUT!</b>\n\nThe correct answer was <b>{correct_answer}</b>. Nobody found it! 😢"
                    sent_msg = await self.application.bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        reply_to_message_id=quiz_msg_id, 
                        parse_mode='HTML'
                    )
                    timeout_msg_id = sent_msg.message_id
                except: pass

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

            for wid in warning_msg_ids:
                try:
                    await self.application.bot.delete_message(chat_id=chat_id, message_id=wid)
                except: pass
            
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
                
                try:
                    chosen_emoji = random.choice(REACTION_POOL)
                    await asyncio.sleep(0.5) 
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
            self.current_mode_index = (self.current_mode_index + 1) % len(self.game_modes)

            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                logger.info(f"🚀 Starting Mode: {current_mode.upper()}")

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
                            # ### NEW: Check agar chat Disabled hai to Skip karo
                            if cid in self.disabled_chats: continue

                            try:
                                photo.seek(0)
                                # ### NEW: Caption me Footer add kiya
                                msg = await self.application.bot.send_photo(
                                    cid, photo=photo, 
                                    caption=f"🖼 <b>EMOJI HUNT!</b>\nTap photo to reveal and find the emoji!{GAME_FOOTER}", 
                                    reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML', has_spoiler=True
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                                asyncio.create_task(self.auto_delete_task(cid, msg.message_id, target))
                            except: pass

                elif current_mode == "trivia":
                    q = self.get_trivia_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    for cid in active_chats:
                         # ### NEW: Check agar chat Disabled hai to Skip karo
                        if cid in self.disabled_chats: continue

                        try:
                            # ### NEW: Text me Footer add kiya
                            msg = await self.application.bot.send_message(
                                cid, f"🧩 <b>TRIVIA QUIZ</b>\n\n{q['q']}{GAME_FOOTER}", 
                                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
                            )
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                            asyncio.create_task(self.auto_delete_task(cid, msg.message_id, q['a']))
                        except: pass

                elif current_mode == "word":
                    data = self.get_word_data()
                    photo = await self.create_word_image(data['scrambled'])
                    if photo:
                        kb = []
                        for opt in data['options']:
                            is_correct = 'yes' if opt == data['correct'] else 'no'
                            kb.append([InlineKeyboardButton(opt, callback_data=f"trivia:{is_correct}:{data['correct']}")])
                        
                        for cid in active_chats:
                             # ### NEW: Check agar chat Disabled hai to Skip karo
                            if cid in self.disabled_chats: continue

                            try:
                                photo.seek(0)
                                # ### NEW: Caption me Footer add kiya
                                msg = await self.application.bot.send_photo(
                                    cid, photo=photo,
                                    caption=f"🔠 <b>UNSCRAMBLE THE WORD!</b>\nTap the correct option below! 👇{GAME_FOOTER}",
                                    reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML',has_spoiler=True  
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'winner': None}
                                asyncio.create_task(self.auto_delete_task(cid, msg.message_id, data['correct']))
                            except: pass

            except Exception as e: 
                logger.error(f"Global Loop Error: {e}")
