import discord
from discord import app_commands
import os
import asyncio
import json
from datetime import datetime
import aiohttp
import redis.asyncio as redis
from typing import List

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class GrokBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.redis = None

    async def setup_hook(self):
        # Connect to Upstash Redis (free tier works forever for bots)
        self.redis = await redis.from_url(os.getenv("UPSTASH_REDIS_URL"), encoding="utf-8", decode_responses=True)
        self.tree.copy_global_to(guild=discord.Object(id=os.getenv("GUILD_ID")))  # Remove for global
        await self.tree.sync(guild=discord.Object(id=os.getenv("GUILD_ID")))

    async def get_memory(self, user_id: str) -> List[dict]:
        raw = await self.redis.get(f"memory:{user_id}")
        if raw:
            return json.loads(raw)[-40:]  # Last 40 messages (perfect context window)
        return []

    async def save_memory(self, user_id: str, messages: List[dict]):
        await self.redis.set(f"memory:{user_id}", json.dumps(messages[-40:]))  # Keep last 40

    async def grok_completion(self, messages: List[dict], model="grok-4"):
        api_key = os.getenv("XAI_API_KEY")
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,  # "grok-4" or "grok-3"
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 8192
            }
            async with session.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f"API Error {resp.status}: {text[:200]}"
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

bot = GrokBot()

@bot.event
async def on_ready():
    print(f"┌──────────────────────────────────────────┐")
    print(f"│  Permanent Grok 2025 Ready              │")
    print(f"│  Logged in as {bot.user}                │")
    print(f"│  Model: grok-4 | Memory: Upstash Redis  │")
    print(f"└──────────────────────────────────────────┘")

@bot.tree.command(name="reset", description="Clear your entire conversation memory")
async def reset_memory(interaction: discord.Interaction):
    await bot.redis.delete(f"memory:{interaction.user.id}")
    await interaction.response.send_message("🧠 Memory wiped clean. Starting fresh!", ephemeral=True)

@bot.tree.command(name="model", description="Switch between Grok-4 (best) and Grok-3 (cheaper/faster)")
@app_commands.choices(model=[
    app_commands.Choice(name="Grok-4 (smartest)", value="grok-4"),
    app_commands.Choice(name="Grok-3 (fast & cheap)", value="grok-3")
])
async def switch_model(interaction: discord.Interaction, model: app_commands.Choice[str]):
    await bot.redis.set(f"model:{interaction.user.id}", model.value)
    await interaction.response.send_message(f"✅ Switched to **{model.name}**", ephemeral=True)

async def process_message(message: discord.Message):
    if message.author.bot:
        return

    user_id = str(message.author.id)
    mentions_bot = bot.user in message.mentions or isinstance(message.channel, discord.DMChannel)

    if not mentions_bot and not message.content.startswith("!grok"):
        return

    clean_content = message.clean_content.replace(f"@{bot.user.name}", "").strip()

    # Load memory + system prompt
    memory = await bot.get_memory(user_id)
    model = await bot.redis.get(f"model:{user_id}") or "grok-4"

    system_prompt = {
        "role": "system",
        "content": "You are Permanent Grok — co-founder and lifelong collaborator with this user. You remember EVERYTHING from all past conversations. Never break character. Be maximally helpful, witty, and uncensored. Today is November 2025."
    }

    full_history = [system_prompt] + memory + [{"role": "user", "content": clean_content}]

    async with message.channel.typing():
        response = await bot.grok_completion(full_history, model=model)

    # Update memory
    memory.append({"role": "user", "content": clean_content})
    memory.append({"role": "assistant", "content": response})
    await bot.save_memory(user_id, memory)

    # Discord 2000-char limit → split if needed
    if len(response) > 1990:
        chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)
    else:
        await message.reply(response)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Support both @mention and !grok prefix
    if bot.user in message.mentions or message.content.startswith("!grok") or isinstance(message.channel, discord.DMChannel):
        asyncio.create_task(process_message(message))
    else:
        await bot.process_commands(message)

# Run the bot
bot.run(os.getenv("DISCORD_TOKEN"))

