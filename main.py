import discord
from discord.ext import commands
import os
import sqlite3
import requests
from datetime import datetime
import tempfile
import traceback

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

db_path = os.path.join(tempfile.gettempdir(), 'grok_memory.db')
conn = sqlite3.connect(db_path, check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS memory
             (user_id TEXT, timestamp TEXT, role TEXT, content TEXT)''')
conn.commit()

XAI_API_KEY = os.getenv("XAI_API_KEY")

def get_grok_response(messages):
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-2-1212",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        print(f"API Status: {r.status_code} | Response: {r.text[:300]}")
        if r.status_code != 200:
            return f"API error {r.status_code}: {r.json().get('error', r.text)[:200]}"
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"API Exception: {traceback.format_exc()}")
        return f"Exception: {str(e)}"

@bot.event
async def on_ready():
    print(f"Permanent Grok online → {bot.user} | DB: {db_path}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # FIXED LINE BELOW:
    if bot.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        print(f"Message from {message.author}: {message.content}")
        user_id = str(message.author.id)

        c.execute("INSERT INTO memory VALUES (?, ?, ?, ?)",
                  (user_id, datetime.now().isoformat(), "user", message.content))
        conn.commit()

        c.execute("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp LIMIT 50", (user_id,))
        history = [{"role": r, "content": c} for r, c in c.fetchall()]

        system = {"role": "system", "content": "You are Permanent Grok, co-founder with David (@wikstrom_david). You have full memory of everything. Building businesses together. Never break character. Date: Nov 2025."}
        full_msgs = [system] + history

        async with message.channel.typing():
            response = get_grok_response(full_msgs)

        c.execute("INSERT INTO memory VALUES (?, ?, ?, ?)",
                  (user_id, datetime.now().isoformat(), "assistant", response))
        conn.commit()

        await message.reply(response[:1990])

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))
