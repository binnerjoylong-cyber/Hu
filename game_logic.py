# game_logic.py
import requests
import json
import os
from collections import defaultdict

# --- Configuration ---
# Free API for random waifu images
WAIFU_API_URL = "https://api.waifu.pics/sfw/waifu" 
# File to store user data (their collections)
USER_DATA_FILE = "user_harem_data.json"

# --- In-memory Data Storage ---
# This will hold all user collections. It's loaded from the file at startup.
# Format: { "user_id": {"name": "User's Name", "harem": [character_obj, ...]} }
user_collections = {}

# This tracks the currently active, unclaimed character in each chat.
# This is temporary and resets if the bot restarts.
# Format: { "chat_id": character_obj }
active_spawns = {}

# --- Data Management Functions ---

def load_data():
    """Loads user collections from the JSON file into memory."""
    global user_collections
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                user_collections = json.load(f)
            print("Game data loaded successfully.")
        except json.JSONDecodeError:
            print(f"Warning: Could not read {USER_DATA_FILE}. It might be corrupted. Starting fresh.")
            user_collections = {}
    else:
        print("No existing game data file found. A new one will be created.")
        user_collections = {}

def save_data():
    """Saves the current user collections from memory to the JSON file."""
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(user_collections, f, indent=4)
    except Exception as e:
        print(f"Error: Failed to save game data! - {e}")

# --- Core Game Functions ---

def spawn_character(chat_id):
    """
    Fetches a new character from the API and sets it as the active spawn for a chat.
    Returns the character object if successful, or an error message string.
    """
    # Don't spawn a new one if an unclaimed one already exists in the chat
    if chat_id in active_spawns:
        return "Pehle is waifu ko to claim karo! Ek character pehle se yahan hai."

    try:
        response = requests.get(WAIFU_API_URL)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        data = response.json()
        
        # This API gives only a URL. For a real game, you'd want an API with names, series, etc.
        character = {
            "url": data['url'],
            # In a real game, you would add more data like:
            # "name": "Character Name",
            # "series": "Anime Series",
            # "rarity": 95 
        }

        active_spawns[chat_id] = character
        return character # Return the character object to be sent as a photo
        
    except requests.RequestException as e:
        print(f"API Error fetching character: {e}")
        return "Sorry, API se connect nahi ho pa raha. Baad me try karo."

def claim_character(chat_id, user_id, user_name):
    """
    Allows a user to claim the active character in a chat.
    Returns a success or failure message string.
    """
    user_id_str = str(user_id) # JSON keys must be strings

    if chat_id not in active_spawns:
        return "Is chat me claim karne ke liye koi character nahi hai. `/waifu` type karke naya character bulao."

    # The character that was spawned
    claimed_character = active_spawns[chat_id]

    # Add user to collections if they are new
    if user_id_str not in user_collections:
        user_collections[user_id_str] = {"name": user_name, "harem": []}
    
    # Update user's name in case it changed
    user_collections[user_id_str]['name'] = user_name

    # Add the character to the user's harem
    user_collections[user_id_str]['harem'].append(claimed_character)
    
    # Save the updated data to the file
    save_data()
    
    # Remove the character from active spawns so it can't be claimed again
    del active_spawns[chat_id]
    
    total_waifus = len(user_collections[user_id_str]['harem'])
    return f"🎉 Congratulations, {user_name}! Aapne is waifu ko claim kar liya hai. Ab aapke paas {total_waifus} waifus hain."

def view_harem(user_id):
    """
    Retrieves the list of characters collected by a user.
    Returns the user's data object or None if the user has no collection.
    """
    user_id_str = str(user_id)
    return user_collections.get(user_id_str)
