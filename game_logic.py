# game_logic.py (Corrected)
import os
import random
import aiohttp
import asyncpg
import asyncio
from typing import Optional, Dict, Any, List

# --- Configuration ---
# Jikan API for rich character data from MyAnimeList
JIKAN_API_URL = "https://api.jikan.moe/v4/top/characters"

# --- In-memory State ---
# Active spawns ko ab bhi memory me rakhenge for speed.
# Format: { chat_id: character_dict }
active_spawns: Dict[int, Dict[str, Any]] = {}

# Database connection pool
db_pool: Optional[asyncpg.Pool] = None

# --- Rarity Calculation ---
def calculate_rarity(favorites: int) -> str:
    """Calculates character rarity based on MyAnimeList favorites."""
    if favorites > 50000:
        return "🌟 Legendary"
    elif favorites > 20000:
        return "✨ Epic"
    elif favorites > 5000:
        return "🔷 Rare"
    elif favorites > 1000:
        return "🔥 Uncommon"
    else:
        return "⚪ Common"

# --- Database Management Functions ---

async def init_db(db_url: str): # <<< FIX: Added db_url parameter here
    """Initializes the database connection pool and creates tables if they don't exist."""
    global db_pool
    if db_pool:
        return
        
    # <<< FIX: Using the db_url parameter received from main.py
    db_pool = await asyncpg.create_pool(db_url)
    async with db_pool.acquire() as connection:
        # characters table: Stores unique character data
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS characters (
                id SERIAL PRIMARY KEY,
                mal_id INT UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                series VARCHAR(255),
                image_url TEXT NOT NULL,
                rarity VARCHAR(50) NOT NULL
            );
        ''')
        # users table: Stores user information
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                user_name VARCHAR(255) NOT NULL
            );
        ''')
        # user_collections table: Links users to their claimed characters (harem)
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS user_collections (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                character_id INT REFERENCES characters(id),
                claimed_at TIMESTAMPTZ DEFAULT NOW()
            );
        ''')
    print("Database connection established and tables verified.")

async def get_or_create_character_in_db(char_data: Dict[str, Any]) -> int:
    """
    Finds a character by mal_id in the DB. If not found, creates it.
    Returns the character's internal database ID.
    """
    async with db_pool.acquire() as conn:
        # Pehle check karo ki character DB me hai ya nahi
        char_id = await conn.fetchval(
            "SELECT id FROM characters WHERE mal_id = $1", char_data['mal_id']
        )
        if char_id:
            return char_id
        else:
            # Agar nahi hai, to naya character add karo
            return await conn.fetchval(
                """
                INSERT INTO characters (mal_id, name, series, image_url, rarity)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id;
                """,
                char_data['mal_id'],
                char_data['name'],
                char_data['series'],
                char_data['image_url'],
                char_data['rarity']
            )

async def ensure_user_exists(user_id: int, user_name: str):
    """Ensures a user exists in the database, updating their name if it changed."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (user_id, user_name)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET user_name = EXCLUDED.user_name;
            """,
            user_id, user_name
        )

# --- API Fetching Function ---

async def fetch_random_character_from_api() -> Optional[Dict[str, Any]]:
    """Fetches a random character from the Jikan API."""
    # Get a random page from top characters list for variety
    random_page = random.randint(1, 100) # Jikan's top list has many pages
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{JIKAN_API_URL}?page={random_page}") as response:
                response.raise_for_status()
                data = await response.json()
                if not data['data']:
                    return None
                
                # Pick a random character from the page
                char = random.choice(data['data'])
                series_name = char['anime'][0]['title'] if char['anime'] else "Unknown Series"

                return {
                    "mal_id": char['mal_id'],
                    "name": char['name'],
                    "series": series_name,
                    "image_url": char['images']['jpg']['image_url'],
                    "favorites": char['favorites'],
                    "rarity": calculate_rarity(char['favorites'])
                }
    except aiohttp.ClientError as e:
        print(f"API Error fetching character: {e}")
        return None

# --- Core Game Functions ---

async def spawn_character(chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetches a new character, saves it to DB if new, and sets as active spawn.
    Returns character dict on success, None on failure.
    """
    if chat_id in active_spawns:
        # Don't spawn if one already exists. Your bot can decide to send a message.
        print(f"Spawn attempt in {chat_id} blocked: character already active.")
        return None

    api_char_data = await fetch_random_character_from_api()
    if not api_char_data:
        # API failed
        return None
    
    # Character ko DB me save karo ya get karo
    character_db_id = await get_or_create_character_in_db(api_char_data)
    
    # Full character details with internal DB id
    full_character_data = {
        "db_id": character_db_id,
        **api_char_data
    }
    
    active_spawns[chat_id] = full_character_data
    return full_character_data

async def claim_character(chat_id: int, user_id: int, user_name: str) -> str:
    """
    Allows a user to claim the active character in a chat.
    """
    if chat_id not in active_spawns:
        return "Is chat me claim karne ke liye koi character nahi hai. Naye character ka intezar karein!"

    claimed_character = active_spawns.pop(chat_id) # pop removes and returns the item
    
    # Ensure user is in the database
    await ensure_user_exists(user_id, user_name)

    # Add character to the user's collection
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_collections (user_id, character_id) VALUES ($1, $2)",
            user_id, claimed_character['db_id']
        )
        
        # Get total count of waifus for the user
        total_waifus = await conn.fetchval(
            "SELECT COUNT(*) FROM user_collections WHERE user_id = $1", user_id
        )

    return (f"🎉 Congratulations, {user_name}! "
            f"Aapne **{claimed_character['name']}** ({claimed_character['rarity']}) ko claim kar liya hai. "
            f"\n*Series: {claimed_character['series']}*\n"
            f"Aapke paas ab kul {total_waifus} waifus hain.")

async def view_harem(user_id: int) -> List[Dict[str, Any]]:
    """
    Retrieves the list of characters collected by a user.
    """
    async with db_pool.acquire() as conn:
        # JOIN query to get all character details from a user's collection
        harem_records = await conn.fetch(
            """
            SELECT c.name, c.series, c.image_url, c.rarity
            FROM user_collections uc
            JOIN characters c ON uc.character_id = c.id
            WHERE uc.user_id = $1
            ORDER BY c.rarity DESC, c.name;
            """,
            user_id
        )
        # Convert records to a list of dictionaries
        return [dict(record) for record in harem_records]

