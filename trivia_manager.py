import asyncio, random, logging, html, time, io, requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application

logger = logging.getLogger(__name__)

# --- CONFIG: 50+ Emojis and Frame ---
EMOJI_POOL = [
    "🍎", "🚀", "💎", "🐱", "🎸", "🍕", "🌈", "🔥", "🦄", "🍦", "⚽", "🎮", "🔔", "🎁", "🧿", "🍀", "🍩", "🍹", "🎈", "🧸",
    "🍍", "🦚", "🎲", "🛸", "🍟", " popcorn", "🛹", "🎯", "🎭", "🎬", "🎨", "🧩", "🎤", "🎧", "🎷", "🎸", "🎺", "🎻", "🎬", "🏹",
    "🌋", "🛰", "🎡", "🎢", "🚢", "🛫", "🪐", "🌟", "🌙", "🥨", "🥓", "🍔", "🍣", "🌮", "🍭", "🍫", "🍯", "🥂", "🥃", "🧉"
]

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
        hex_code = "-".join([f"{ord(c):x}" for c in emoji])
        return f"https://raw.githubusercontent.com/googlefonts/noto-emoji/master/png/512/emoji_u{hex_code}.png"

    async def create_emoji_image(self, target_emoji):
        try:
            frame_data = await self.get_frame_from_telegram()
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
            logger.error(f"Image Error: {e}")
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
        chat_id = query.message.chat_id
        data = query.data.split(":") 

        if msg_id not in self.active_games:
            await query.answer("Khel khatam ho gaya!", show_alert=True)
            return

        game = self.active_games[msg_id]

        if game.get('winner'):
            await query.answer(f"Already guessed by {game['winner_name']}!", show_alert=True)
            return

        if data[1] == "yes":
            game['winner'] = user.id
            game['winner_name'] = user.first_name
            time_taken = round(time.time() - game['start_time'], 2)
            
            await query.answer("Correct! 🔥", show_alert=False)
            
            # Short 1-line congrats message
            congrats_msg = f"🏆 {user.mention_html()} ne <b>{data[2]}</b> ko {time_taken}s mein dhund nikaala!"
            
            try:
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=congrats_msg,
                    reply_to_message_id=msg_id,
                    parse_mode='HTML'
                )
                
                # Auto-reaction on congrats message
                try:
                    await context.bot.set_message_reaction(
                        chat_id=chat_id,
                        message_id=sent_msg.message_id,
                        reaction=[{"type": "emoji", "emoji": "🔥"}]
                    )
                except: pass
            except: pass

        else:
            await query.answer("Galat! Phir se try karo.", show_alert=False)

    async def start_loop(self):
        logger.info("Advanced Trivia Loop Started!")
        await asyncio.sleep(10)
        
        while True:
            try:
                active_chats = [c for c in list(self.known_users) if str(c).startswith("-")]
                expiry = time.time() + 900 
                
                if self.current_mode == "emoji":
                    target = random.choice(EMOJI_POOL)
                    photo = await self.create_emoji_image(target)
                    
                    if photo:
                        # Sirf 9 buttons (3x3 grid) - random selection every time
                        random_opts = random.sample([e for e in EMOJI_POOL if e != target], 8)
                        grid_opts = random_opts + [target]
                        random.shuffle(grid_opts)
                        
                        kb = []
                        row = []
                        for e in grid_opts:
                            row.append(InlineKeyboardButton(e, callback_data=f"trivia:{'yes' if e==target else 'no'}:{e}"))
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
                                    has_spoiler=True # Blurred photo
                                )
                                self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                            except: pass
                    self.current_mode = "trivia"
                else:
                    q = self.get_api_question()
                    kb = [[InlineKeyboardButton(o, callback_data=f"trivia:{'yes' if o==q['a'] else 'no'}:{o}")] for o in q['options']]
                    for cid in active_chats:
                        try:
                            msg = await self.application.bot.send_message(cid, f"🧩 <b>TRIVIA QUIZ</b>\n\n{q['q']}", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                            self.active_games[msg.message_id] = {'start_time': time.time(), 'expires_at': expiry, 'winner': None}
                        except: pass
                    self.current_mode = "emoji"

            except Exception as e: logger.error(f"Loop Error: {e}")
            await asyncio.sleep(1800) # 30 min wait
