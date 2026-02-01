import os
import json
import re
from typing import Optional, Union
from dotenv import load_dotenv
import discord
from discord import app_commands, ui
from datetime import datetime, timezone, timedelta
import asyncio
from zoneinfo import ZoneInfo

load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
CLEAR_GLOBAL_COMMANDS = os.getenv("DISCORD_CLEAR_GLOBAL_COMMANDS", "").strip() == "1"


def parse_id_list(value: str) -> list[int]:
    # Extract any numeric IDs from the string to tolerate quotes/spaces/newlines.
    return [int(x) for x in re.findall(r"\d{5,}", value or "")]


SYNC_GUILD_IDS = parse_id_list(os.getenv("DISCORD_GUILD_IDS", ""))
SYNC_GUILD_IDS += parse_id_list(os.getenv("DISCORD_GUILD_ID", ""))
SYNC_GUILD_IDS = sorted(set(SYNC_GUILD_IDS))

ALLOWED_GUILD_IDS = set(parse_id_list(os.getenv("ALLOWED_GUILD_IDS", "")))

DATA_FILE = "bot_data.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Store downtime info
current_downtime = {
    "start": None,
    "end": None,
    "title": None
}

panel_messages: list[dict[str, int]] = []

# Theme (Infinity Nikki)
ONLINE_COLOR = discord.Color.from_rgb(255, 173, 216)  # #ffadd8
MAINT_COLOR = discord.Color.from_rgb(255, 122, 184)   # deeper pink
HEART_EMOJI = "\U0001F497"  # sparkling heart
ONLINE_EMOJI = "\U0001F495"  # two hearts
MAINT_EMOJI = "\U0001F49D"   # heart with ribbon
TIME_EMOJI = "\U0001F49E"    # revolving hearts
FOOTER_TEXT = "Infinity Nikki - Status Panel"
BUTTON_LABEL = "Check Status"

# Common timezone shortcuts
TZ_SHORTCUTS = {
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "GMT": "Europe/London",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "UTC": "UTC",
}

# Fallback offsets when IANA tzdata is unavailable (hours from UTC)
TZ_ABBR_OFFSETS = {
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "GMT": 0,
    "BST": 1,
    "CET": 1,
    "UTC": 0,
}


def load_data() -> None:
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        current_downtime["start"] = data.get("start")
        current_downtime["end"] = data.get("end")
        current_downtime["title"] = data.get("title")
        panels = data.get("panels", [])
        if isinstance(panels, list):
            panel_messages.clear()
            for item in panels:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("channel_id"), int)
                    and isinstance(item.get("message_id"), int)
                ):
                    panel_messages.append(item)
    except Exception as exc:
        print(f"Failed to load {DATA_FILE}: {exc!r}")


def save_data() -> None:
    data = {
        "start": current_downtime["start"],
        "end": current_downtime["end"],
        "title": current_downtime["title"],
        "panels": panel_messages,
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        print(f"Failed to save {DATA_FILE}: {exc!r}")


def resolve_timezone(tz_input: str) -> str:
    """Convert shortcut to full timezone name, or return as-is."""
    if not tz_input:
        return "UTC"
    tz_clean = tz_input.strip()
    return TZ_SHORTCUTS.get(tz_clean.upper(), tz_clean)


def get_tzinfo(
    tz_name: str, tz_fallback: Optional[str] = None
) -> Optional[Union[timezone, ZoneInfo]]:
    """Resolve a timezone name to tzinfo, with fallback to fixed offsets for abbreviations."""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        abbr = (tz_fallback or tz_name or "").strip().upper()
        offset_hours = TZ_ABBR_OFFSETS.get(abbr)
        if offset_hours is None:
            return None
        return timezone(timedelta(hours=offset_hours))


def normalize_time_input(time_str: str) -> str:
    """Normalize whitespace and AM/PM spacing."""
    cleaned = " ".join(time_str.strip().split())
    if cleaned.upper().endswith(("AM", "PM")) and " " not in cleaned[-3:]:
        # Convert 9:48AM -> 9:48 AM
        cleaned = cleaned[:-2] + " " + cleaned[-2:]
    return cleaned


def parse_time(time_str: str, tzinfo: Union[timezone, ZoneInfo]) -> Optional[datetime]:
    """Parse time string and convert from specified timezone to UTC."""
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%m/%d %H:%M",
        "%m/%d %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%H:%M",
        "%I:%M %p",
    ]
    
    now_local = datetime.now(tzinfo)
    normalized = normalize_time_input(time_str)
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt in ("%H:%M", "%I:%M %p"):
                parsed = parsed.replace(year=now_local.year, month=now_local.month, day=now_local.day)
            elif fmt == "%m/%d %H:%M":
                parsed = parsed.replace(year=now_local.year)
            elif fmt == "%m/%d %I:%M %p":
                parsed = parsed.replace(year=now_local.year)
            
            parsed = parsed.replace(tzinfo=tzinfo)
            if fmt in ("%H:%M", "%I:%M %p"):
                # If the time already passed today, assume next day to avoid "completed" schedules.
                if parsed < now_local:
                    parsed = parsed + timedelta(days=1)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


async def apply_downtime(
    interaction: discord.Interaction,
    start: str,
    end: str,
    tz: str,
    title: Optional[str],
) -> None:
    tz_resolved = resolve_timezone(tz)
    tzinfo = get_tzinfo(tz_resolved, tz_fallback=tz)
    if not tzinfo:
        await interaction.response.send_message(
            "Invalid timezone.\n"
            "Examples: `EST`, `PST`, `UTC`, `America/New_York`\n"
            "Note: On Windows, install `tzdata` (pip install tzdata) for full IANA support.",
            ephemeral=True,
        )
        return

    start_dt = parse_time(start, tzinfo)
    end_dt = parse_time(end, tzinfo)

    if not start_dt or not end_dt:
        await interaction.response.send_message(
            "Invalid time format.\n"
            "Formats: `HH:MM`, `HH:MM AM`, `MM/DD HH:MM`, `MM/DD HH:MM AM`, "
            "`MM/DD/YYYY HH:MM`, `YYYY-MM-DD HH:MM`",
            ephemeral=True,
        )
        return

    if end_dt <= start_dt:
        await interaction.response.send_message("End time must be after start time.", ephemeral=True)
        return

    final_title = (title or "").strip() or "Scheduled Maintenance"

    current_downtime["start"] = int(start_dt.timestamp())
    current_downtime["end"] = int(end_dt.timestamp())
    current_downtime["title"] = final_title
    save_data()
    await update_panels()

    await interaction.response.send_message(
        f"{HEART_EMOJI} Downtime set: {final_title}\n"
        f"Start: <t:{current_downtime['start']}:f>\n"
        f"End: <t:{current_downtime['end']}:f>\n"
        f"(Entered in {tz_resolved})",
        ephemeral=True,
    )


async def update_panels() -> None:
    if not panel_messages:
        return
    embed = get_status_embed(full=False)
    stale: list[dict[str, int]] = []
    for item in panel_messages:
        channel_id = item.get("channel_id")
        message_id = item.get("message_id")
        if not channel_id or not message_id:
            stale.append(item)
            continue
        channel = client.get_channel(channel_id)
        try:
            if channel is None:
                channel = await client.fetch_channel(channel_id)
            if not hasattr(channel, "fetch_message"):
                stale.append(item)
                continue
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=StatusPanel())
        except Exception:
            stale.append(item)
    if stale:
        for item in stale:
            if item in panel_messages:
                panel_messages.remove(item)
        save_data()


def get_status_embed(full: bool = False) -> discord.Embed:
    """Build status embed. full=True for detailed view, False for panel."""
    
    if not current_downtime["start"]:
        embed = discord.Embed(
            title=f"{ONLINE_EMOJI} Server Status",
            description="No maintenance scheduled.",
            color=ONLINE_COLOR
        )
        return embed
    
    now = datetime.now(timezone.utc).timestamp()
    start_ts = current_downtime["start"]
    end_ts = current_downtime["end"]
    title = current_downtime["title"] or "Scheduled Maintenance"
    
    if now < start_ts:
        status = f"{ONLINE_EMOJI} ONLINE"
        color = ONLINE_COLOR
        details = (
            f"**Upcoming Maintenance:** {title}\n\n"
            f"{TIME_EMOJI} Downtime begins: <t:{start_ts}:R>\n"
            f"{TIME_EMOJI} Start: <t:{start_ts}:f>\n"
            f"{TIME_EMOJI} End: <t:{end_ts}:f>"
        ) if full else f"Maintenance scheduled <t:{start_ts}:R>"
    elif now < end_ts:
        status = f"{MAINT_EMOJI} MAINTENANCE"
        color = MAINT_COLOR
        details = (
            f"**{title}**\n\n"
            f"{TIME_EMOJI} Servers back online: <t:{end_ts}:R>\n"
            f"{TIME_EMOJI} At: <t:{end_ts}:f>"
        ) if full else f"Back online <t:{end_ts}:R>"
    else:
        status = f"{ONLINE_EMOJI} ONLINE"
        color = ONLINE_COLOR
        details = "Maintenance complete!" if full else "All systems operational"
    
    embed = discord.Embed(
        title=f"{status}",
        description=details,
        color=color
    )
    
    if not full:
        embed.set_footer(text=FOOTER_TEXT)
    
    return embed


# ============ BUTTON VIEW ============
class StatusPanel(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label=BUTTON_LABEL, style=discord.ButtonStyle.primary, emoji=HEART_EMOJI, custom_id="check_status")
    async def check_status(self, interaction: discord.Interaction, button: ui.Button):
        embed = get_status_embed(full=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SetDowntimeModal(ui.Modal, title="Set Downtime"):
    def __init__(self):
        super().__init__()
        self.start_input = ui.TextInput(
            label="Start",
            placeholder="e.g. 2/15 9:00 PM or 2026-02-15 21:00",
            required=True,
        )
        self.end_input = ui.TextInput(
            label="End",
            placeholder="e.g. 2/15 11:00 PM or 2026-02-15 23:00",
            required=True,
        )
        self.tz_input = ui.TextInput(
            label="Timezone (optional)",
            placeholder="UTC, EST, America/New_York",
            required=False,
        )
        self.title_input = ui.TextInput(
            label="Title (optional)",
            placeholder="Patch 2.1 Update",
            required=False,
        )
        self.add_item(self.start_input)
        self.add_item(self.end_input)
        self.add_item(self.tz_input)
        self.add_item(self.title_input)

    async def on_submit(self, interaction: discord.Interaction):
        tz_value = (self.tz_input.value or "").strip() or "UTC"
        title_value = (self.title_input.value or "").strip() or "Scheduled Maintenance"
        await apply_downtime(
            interaction,
            self.start_input.value,
            self.end_input.value,
            tz_value,
            title_value,
        )


# ============ EVENTS ============
@tree.check
async def enforce_allowed_guild(interaction: discord.Interaction) -> bool:
    if not ALLOWED_GUILD_IDS:
        return True
    return interaction.guild_id in ALLOWED_GUILD_IDS


@client.event
async def on_guild_join(guild: discord.Guild):
    if ALLOWED_GUILD_IDS and guild.id not in ALLOWED_GUILD_IDS:
        await guild.leave()


@client.event
async def on_ready():
    client.add_view(StatusPanel())
    load_data()
    if SYNC_GUILD_IDS:
        print(f"Sync guild IDs: {SYNC_GUILD_IDS}")
    if ALLOWED_GUILD_IDS:
        print(f"Allowed guild IDs: {sorted(ALLOWED_GUILD_IDS)}")
    if SYNC_GUILD_IDS:
        if CLEAR_GLOBAL_COMMANDS:
            tree.clear_commands(guild=None)
            await tree.sync()
            print("Cleared global commands")
        for guild_id in SYNC_GUILD_IDS:
            guild_obj = discord.Object(id=guild_id)
            tree.copy_global_to(guild=guild_obj)
            synced = await tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} commands to guild {guild_id}")
    else:
        synced = await tree.sync()
        print(f"Synced {len(synced)} global commands")
    await update_panels()
    print(f"Bot is online as {client.user}")


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the Manage Server permission to use this command."
    elif isinstance(error, app_commands.CheckFailure):
        message = "This bot is restricted to approved servers."
    elif isinstance(error, app_commands.CommandInvokeError):
        # Unwrap the original exception for clearer logging.
        message = "An internal error occurred while running that command."
        print(f"Command error: {error.original!r}")
    else:
        message = "An unexpected error occurred."
        print(f"App command error: {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


# ============ MOD COMMANDS ============
@tree.command(name="setdowntime", description="[MOD] Set a maintenance window")
@app_commands.describe(
    start="Start time (HH:MM, HH:MM AM, MM/DD HH:MM, MM/DD/YYYY HH:MM, or YYYY-MM-DD HH:MM)",
    end="End time (same formats)",
    tz="Your timezone (EST, PST, UTC, etc.)",
    title="Optional custom title"
)
@app_commands.default_permissions(manage_guild=True)
async def setdowntime(
    interaction: discord.Interaction, 
    start: str, 
    end: str, 
    tz: str = "UTC",
    title: str = "Scheduled Maintenance"
):
    await apply_downtime(interaction, start, end, tz, title)


@tree.command(name="setdowntimewizard", description="[MOD] Set a maintenance window with a form")
@app_commands.default_permissions(manage_guild=True)
async def setdowntimewizard(interaction: discord.Interaction):
    await interaction.response.send_modal(SetDowntimeModal())


@tree.command(name="panel", description="[MOD] Post the status panel in this channel")
@app_commands.default_permissions(manage_guild=True)
async def post_panel(interaction: discord.Interaction):
    embed = get_status_embed(full=False)
    message = await interaction.channel.send(embed=embed, view=StatusPanel())
    panel_messages.append({"channel_id": message.channel.id, "message_id": message.id})
    save_data()
    await interaction.response.send_message("Panel posted.", ephemeral=True)


@tree.command(name="cleardowntime", description="[MOD] Clear scheduled downtime")
@app_commands.default_permissions(manage_guild=True)
async def cleardowntime(interaction: discord.Interaction):
    current_downtime["start"] = None
    current_downtime["end"] = None
    current_downtime["title"] = None
    save_data()
    await update_panels()
    await interaction.response.send_message("Downtime cleared.", ephemeral=True)


# ============ PUBLIC COMMAND ============
@tree.command(name="status", description="Check server status (only you can see)")
async def status(interaction: discord.Interaction):
    embed = get_status_embed(full=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")

client.run(BOT_TOKEN)
