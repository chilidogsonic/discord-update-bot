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

# Store downtime info per guild
current_downtime: dict[int, dict[str, Optional[Union[int, str]]]] = {}

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

# ============ EVENT SYSTEM ============
# Event data - update monthly with current Infinity Nikki events
EVENTS = [
    # Version 2.2 Resonance Events
    {
        "type": "resonance",
        "name": "Echoes of Wanxiang",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1772480940,    # Mar 2, 2026 19:49 UTC
        "description": "5★ outfit Where Wanxiang Weaves Life, 4★ Song Beyond",
        "rewards": "5★ Miracle Outfit, 4★ Outfit, Decorations, Heartshine Items",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    {
        "type": "resonance",
        "name": "Traces of Chroma",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1772480940,    # Mar 2, 2026 19:49 UTC
        "description": "5★ outfit Chroma's Mortal Heart, 4★ Moonlit Immortal",
        "rewards": "5★ Miracle Outfit, 4★ Outfit, Dance Moves, Items",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    # Version 2.2 Collection & Task Events
    {
        "type": "task",
        "name": "Flavors of Life",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1772480940,    # Mar 2, 2026 19:49 UTC
        "description": "Complete tasks to earn 4★ outfit Tasting the World",
        "rewards": "4★ Outfit, Outfit Sketch, Diamonds",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    {
        "type": "quest",
        "name": "Transient Wonders",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1772480940,    # Mar 2, 2026 19:49 UTC
        "description": "Collection event with special rewards",
        "rewards": "Diamonds, Card: Endless Revelry, Materials",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    {
        "type": "checkin",
        "name": "Chroma's Blessings",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1771034340,    # Feb 14, 2026 01:59 UTC
        "description": "7-day login event for Revelation Crystals",
        "rewards": "10 Revelation Crystals",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    {
        "type": "doublerewards",
        "name": "Deep Breakthrough",
        "start": 1770004800,  # Feb 2, 2026 04:00 UTC
        "end": 1771819140,    # Feb 23, 2026 03:59 UTC
        "description": "Weekly doubled realm challenge rewards",
        "rewards": "Double Realm Challenge Rewards (once per week per realm)",
        "url": "https://infinity-nikki.fandom.com/wiki/Version/2.2"
    },
    # Battle Pass
    {
        "type": "store",
        "name": "Mira Journey (Battle Pass)",
        "start": 1769716800,  # Jan 29, 2026 20:00 UTC
        "end": 1772480940,    # Mar 2, 2026 19:49 UTC
        "description": "Complete Journey Tasks for rewards, max level 90",
        "rewards": "Resonite Crystals, Energy Crystals, Premium Items",
        "url": "https://infinity-nikki.fandom.com/wiki/Mira_Journey"
    },
    # Daily & Weekly Resets
    {
        "type": "recurring",
        "name": "Daily Reset",
        "start": 1769644800,  # Jan 29, 2026 00:00 UTC (start of v2.2)
        "end": 1798761600,    # Dec 31, 2026 00:00 UTC (far future)
        "description": "Daily reset at 04:00 server time (11:00 UTC for America)",
        "rewards": "Daily Quests, Shop Refresh, Energy Refresh",
        "url": "https://infinity-nikki.fandom.com/wiki/Reset"
    },
    {
        "type": "recurring",
        "name": "Weekly Reset",
        "start": 1769644800,  # Jan 29, 2026 00:00 UTC
        "end": 1798761600,    # Dec 31, 2026 00:00 UTC
        "description": "Weekly reset every Monday at 04:00 server time",
        "rewards": "Weekly Quests, Weekly Shop Refresh, Realm Challenges",
        "url": "https://infinity-nikki.fandom.com/wiki/Reset"
    }
]

# Event type configuration - styling for each event category
EVENT_TYPE_CONFIG = {
    "resonance": {
        "emoji": "✨",
        "color": discord.Color.from_rgb(255, 200, 220),
        "display_name": "Resonance Event"
    },
    "quest": {
        "emoji": "📜",
        "color": discord.Color.from_rgb(200, 220, 255),
        "display_name": "Quest Event"
    },
    "task": {
        "emoji": "✅",
        "color": discord.Color.from_rgb(220, 255, 200),
        "display_name": "Task Event"
    },
    "checkin": {
        "emoji": "📅",
        "color": discord.Color.from_rgb(255, 220, 200),
        "display_name": "Check-in Event"
    },
    "doublerewards": {
        "emoji": "⭐",
        "color": discord.Color.from_rgb(255, 255, 150),
        "display_name": "Double Rewards"
    },
    "web": {
        "emoji": "🌐",
        "color": discord.Color.from_rgb(200, 255, 255),
        "display_name": "Web Event"
    },
    "store": {
        "emoji": "🛍️",
        "color": discord.Color.from_rgb(255, 200, 255),
        "display_name": "Store Event"
    },
    "recurring": {
        "emoji": "🔄",
        "color": discord.Color.from_rgb(220, 220, 220),
        "display_name": "Recurring Event"
    }
}

# Store event panel messages (separate from downtime panels)
event_panel_messages: list[dict[str, Union[int, str]]] = []


COMMON_TIMEZONES = [
    ("UTC", "UTC"),
    ("Eastern (America/New_York)", "America/New_York"),
    ("Central (America/Chicago)", "America/Chicago"),
    ("Mountain (America/Denver)", "America/Denver"),
    ("Pacific (America/Los_Angeles)", "America/Los_Angeles"),
    ("UK (Europe/London)", "Europe/London"),
    ("Central Europe (Europe/Paris)", "Europe/Paris"),
    ("Tokyo (Asia/Tokyo)", "Asia/Tokyo"),
    ("Sydney (Australia/Sydney)", "Australia/Sydney"),
    ("Auckland (Pacific/Auckland)", "Pacific/Auckland"),
    ("Sao Paulo (America/Sao_Paulo)", "America/Sao_Paulo"),
    ("Mexico City (America/Mexico_City)", "America/Mexico_City"),
    ("Phoenix (America/Phoenix)", "America/Phoenix"),
    ("Anchorage (America/Anchorage)", "America/Anchorage"),
    ("Honolulu (Pacific/Honolulu)", "Pacific/Honolulu"),
    ("Mumbai (Asia/Kolkata)", "Asia/Kolkata"),
    ("Seoul (Asia/Seoul)", "Asia/Seoul"),
    ("Singapore (Asia/Singapore)", "Asia/Singapore"),
    ("Dubai (Asia/Dubai)", "Asia/Dubai"),
    ("Johannesburg (Africa/Johannesburg)", "Africa/Johannesburg"),
    ("EST (fixed)", "EST"),
    ("CST (fixed)", "CST"),
    ("MST (fixed)", "MST"),
    ("PST (fixed)", "PST"),
]


async def tz_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current_lower = (current or "").lower()
    choices: list[app_commands.Choice[str]] = []
    for name, value in COMMON_TIMEZONES:
        if not current_lower or current_lower in name.lower() or current_lower in value.lower():
            choices.append(app_commands.Choice(name=name, value=value))
        if len(choices) >= 25:
            break
    return choices

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


def get_default_downtime() -> dict[str, Optional[Union[int, str]]]:
    return {"start": None, "end": None, "title": None}


def get_downtime(guild_id: int) -> dict[str, Optional[Union[int, str]]]:
    if guild_id not in current_downtime:
        current_downtime[guild_id] = get_default_downtime()
    return current_downtime[guild_id]






def require_allowed_guild(interaction: discord.Interaction) -> bool:
    if ALLOWED_GUILD_IDS and interaction.guild_id not in ALLOWED_GUILD_IDS:
        raise app_commands.CheckFailure("This bot is restricted to approved servers.")
    return True


def get_bot_member(guild: discord.Guild) -> Optional[discord.Member]:
    if not client.user:
        return None
    return guild.get_member(client.user.id)


def missing_channel_perms(
    channel: discord.abc.GuildChannel, member: discord.Member
) -> list[str]:
    perms = channel.permissions_for(member)
    missing = []
    if not perms.view_channel:
        missing.append("View Channel")
    if not perms.send_messages:
        missing.append("Send Messages")
    if not perms.read_message_history:
        missing.append("Read Message History")
    if isinstance(channel, discord.Thread) and not perms.send_messages_in_threads:
        missing.append("Send Messages in Threads")
    return missing


DOWNTIME_ROLE_NAME = "downtime"


def has_downtime_role(member: discord.Member) -> bool:
    return any(role.name.lower() == DOWNTIME_ROLE_NAME for role in member.roles)


def require_downtime_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.guild_id:
        raise app_commands.CheckFailure("This command can only be used in a server.")
    member = interaction.user
    if isinstance(member, discord.Member):
        if has_downtime_role(member):
            return True
    raise app_commands.CheckFailure("You need the @downtime role to use this command.")


def get_guild_panels(guild_id: int) -> list[dict[str, int]]:
    return [p for p in panel_messages if p.get("guild_id") == guild_id]


async def post_panel_message(channel: discord.abc.Messageable, guild_id: int) -> None:
    embed = get_status_embed(guild_id, full=False)
    message = await channel.send(embed=embed, view=StatusPanel())
    panel_messages.append(
        {"channel_id": message.channel.id, "message_id": message.id, "guild_id": guild_id}
    )
    save_data()









def load_data() -> None:
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        current_downtime.clear()
        downtime_data = data.get("downtime")
        if isinstance(downtime_data, dict):
            for key, value in downtime_data.items():
                try:
                    guild_id = int(key)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    current_downtime[guild_id] = {
                        "start": value.get("start"),
                        "end": value.get("end"),
                        "title": value.get("title"),
                    }
        else:
            # Backward compatibility: previous single-guild format
            legacy_start = data.get("start")
            legacy_end = data.get("end")
            legacy_title = data.get("title")
            if legacy_start or legacy_end or legacy_title:
                target_id: Optional[int] = None
                if len(ALLOWED_GUILD_IDS) == 1:
                    target_id = next(iter(ALLOWED_GUILD_IDS))
                elif len(SYNC_GUILD_IDS) == 1:
                    target_id = SYNC_GUILD_IDS[0]
                elif GUILD_ID and GUILD_ID.isdigit():
                    target_id = int(GUILD_ID)
                if target_id:
                    current_downtime[target_id] = {
                        "start": legacy_start,
                        "end": legacy_end,
                        "title": legacy_title,
                    }
                else:
                    print("Legacy downtime data ignored: no single guild target found.")

        panels = data.get("panels", [])
        panel_messages.clear()
        if isinstance(panels, list):
            for item in panels:
                if not isinstance(item, dict):
                    continue
                channel_id = item.get("channel_id")
                message_id = item.get("message_id")
                guild_id = item.get("guild_id")
                if isinstance(channel_id, int) and isinstance(message_id, int) and isinstance(guild_id, int):
                    panel_messages.append(
                        {"channel_id": channel_id, "message_id": message_id, "guild_id": guild_id}
                    )
                elif isinstance(channel_id, int) and isinstance(message_id, int):
                    # Legacy panel without guild_id; attach if only one known guild
                    target_id = None
                    if len(ALLOWED_GUILD_IDS) == 1:
                        target_id = next(iter(ALLOWED_GUILD_IDS))
                    elif len(SYNC_GUILD_IDS) == 1:
                        target_id = SYNC_GUILD_IDS[0]
                    elif GUILD_ID and GUILD_ID.isdigit():
                        target_id = int(GUILD_ID)
                    if target_id:
                        panel_messages.append(
                            {"channel_id": channel_id, "message_id": message_id, "guild_id": target_id}
                        )

        # Load event panels
        event_panels = data.get("event_panels", [])
        event_panel_messages.clear()
        if isinstance(event_panels, list):
            for item in event_panels:
                if not isinstance(item, dict):
                    continue
                channel_id = item.get("channel_id")
                message_id = item.get("message_id")
                guild_id = item.get("guild_id")
                event_type = item.get("event_type")
                if isinstance(channel_id, int) and isinstance(message_id, int) and isinstance(guild_id, int) and isinstance(event_type, str):
                    event_panel_messages.append({
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "guild_id": guild_id,
                        "event_type": event_type
                    })
    except Exception as exc:
        print(f"Failed to load {DATA_FILE}: {exc!r}")


def save_data() -> None:
    data = {
        "downtime": {str(gid): info for gid, info in current_downtime.items()},
        "panels": panel_messages,
        "event_panels": event_panel_messages,
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
    # Accept GMT/UTC offsets like "GMT-05:00" or "UTC +05:30"
    for raw in (tz_name, tz_fallback or ""):
        raw = (raw or "").strip().upper()
        match = re.fullmatch(r"(GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", raw)
        if match:
            sign = -1 if match.group(2) == "-" else 1
            hours = int(match.group(3))
            minutes = int(match.group(4) or 0)
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                offset = timedelta(hours=hours, minutes=minutes) * sign
                return timezone(offset)
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
    cleaned = time_str.strip()
    # Normalize common unicode spaces to regular space
    cleaned = cleaned.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2009", " ")
    # Normalize common unicode punctuation
    cleaned = cleaned.translate(
        {
            ord("／"): "/",
            ord("∕"): "/",
            ord("⁄"): "/",
            ord("："): ":",
        }
    )
    cleaned = cleaned.replace(",", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Replace dot time separators (e.g., 2.15 PM -> 2:15 PM)
    cleaned = cleaned.replace(".", ":")
    # If date and time are separated by a colon or dash, normalize to space (e.g., 2/12:2:15 PM)
    cleaned = re.sub(r"^(\d{1,2}[/-]\d{1,2})\s*[:\-]\s*", r"\1 ", cleaned)
    # Ensure space before AM/PM if missing (e.g., 9:48PM -> 9:48 PM)
    cleaned = re.sub(r"(?i)(\d)(am|pm)$", r"\1 \2", cleaned)
    if cleaned.upper().endswith(("AM", "PM")) and " " not in cleaned[-3:]:
        cleaned = cleaned[:-2] + " " + cleaned[-2:]
    return cleaned


def parse_time_info(
    time_str: str, tzinfo: Union[timezone, ZoneInfo]
) -> tuple[Optional[datetime], Optional[datetime], bool]:
    """Parse time string. Returns (local_dt, utc_dt, is_time_only)."""
    formats = [
        # Full formats with 4-digit year
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I %p",
        # 2-digit year formats (e.g., 2/1/26 2:30 PM)
        "%m/%d/%y %H:%M",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%y %I %p",
        "%m/%d/%y %I%p",  # No space before AM/PM (2/1/26 4pm)
        # Month/day without year
        "%m/%d %H:%M",
        "%m/%d %I:%M %p",
        "%m/%d %I %p",
        "%m/%d %I%p",  # No space before AM/PM (2/1 4pm)
        # Time-only formats
        "%H:%M",
        "%I:%M %p",
        "%I %p",
        "%I%p",  # No space before AM/PM (4pm)
    ]
    
    now_local = datetime.now(tzinfo)
    normalized = normalize_time_input(time_str)

    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            # Determine if this is a time-only format (no date component)
            time_only = fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I%p")

            if time_only:
                # For time-only, fill in today's date
                parsed = parsed.replace(year=now_local.year, month=now_local.month, day=now_local.day)
            elif fmt in ("%m/%d %H:%M", "%m/%d %I:%M %p", "%m/%d %I %p", "%m/%d %I%p"):
                # For month/day without year, fill in current year
                parsed = parsed.replace(year=now_local.year)

            parsed = parsed.replace(tzinfo=tzinfo)
            return parsed, parsed.astimezone(timezone.utc), time_only
        except ValueError:
            continue
    # Helpful debug in logs when parsing fails
    if os.getenv("DEBUG_TIME_PARSE", "").strip() == "1":
        print(f"Time parse failed: raw={time_str!r} normalized={normalized!r}")
    return None, None, False


async def apply_downtime(
    interaction: discord.Interaction,
    start: str,
    end: str,
    tz: str,
    title: Optional[str],
    guild_id: Optional[int],
) -> None:
    if not guild_id:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return
    tz_resolved = resolve_timezone(tz)
    tzinfo = get_tzinfo(tz_resolved, tz_fallback=tz)
    if not tzinfo:
        await interaction.response.send_message(
            f"{HEART_EMOJI} **Invalid timezone**\n\n"
            "**Common timezones:**\n"
            "• `EST`, `CST`, `MST`, `PST` (US)\n"
            "• `UTC`, `GMT`\n"
            "• `America/New_York`, `Europe/London`\n"
            "• `GMT-05:00`, `UTC+05:30` (offset format)\n\n"
            f"**Your input:** `{tz}`\n\n"
            "💡 **Windows users:** Install `tzdata` for full timezone support:\n"
            "`pip install tzdata`",
            ephemeral=True,
        )
        return

    start_local, start_dt, start_time_only = parse_time_info(start, tzinfo)
    end_local, end_dt, end_time_only = parse_time_info(end, tzinfo)

    if not start_dt or not end_dt:
        await interaction.response.send_message(
            f"{HEART_EMOJI} **Invalid time format**\n\n"
            "**Supported formats:**\n"
            "• `2/1/2026 2:30 PM` (full date with 4-digit year)\n"
            "• `2/1/26 2:30 PM` (2-digit year)\n"
            "• `2/1 2:30 PM` (month/day, current year)\n"
            "• `2:30 PM` (time only, today's date)\n"
            "• `4pm` (casual time format)\n\n"
            "**Your input:**\n"
            f"Start: `{start}`\n"
            f"End: `{end}`",
            ephemeral=True,
        )
        return

    # If both inputs are time-only and end is earlier, assume it crosses midnight.
    if start_time_only and end_time_only and start_local and end_local and end_local <= start_local:
        end_local = end_local + timedelta(days=1)
        end_dt = end_local.astimezone(timezone.utc)

    if end_dt <= start_dt:
        await interaction.response.send_message(
            f"{HEART_EMOJI} **End time must be after start time**\n\n"
            f"Start: <t:{int(start_dt.timestamp())}:f>\n"
            f"End: <t:{int(end_dt.timestamp())}:f>\n\n"
            "Please check your times and try again.",
            ephemeral=True
        )
        return

    final_title = (title or "").strip() or "Scheduled Maintenance"

    downtime = get_downtime(guild_id)
    downtime["start"] = int(start_dt.timestamp())
    downtime["end"] = int(end_dt.timestamp())
    downtime["title"] = final_title
    save_data()
    await update_panels(guild_id)

    await interaction.response.send_message(
        f"{HEART_EMOJI} Downtime set: {final_title}\n"
        f"Start: <t:{downtime['start']}:f>\n"
        f"End: <t:{downtime['end']}:f>\n"
        f"(Entered in {tz_resolved})",
        ephemeral=True,
    )


async def update_panels(target_guild_id: Optional[int] = None) -> None:
    if not panel_messages:
        return
    stale: list[dict[str, int]] = []
    for item in panel_messages:
        guild_id = item.get("guild_id")
        if target_guild_id and guild_id != target_guild_id:
            continue
        channel_id = item.get("channel_id")
        message_id = item.get("message_id")
        if not channel_id or not message_id or not guild_id:
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
            embed = get_status_embed(guild_id, full=False)
            await message.edit(embed=embed, view=StatusPanel())
        except Exception:
            stale.append(item)
    if stale:
        for item in stale:
            if item in panel_messages:
                panel_messages.remove(item)
        save_data()


async def post_event_panel_message(channel: discord.abc.Messageable, guild_id: int, event_type: str) -> None:
    """Post an event panel for a specific event type."""
    embed = get_event_embed(event_type, guild_id)
    message = await channel.send(embed=embed)
    event_panel_messages.append({
        "channel_id": message.channel.id,
        "message_id": message.id,
        "guild_id": guild_id,
        "event_type": event_type
    })
    save_data()


async def update_event_panels(target_guild_id: Optional[int] = None) -> None:
    """Update all event panels with current event data."""
    if not event_panel_messages:
        return
    stale: list[dict[str, Union[int, str]]] = []
    for item in event_panel_messages:
        guild_id = item.get("guild_id")
        if target_guild_id and guild_id != target_guild_id:
            continue
        channel_id = item.get("channel_id")
        message_id = item.get("message_id")
        event_type = item.get("event_type")
        if not channel_id or not message_id or not guild_id or not event_type:
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
            embed = get_event_embed(str(event_type), int(guild_id))
            await message.edit(embed=embed)
        except Exception:
            stale.append(item)
    if stale:
        for item in stale:
            if item in event_panel_messages:
                event_panel_messages.remove(item)
        save_data()


async def event_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for event types."""
    current_lower = (current or "").lower()
    choices: list[app_commands.Choice[str]] = []
    for event_type, config in EVENT_TYPE_CONFIG.items():
        display = config["display_name"]
        if not current_lower or current_lower in event_type.lower() or current_lower in display.lower():
            choices.append(app_commands.Choice(name=f"{config['emoji']} {display}", value=event_type))
        if len(choices) >= 25:
            break
    return choices


def get_status_embed(guild_id: Optional[int], full: bool = False) -> discord.Embed:
    """Build status embed. full=True for detailed view, False for panel."""

    downtime = get_default_downtime() if not guild_id else get_downtime(guild_id)

    if not downtime["start"]:
        embed = discord.Embed(
            title=f"{ONLINE_EMOJI} Server Status",
            description="No maintenance scheduled.",
            color=ONLINE_COLOR
        )
        return embed
    
    now = datetime.now(timezone.utc).timestamp()
    start_ts = downtime["start"]
    end_ts = downtime["end"]
    title = downtime["title"] or "Scheduled Maintenance"
    
    if now < start_ts:
        status = f"{ONLINE_EMOJI} ONLINE"
        color = ONLINE_COLOR
        remaining = format_remaining(int(end_ts - now))
        details = (
            f"**Upcoming Maintenance:** {title}\n\n"
            f"{TIME_EMOJI} Game back online in: **{remaining}**\n"
            f"{TIME_EMOJI} Downtime begins: <t:{start_ts}:R>\n"
            f"{TIME_EMOJI} Start: <t:{start_ts}:f>\n"
            f"{TIME_EMOJI} End: <t:{end_ts}:f>"
        ) if full else f"Maintenance scheduled <t:{start_ts}:R>"
    elif now < end_ts:
        status = f"{MAINT_EMOJI} MAINTENANCE"
        color = MAINT_COLOR
        remaining = format_remaining(int(end_ts - now))
        details = (
            f"**{title}**\n\n"
            f"{TIME_EMOJI} Game back online in: **{remaining}**\n"
            f"{TIME_EMOJI} Maintenance ends at: <t:{end_ts}:f>"
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
    else:
        embed.set_footer(text="Times shown in your local timezone")
    
    return embed


def format_remaining(seconds: int) -> str:
    if seconds <= 0:
        return "0 minutes"
    minutes_total = seconds // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes or not parts:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts)


def parse_duration_minutes(raw: str) -> Optional[int]:
    text = (raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", text)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    if total <= 0:
        return None
    return total


# ============ EVENT FUNCTIONS ============
def get_events_by_type(event_type: str) -> list[dict]:
    """Filter events by type and return only active/upcoming events."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    filtered = [
        event for event in EVENTS
        if event["type"] == event_type and event["end"] > now_ts
    ]
    return sorted(filtered, key=lambda x: x["start"])


def get_event_status(start_ts: int, end_ts: int, now_ts: int) -> str:
    """Determine event status indicator based on timestamps."""
    if now_ts < start_ts:
        time_until = start_ts - now_ts
        if time_until <= 86400:  # 24 hours
            return "🟡 Starting Soon"
        return "🔵 Upcoming"
    elif now_ts < end_ts:
        time_remaining = end_ts - now_ts
        if time_remaining <= 172800:  # 48 hours
            return "🟠 Ending Soon"
        return "🟢 Active"
    else:
        return "⚫ Ended"


def format_event_entry(event: dict, now_ts: int) -> str:
    """Format a single event entry for embed description."""
    status = get_event_status(event["start"], event["end"], now_ts)
    name = event["name"]
    end_ts = event["end"]
    start_ts = event["start"]
    rewards = event.get("rewards", "N/A")
    url = event.get("url", "")

    # Build the entry
    lines = [f"**{status}: {name}**"]

    # Show appropriate timestamp based on status
    if now_ts < start_ts:
        # Upcoming - show when it starts
        lines.append(f"Starts: <t:{start_ts}:R> • <t:{start_ts}:F>")
        lines.append(f"Ends: <t:{end_ts}:F>")
    else:
        # Active - show when it ends
        lines.append(f"Ends: <t:{end_ts}:R> • <t:{end_ts}:F>")

    lines.append(f"**Rewards:** {rewards}")

    if url:
        lines.append(f"🔗 [Wiki Guide]({url})")

    return "\n".join(lines)


def get_event_embed(event_type: str, guild_id: Optional[int] = None) -> discord.Embed:
    """Build embed for a specific event type showing all active/upcoming events."""
    config = EVENT_TYPE_CONFIG.get(event_type)
    if not config:
        # Fallback if unknown type
        config = {"emoji": "📌", "color": discord.Color.blurple(), "display_name": "Event"}

    events = get_events_by_type(event_type)
    now_ts = int(datetime.now(timezone.utc).timestamp())

    # Build title
    emoji = config["emoji"]
    display_name = config["display_name"]
    title = f"{emoji} {display_name}s"

    # Build description
    if not events:
        description = f"No active or upcoming {display_name.lower()}s at this time.\n\nCheck back later for new events!"
    else:
        entries = [format_event_entry(event, now_ts) for event in events]
        description = "\n\n──────────────────────\n\n".join(entries)

    embed = discord.Embed(
        title=title,
        description=description,
        color=config["color"]
    )
    embed.set_footer(text="Infinity Nikki - Event Calendar")

    return embed


def get_all_events_embed(event_type_filter: Optional[str] = None) -> discord.Embed:
    """Build embed showing all active/upcoming events, optionally filtered by type."""
    if event_type_filter:
        return get_event_embed(event_type_filter)

    now_ts = int(datetime.now(timezone.utc).timestamp())
    all_events = [e for e in EVENTS if e["end"] > now_ts]

    if not all_events:
        embed = discord.Embed(
            title="📅 All Events",
            description="No active or upcoming events at this time.\n\nCheck back later!",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Infinity Nikki - Event Calendar")
        return embed

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for event in all_events:
        event_type = event["type"]
        if event_type not in by_type:
            by_type[event_type] = []
        by_type[event_type].append(event)

    # Build description with sections per type
    sections = []
    for event_type, events in sorted(by_type.items()):
        config = EVENT_TYPE_CONFIG.get(event_type, {"emoji": "📌", "display_name": "Event"})
        emoji = config["emoji"]
        display_name = config["display_name"]

        section_lines = [f"**{emoji} {display_name}s**"]
        for event in sorted(events, key=lambda x: x["start"]):
            status = get_event_status(event["start"], event["end"], now_ts)
            name = event["name"]
            end_ts = event["end"]
            section_lines.append(f"{status}: {name} • Ends <t:{end_ts}:R>")

        sections.append("\n".join(section_lines))

    description = "\n\n".join(sections)

    embed = discord.Embed(
        title="📅 All Events",
        description=description,
        color=discord.Color.from_rgb(255, 200, 220)
    )
    embed.set_footer(text="Infinity Nikki - Event Calendar • Use /eventpanel to post detailed panels")

    return embed


def get_overview_embed() -> discord.Embed:
    """Build compact overview embed showing all events grouped by category."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    all_events = [e for e in EVENTS if e["end"] > now_ts]

    if not all_events:
        embed = discord.Embed(
            title="📅 Event Overview",
            description="No active or upcoming events at this time.\n\nCheck back later!",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Infinity Nikki - Event Calendar")
        return embed

    # Group events into categories
    resonance_events = [e for e in all_events if e["type"] == "resonance"]
    limited_events = [e for e in all_events if e["type"] in ["task", "quest", "checkin", "doublerewards"]]
    store_recurring = [e for e in all_events if e["type"] in ["store", "recurring"]]

    # Helper to format compact event line
    def format_compact_event(event: dict) -> str:
        config = EVENT_TYPE_CONFIG.get(event["type"], {"emoji": "📌"})
        emoji = config["emoji"]
        name = event["name"]

        # Extract short description from the description field
        desc = event.get("description", "")

        # For specific event types, extract key info
        if event["type"] == "resonance":
            # Extract outfit name from description (e.g., "5★ outfit Where Wanxiang Weaves Life")
            if "5★ outfit " in desc:
                outfit = desc.split("5★ outfit ")[1].split(",")[0]
                return f"{emoji} {name} - 5★ {outfit}"
        elif event["type"] == "task":
            # Extract outfit from description
            if "4★ outfit " in desc:
                outfit = desc.split("4★ outfit ")[1].split("\n")[0]
                return f"{emoji} {name} (Task) - 4★ {outfit}"
        elif event["type"] == "quest":
            # Simple format for collection events
            return f"{emoji} {name} (Collection) - Diamonds + Card"
        elif event["type"] == "checkin":
            # Extract reward amount
            rewards = event.get("rewards", "")
            return f"{emoji} {name} (Check-in) - {rewards}"
        elif event["type"] == "doublerewards":
            # Short description
            return f"{emoji} {name} (Double Rewards) - Weekly double realm rewards"
        elif event["type"] == "store":
            # Battle Pass
            return f"{emoji} {name.replace(' (Battle Pass)', '')} - Battle Pass (Level 90 rewards)"
        elif event["type"] == "recurring":
            # Extract time info from description
            if "Daily reset" in desc:
                return f"{emoji} {name} - 04:00 server time"
            elif "Weekly reset" in desc:
                return f"{emoji} {name} - Monday 04:00 server time"

        # Fallback
        return f"{emoji} {name} - {desc[:50]}"

    # Build description sections
    sections = []

    if resonance_events:
        count = len(resonance_events)
        lines = [f"**Resonance Events ({count})**"]
        for event in sorted(resonance_events, key=lambda x: x["start"]):
            lines.append(format_compact_event(event))
        sections.append("\n".join(lines))

    if limited_events:
        count = len(limited_events)
        lines = [f"**Limited Events ({count})**"]
        for event in sorted(limited_events, key=lambda x: x["start"]):
            lines.append(format_compact_event(event))
        sections.append("\n".join(lines))

    if store_recurring:
        count = len(store_recurring)
        lines = [f"**Store/Recurring ({count})**"]
        for event in sorted(store_recurring, key=lambda x: x["start"]):
            lines.append(format_compact_event(event))
        sections.append("\n".join(lines))

    description = "\n\n".join(sections)

    embed = discord.Embed(
        title="📅 Event Overview",
        description=description,
        color=discord.Color.from_rgb(255, 200, 220)
    )
    embed.set_footer(text="Infinity Nikki - Event Calendar • Use /events for detailed info")

    return embed


# ============ BUTTON VIEW ============
class StatusPanel(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label=BUTTON_LABEL, style=discord.ButtonStyle.primary, emoji=HEART_EMOJI, custom_id="check_status")
    async def check_status(self, interaction: discord.Interaction, button: ui.Button):
        if ALLOWED_GUILD_IDS and interaction.guild_id not in ALLOWED_GUILD_IDS:
            await interaction.response.send_message(
                "This bot is restricted to approved servers.",
                ephemeral=True,
            )
            return
        embed = get_status_embed(interaction.guild_id, full=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)



# ============ EVENTS ============
@client.event
async def on_guild_join(guild: discord.Guild):
    if ALLOWED_GUILD_IDS and guild.id not in ALLOWED_GUILD_IDS:
        await guild.leave()


@client.event
async def on_ready():
    client.add_view(StatusPanel())
    load_data()

    # Check for tzdata on Windows
    import platform
    if platform.system() == "Windows":
        try:
            import tzdata
            print("✓ tzdata is installed (full timezone support available)")
        except ImportError:
            print("\n" + "="*60)
            print("⚠️  WARNING: tzdata is not installed!")
            print("   Windows requires tzdata for full timezone support.")
            print("   Install it with: pip install tzdata")
            print("   Without it, only GMT offset timezones (e.g., GMT-05:00) will work.")
            print("="*60 + "\n")

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
    await update_event_panels()
    print(f"Bot is online as {client.user}")


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the Manage Server permission to use this command."
    elif isinstance(error, app_commands.CheckFailure):
        message = str(error) if str(error) else "You don't have permission to use this command."
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
@tree.command(name="downtime", description="[MOD] Set a maintenance window")
@app_commands.describe(
    start="Start time (e.g., 2/1/26 2:30 PM or 4pm)",
    end="End time (same formats)",
    tz="Timezone (autocomplete)",
    title="Optional custom title"
)
@app_commands.autocomplete(tz=tz_autocomplete)
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def downtime(
    interaction: discord.Interaction,
    start: str,
    end: str,
    tz: Optional[str] = "UTC",
    title: str = "Scheduled Maintenance",
):
    """Set downtime with inline parameters."""
    await apply_downtime(interaction, start, end, tz or "UTC", title, interaction.guild_id)


@tree.command(name="panel", description="[MOD] Post the status panel in this channel")
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def post_panel(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    await post_panel_message(interaction.channel, interaction.guild_id)
    await interaction.response.send_message("Panel posted.", ephemeral=True)


@tree.command(name="cleardowntime", description="[MOD] Clear scheduled downtime")
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def cleardowntime(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    downtime = get_downtime(interaction.guild_id)
    downtime["start"] = None
    downtime["end"] = None
    downtime["title"] = None
    save_data()
    await update_panels(interaction.guild_id)
    await interaction.response.send_message("Downtime cleared.", ephemeral=True)


@tree.command(name="extenddowntime", description="[MOD] Extend the downtime end time")
@app_commands.describe(
    new_end="New end time (e.g., 2/1/26 6pm) OR +duration (e.g., +2h)",
    tz="Timezone (autocomplete)"
)
@app_commands.autocomplete(tz=tz_autocomplete)
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def extenddowntime(
    interaction: discord.Interaction,
    new_end: str,
    tz: Optional[str] = "UTC"
):
    """Extend the current downtime by changing the end time."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    downtime = get_downtime(interaction.guild_id)
    if not downtime.get("start") or not downtime.get("end"):
        await interaction.response.send_message(
            f"{HEART_EMOJI} **No active downtime to extend**\n\n"
            "Use `/downtime` to set a new downtime window.",
            ephemeral=True,
        )
        return

    tz_resolved = resolve_timezone(tz or "UTC")
    tzinfo = get_tzinfo(tz_resolved, tz_fallback=tz)

    if not tzinfo:
        await interaction.response.send_message(
            f"{HEART_EMOJI} **Invalid timezone**\n\n"
            "**Common timezones:**\n"
            "• `EST`, `CST`, `MST`, `PST`\n"
            "• `UTC`, `America/New_York`\n"
            "• `GMT-05:00` (offset format)\n\n"
            f"**Your input:** `{tz}`",
            ephemeral=True,
        )
        return

    new_end_str = new_end.strip()

    # Check if it's a relative duration (starts with +)
    if new_end_str.startswith('+'):
        duration_str = new_end_str[1:].strip()
        duration_minutes = parse_duration_minutes(duration_str)

        if duration_minutes is None:
            await interaction.response.send_message(
                f"{HEART_EMOJI} **Invalid duration format**\n\n"
                "**Examples:** `+2h`, `+1h30m`, `+30m`\n\n"
                f"**Your input:** `{new_end_str}`",
                ephemeral=True,
            )
            return

        current_end_dt = datetime.fromtimestamp(downtime["end"], tz=timezone.utc)
        new_end_dt = current_end_dt + timedelta(minutes=duration_minutes)
    else:
        # Parse as absolute time
        _, new_end_dt, _ = parse_time_info(new_end_str, tzinfo)

        if not new_end_dt:
            await interaction.response.send_message(
                f"{HEART_EMOJI} **Invalid time format**\n\n"
                "**Examples:** `2/1/2026 6pm`, `2/1/26 6:00 PM`, `+2h`\n\n"
                f"**Your input:** `{new_end_str}`",
                ephemeral=True,
            )
            return

    # Validate new end time is after start time
    start_dt = datetime.fromtimestamp(downtime["start"], tz=timezone.utc)
    if new_end_dt <= start_dt:
        await interaction.response.send_message(
            f"{HEART_EMOJI} **New end time must be after start time**\n\n"
            f"Start: <t:{downtime['start']}:f>\n"
            f"New End: <t:{int(new_end_dt.timestamp())}:f>",
            ephemeral=True
        )
        return

    # Update downtime
    old_end = downtime["end"]
    downtime["end"] = int(new_end_dt.timestamp())
    save_data()
    await update_panels(interaction.guild_id)

    await interaction.response.send_message(
        f"{HEART_EMOJI} **Downtime extended!**\n\n"
        f"Previous End: <t:{old_end}:f>\n"
        f"New End: <t:{downtime['end']}:f>",
        ephemeral=True,
    )

    print(f"✓ Downtime extended by {interaction.user} in {interaction.guild}: "
          f"New end: <t:{downtime['end']}:f> ({tz_resolved})")


@tree.command(name="status", description="Check server status")
@app_commands.check(require_allowed_guild)
async def status(interaction: discord.Interaction):
    """Check the current server status."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    embed = get_status_embed(interaction.guild_id, full=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="eventpanel", description="[MOD] Post an event panel in this channel")
@app_commands.describe(event_type="Event type to display (e.g., resonance, quest, task)")
@app_commands.autocomplete(event_type=event_type_autocomplete)
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def post_event_panel_cmd(interaction: discord.Interaction, event_type: str):
    """Post an event panel for a specific event type."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Validate event type
    if event_type not in EVENT_TYPE_CONFIG:
        valid_types = ", ".join(EVENT_TYPE_CONFIG.keys())
        await interaction.response.send_message(
            f"{HEART_EMOJI} **Invalid event type**\n\n"
            f"Valid types: {valid_types}",
            ephemeral=True
        )
        return

    await post_event_panel_message(interaction.channel, interaction.guild_id, event_type)
    config = EVENT_TYPE_CONFIG[event_type]
    await interaction.response.send_message(
        f"{config['emoji']} Event panel posted for **{config['display_name']}s**!",
        ephemeral=True
    )


@tree.command(name="postallevents", description="[MOD] Post all event panels in this channel")
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def post_all_events_cmd(interaction: discord.Interaction):
    """Post panels for all event types that have active/upcoming events."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # Get all event types that have active events
    now_ts = int(datetime.now(timezone.utc).timestamp())
    active_types = set()
    for event in EVENTS:
        if event["end"] > now_ts:  # Active or upcoming
            active_types.add(event["type"])

    # Post panels in a logical order
    order = ["resonance", "quest", "task", "checkin", "doublerewards", "web", "store", "recurring"]
    posted_count = 0

    for event_type in order:
        if event_type in active_types:
            await post_event_panel_message(interaction.channel, interaction.guild_id, event_type)
            posted_count += 1

    await interaction.followup.send(
        f"{HEART_EMOJI} Posted **{posted_count}** event panels!",
        ephemeral=True
    )


@tree.command(name="updateevents", description="[MOD] Manually update all event panels")
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def update_events_cmd(interaction: discord.Interaction):
    """Manually trigger event panel updates."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await update_event_panels(interaction.guild_id)
    await interaction.followup.send(
        f"{HEART_EMOJI} Event panels updated successfully!",
        ephemeral=True
    )


@tree.command(name="overview", description="View compact overview of all active events")
@app_commands.check(require_allowed_guild)
async def view_overview(interaction: discord.Interaction):
    """View compact overview of all events grouped by category."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    embed = get_overview_embed()
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="events", description="View all active and upcoming events")
@app_commands.describe(event_type="Optional: Filter by event type")
@app_commands.autocomplete(event_type=event_type_autocomplete)
@app_commands.check(require_allowed_guild)
async def view_events(interaction: discord.Interaction, event_type: Optional[str] = None):
    """View all events or filter by type."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Validate event type if provided
    if event_type and event_type not in EVENT_TYPE_CONFIG:
        valid_types = ", ".join(EVENT_TYPE_CONFIG.keys())
        await interaction.response.send_message(
            f"{HEART_EMOJI} **Invalid event type**\n\n"
            f"Valid types: {valid_types}",
            ephemeral=True
        )
        return

    embed = get_all_events_embed(event_type)
    await interaction.response.send_message(embed=embed, ephemeral=True)


if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")

client.run(BOT_TOKEN)
