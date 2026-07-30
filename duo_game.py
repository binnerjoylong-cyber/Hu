import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Global State for Duo Games ---
# Stores game state by lobby ID
active_lobbies = {}
# Maps a user ID to their current lobby ID for quick lookup
user_lobbies = {}

def generate_lobby_id():
    """Generates a random 4-character lobby ID."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def check_win(board, symbol):
    """Checks if a player has won in a 4x4 grid (needs 4 in a row)."""
    # Rows
    for i in range(0, 16, 4):
        if board[i] == board[i+1] == board[i+2] == board[i+3] == symbol: return True
    # Columns
    for i in range(4):
        if board[i] == board[i+4] == board[i+8] == board[i+12] == symbol: return True
    # Diagonals
    if board[0] == board[5] == board[10] == board[15] == symbol: return True
    if board[3] == board[6] == board[9] == board[12] == symbol: return True
    return False

def get_board_keyboard(lobby_id, board):
    """Creates a 4x4 Inline Keyboard."""
    keyboard = []
    for i in range(0, 16, 4):
        row = []
        for j in range(4):
            idx = i + j
            text = "⬜"
            if board[idx] == "X": text = "❌"
            if board[idx] == "O": text = "⭕"
            row.append(InlineKeyboardButton(text, callback_data=f"duo_{lobby_id}_{idx}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🛑 End Game", callback_data=f"duo_{lobby_id}_end")])
    return InlineKeyboardMarkup(keyboard)

# --- Commands ---

async def host_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /host - Creates a new game lobby."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id in user_lobbies:
        await update.message.reply_text("You are already in a game! Use /quitgame first.")
        return

    lobby_id = generate_lobby_id()
    active_lobbies[lobby_id] = {
        'p1': {'id': user.id, 'name': user.first_name, 'chat_id': chat_id},
        'p2': None,
        'board': [" "] * 16,
        'turn': user.id,
        'active': False
    }
    user_lobbies[user.id] = lobby_id

    await update.message.reply_text(
        f"🎮 **Lobby Created!**\n\n"
        f"Your Lobby Code is: `{lobby_id}`\n\n"
        f"Send this code to your friend. They need to type:\n`/join {lobby_id}`\n\n"
        f"_You can chat with them during the game by using_ `/c <message>`",
        parse_mode='Markdown'
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /join <code> - Joins an existing lobby."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id in user_lobbies:
        await update.message.reply_text("You are already in a game! Use /quitgame first.")
        return

    if not context.args:
        await update.message.reply_text("Please provide a lobby code. Example: `/join A1B2`", parse_mode='Markdown')
        return

    lobby_id = context.args[0].upper()

    if lobby_id not in active_lobbies:
        await update.message.reply_text("❌ Invalid or expired Lobby Code.")
        return

    lobby = active_lobbies[lobby_id]

    if lobby['p2'] is not None:
        await update.message.reply_text("❌ This lobby is already full!")
        return
    
    if lobby['p1']['id'] == user.id:
        await update.message.reply_text("❌ You can't join your own lobby as Player 2!")
        return

    # Add Player 2 to lobby
    lobby['p2'] = {'id': user.id, 'name': user.first_name, 'chat_id': chat_id}
    lobby['active'] = True
    user_lobbies[user.id] = lobby_id

    # Notify Both Players
    start_msg = (
        f"⚔️ **GAME STARTED!** ⚔️\n\n"
        f"❌ {lobby['p1']['name']} VS ⭕ {lobby['p2']['name']}\n\n"
        f"🗣️ **In-Game Chat:** Type `/c hello!` to send a message to your opponent!\n\n"
        f"**Current Turn:** {lobby['p1']['name']} (❌)"
    )
    
    markup = get_board_keyboard(lobby_id, lobby['board'])

    # Send board to P1
    await context.bot.send_message(chat_id=lobby['p1']['chat_id'], text=start_msg, reply_markup=markup, parse_mode='Markdown')
    # Send board to P2 (the person who just ran /join)
    await update.message.reply_text(start_msg, reply_markup=markup, parse_mode='Markdown')

async def in_game_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /c <msg> - Sends a message to the opponent."""
    user = update.effective_user
    
    if user.id not in user_lobbies:
        await update.message.reply_text("You are not currently in an active game.")
        return

    if not context.args:
        await update.message.reply_text("Please include a message! Example: `/c Nice move!`", parse_mode='Markdown')
        return

    lobby_id = user_lobbies[user.id]
    lobby = active_lobbies[lobby_id]
    
    if not lobby['active']:
        await update.message.reply_text("Waiting for Player 2 to join before you can chat.")
        return

    message = " ".join(context.args)
    
    # Determine opponent
    opponent = lobby['p2'] if lobby['p1']['id'] == user.id else lobby['p1']
    
    # Send message to opponent
    try:
        await context.bot.send_message(
            chat_id=opponent['chat_id'], 
            text=f"💬 **[{user.first_name}]** says:\n_{message}_",
            parse_mode='Markdown'
        )
        await update.message.reply_text(f"✅ Message sent to {opponent['name']}!")
    except Exception as e:
        await update.message.reply_text("Failed to send message.")

async def quit_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /quitgame - Leaves the current game."""
    user_id = update.effective_user.id
    
    if user_id not in user_lobbies:
        await update.message.reply_text("You aren't in a game right now.")
        return
        
    lobby_id = user_lobbies[user_id]
    lobby = active_lobbies.get(lobby_id)
    
    if lobby:
        opponent = lobby['p2'] if lobby['p1']['id'] == user_id else lobby['p1']
        # Notify opponent if they exist
        if opponent:
             await context.bot.send_message(chat_id=opponent['chat_id'], text="⚠️ Your opponent has left the game. The match is cancelled.")
             if opponent['id'] in user_lobbies:
                 del user_lobbies[opponent['id']]
        del active_lobbies[lobby_id]
        
    del user_lobbies[user_id]
    await update.message.reply_text("You have successfully left the game.")

# --- Callback Handler for Gameplay ---

async def duo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the board button clicks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("_")  # duo_LOBBYID_INDEX

    if len(data) < 3:
        return

    lobby_id = data[1]
    action = data[2]

    if lobby_id not in active_lobbies:
        await query.answer("This game has expired or ended.", show_alert=True)
        try: await query.message.delete()
        except: pass
        return

    lobby = active_lobbies[lobby_id]

    # Verify user is part of the game
    if user_id not in [lobby['p1']['id'], (lobby['p2']['id'] if lobby['p2'] else None)]:
        await query.answer("You are not part of this game! 🚫", show_alert=True)
        return

    if not lobby['active']:
        await query.answer("Waiting for Player 2 to join! ⏳", show_alert=True)
        return

    # Handle End Game
    if action == "end":
        opponent = lobby['p2'] if lobby['p1']['id'] == user_id else lobby['p1']
        await context.bot.send_message(chat_id=opponent['chat_id'], text=f"🛑 {query.from_user.first_name} ended the game.")
        
        # Cleanup
        if lobby['p1']['id'] in user_lobbies: del user_lobbies[lobby['p1']['id']]
        if lobby['p2']['id'] in user_lobbies: del user_lobbies[lobby['p2']['id']]
        del active_lobbies[lobby_id]
        
        await query.answer("Game ended.", show_alert=True)
        await query.edit_message_text(f"🏳️ Game was cancelled by {query.from_user.first_name}.")
        return

    # Handle Move
    idx = int(action)

    if user_id != lobby['turn']:
        await query.answer("It's not your turn! ✋", show_alert=True)
        return

    if lobby['board'][idx] != " ":
        await query.answer("Spot already taken! 🚫", show_alert=True)
        return

    # Apply Move
    symbol = "X" if user_id == lobby['p1']['id'] else "O"
    lobby['board'][idx] = symbol

    # Check Win or Draw
    if check_win(lobby['board'], symbol):
        final_text = f"🎉 **{query.from_user.first_name} ({symbol}) WINS!** 🎉\n\nGame Over."
        markup = get_board_keyboard(lobby_id, lobby['board'])
        
        # Send updates to both
        await context.bot.send_message(chat_id=lobby['p1']['chat_id'], text=final_text, reply_markup=markup, parse_mode='Markdown')
        if lobby['p1']['chat_id'] != lobby['p2']['chat_id']:
            await context.bot.send_message(chat_id=lobby['p2']['chat_id'], text=final_text, reply_markup=markup, parse_mode='Markdown')
        
        # Cleanup
        if lobby['p1']['id'] in user_lobbies: del user_lobbies[lobby['p1']['id']]
        if lobby['p2']['id'] in user_lobbies: del user_lobbies[lobby['p2']['id']]
        del active_lobbies[lobby_id]
        
        await query.answer("You Won!", show_alert=True)
        return

    if " " not in lobby['board']:
        final_text = "🤝 **It's a Draw!** Both players fought well."
        markup = get_board_keyboard(lobby_id, lobby['board'])
        await context.bot.send_message(chat_id=lobby['p1']['chat_id'], text=final_text, reply_markup=markup, parse_mode='Markdown')
        if lobby['p1']['chat_id'] != lobby['p2']['chat_id']:
            await context.bot.send_message(chat_id=lobby['p2']['chat_id'], text=final_text, reply_markup=markup, parse_mode='Markdown')
        
        # Cleanup
        if lobby['p1']['id'] in user_lobbies: del user_lobbies[lobby['p1']['id']]
        if lobby['p2']['id'] in user_lobbies: del user_lobbies[lobby['p2']['id']]
        del active_lobbies[lobby_id]
        return

    # Switch Turn
    if user_id == lobby['p1']['id']:
        lobby['turn'] = lobby['p2']['id']
        next_name = lobby['p2']['name']
        next_symbol = "⭕"
    else:
        lobby['turn'] = lobby['p1']['id']
        next_name = lobby['p1']['name']
        next_symbol = "❌"

    await query.answer("Move placed! ✅")

    # Update Boards for both players
    status_text = (
        f"⚔️ **GAME ON!** ⚔️\n\n"
        f"❌ {lobby['p1']['name']} VS ⭕ {lobby['p2']['name']}\n\n"
        f"**Current Turn:** {next_name} ({next_symbol})"
    )
    markup = get_board_keyboard(lobby_id, lobby['board'])
    
    # Try editing the message for the player who clicked
    try:
        await query.edit_message_text(status_text, reply_markup=markup, parse_mode='Markdown')
    except: pass

    # Send a fresh board to the other player so it pops up at the bottom of their chat
    opponent_chat = lobby['p2']['chat_id'] if user_id == lobby['p1']['id'] else lobby['p1']['chat_id']
    if opponent_chat != query.message.chat_id: # Only send if they are in different chats (e.g., DMs)
        await context.bot.send_message(chat_id=opponent_chat, text=status_text, reply_markup=markup, parse_mode='Markdown')
