import os
from dotenv import load_dotenv
import discord
from discord import app_commands

load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    synced = await tree.sync()
    print(f"Event Timers Bot is online as {client.user}")
    print(f"Synced {len(synced)} commands")


if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")

client.run(BOT_TOKEN)
