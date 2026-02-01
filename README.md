# Discord Update Notice Bot

A Discord bot for scheduling maintenance windows and showing countdowns with a persistent status panel.

## Features
- `/setdowntime` - set downtime with slash options (mods only)
- `/setdowntimechat` - guided chat setup (mods only)
- `/cleardowntime` - clear downtime (mods only)
- `/panel` - post a persistent status panel (mods only)
- `/status` - check status (everyone)

## Requirements
- Python 3.9+
- A Discord bot token

## Quick Start (Local)
```bash
git clone https://github.com/chilidogsonic/discord-update-bot.git
cd discord-update-bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file (copy from `.env.example`) and fill in values:
```bash
cp .env.example .env
```

Run the bot:
```bash
python bot.py
```

## Environment Variables
Create a `.env` file with:
```
DISCORD_BOT_TOKEN=your_token_here
DISCORD_GUILD_IDS=123,456
ALLOWED_GUILD_IDS=123,456
DISCORD_CLEAR_GLOBAL_COMMANDS=0
```

### Notes
- `DISCORD_GUILD_IDS`: guilds to sync slash commands to (comma-separated).
- `ALLOWED_GUILD_IDS`: restrict bot usage to these guilds (comma-separated).
- `DISCORD_CLEAR_GLOBAL_COMMANDS=1` (one-time) clears global commands to remove duplicates.

## Discord Bot Setup
1) Create a bot in the Discord Developer Portal.
2) Copy the bot token into `.env`.
3) Invite the bot with **applications.commands** + **bot** scopes.
4) Give it permissions:
   - Manage Server
   - Send Messages
   - Embed Links
   - Read Message History

## Permissions
Create a role named **downtime** and assign it to anyone who should manage the bot.

## Hosting Notes
- Use a host that keeps the process online 24/7.
- Set the environment variables in your host panel instead of uploading `.env`.

## Security
- Never commit your `.env` file or token.
- Rotate your token if it is ever exposed.
