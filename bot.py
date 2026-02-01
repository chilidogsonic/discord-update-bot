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
    except Exception as exc:
        print(f"Failed to load {DATA_FILE}: {exc!r}")


def save_data() -> None:
    data = {
        "downtime": {str(gid): info for gid, info in current_downtime.items()},
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
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Replace dot time separators (e.g., 2.15 PM -> 2:15 PM)
    cleaned = cleaned.replace(".", ":")
    # If date and time are separated by a colon, normalize to space (e.g., 2/12:2:15 PM)
    cleaned = re.sub(r"^(\d{1,2}/\d{1,2})\s*[:\-]\s*", r"\1 ", cleaned)
    if cleaned.upper().endswith(("AM", "PM")) and " " not in cleaned[-3:]:
        # Convert 9:48AM -> 9:48 AM
        cleaned = cleaned[:-2] + " " + cleaned[-2:]
    return cleaned


def parse_time_info(
    time_str: str, tzinfo: Union[timezone, ZoneInfo]
) -> tuple[Optional[datetime], Optional[datetime], bool]:
    """Parse time string. Returns (local_dt, utc_dt, is_time_only)."""
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I %p",
        "%m/%d %H:%M",
        "%m/%d %I:%M %p",
        "%m/%d %I %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I %p",
        "%H:%M",
        "%I:%M %p",
        "%I %p",
    ]
    
    now_local = datetime.now(tzinfo)
    normalized = normalize_time_input(time_str)

    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            time_only = fmt in ("%H:%M", "%I:%M %p")
            if time_only:
                parsed = parsed.replace(year=now_local.year, month=now_local.month, day=now_local.day)
            elif fmt == "%m/%d %H:%M":
                parsed = parsed.replace(year=now_local.year)
            elif fmt == "%m/%d %I:%M %p":
                parsed = parsed.replace(year=now_local.year)
            
            parsed = parsed.replace(tzinfo=tzinfo)
            return parsed, parsed.astimezone(timezone.utc), time_only
        except ValueError:
            continue
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
            "Invalid timezone.\n"
            "Examples: `EST`, `PST`, `UTC`, `America/New_York`\n"
            "Or use GMT offsets like `GMT -05:00` / `GMT+05:30`.\n"
            "Reference: https://greenwichmeantime.com/current-time/\n"
            "Note: On Windows, install `tzdata` (pip install tzdata) for full IANA support.",
            ephemeral=True,
        )
        return

    start_local, start_dt, start_time_only = parse_time_info(start, tzinfo)
    end_local, end_dt, end_time_only = parse_time_info(end, tzinfo)

    if not start_dt or not end_dt:
        await interaction.response.send_message(
            "Invalid time format.\n"
            "Formats: `HH:MM`, `HH:MM AM`, `MM/DD HH:MM`, `MM/DD HH:MM AM`, "
            "`MM/DD/YYYY HH:MM`, `YYYY-MM-DD HH:MM`",
            ephemeral=True,
        )
        return

    # If both inputs are time-only and end is earlier, assume it crosses midnight.
    if start_time_only and end_time_only and start_local and end_local and end_local <= start_local:
        end_local = end_local + timedelta(days=1)
        end_dt = end_local.astimezone(timezone.utc)

    if end_dt <= start_dt:
        await interaction.response.send_message("End time must be after start time.", ephemeral=True)
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


SETUP_TIMEOUT_SECONDS = 180


async def prompt_user_message(
    channel: discord.abc.Messageable,
    user: Union[discord.User, discord.Member],
    prompt: str,
) -> tuple[str, str]:
    await channel.send(f"{user.mention} {prompt}")

    def check(message: discord.Message) -> bool:
        return message.author.id == user.id and message.channel.id == channel.id

    try:
        msg = await client.wait_for("message", check=check, timeout=SETUP_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return "timeout", ""

    content = msg.content.strip()
    lowered = content.lower()
    if lowered == "cancel":
        return "cancel", ""
    if lowered == "skip":
        return "skip", ""
    if lowered in {"none", "clear"}:
        return "none", ""
    return "value", content


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


    async def on_submit(self, interaction: discord.Interaction):
        tz_value = (self.tz_input.value or "").strip() or "UTC"
        title_value = (self.title_input.value or "").strip() or "Scheduled Maintenance"
        await apply_downtime(
            interaction,
            self.start_input.value,
            self.end_input.value,
            tz_value,
            title_value,
            interaction.guild_id,
        )



# ============ EVENTS ============
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
@tree.command(name="setdowntime", description="[MOD] Set a maintenance window")
@app_commands.describe(
    start="Start time (HH:MM, HH:MM AM, MM/DD HH:MM, MM/DD/YYYY HH:MM, or YYYY-MM-DD HH:MM)",
    end="End time (same formats)",
    tz="Timezone (autocomplete or GMT offset like GMT-05:00)",
    title="Optional custom title"
)
@app_commands.autocomplete(tz=tz_autocomplete)
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def setdowntime(
    interaction: discord.Interaction,
    start: str,
    end: str,
    tz: Optional[str] = "UTC",
    title: str = "Scheduled Maintenance",
):
    await apply_downtime(interaction, start, end, tz or "UTC", title, interaction.guild_id)

@tree.command(name="setdowntimechat", description="[MOD] Guided setup in chat")
@app_commands.check(require_allowed_guild)
@app_commands.check(require_downtime_role)
async def setdowntimechat(interaction: discord.Interaction):
    if not interaction.guild or not interaction.guild_id or not interaction.channel:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    bot_member = get_bot_member(interaction.guild)
    if not bot_member:
        await interaction.response.send_message("Bot member not found. Try again in a moment.", ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.abc.GuildChannel):
        await interaction.response.send_message("Please run this in a server text channel.", ephemeral=True)
        return

    missing = missing_channel_perms(interaction.channel, bot_member)
    if missing:
        await interaction.response.send_message(
            "I can't run the chat setup here. Missing permissions: "
            + ", ".join(missing),
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "Downtime setup started. Reply in this channel. Type `skip` to keep defaults or `cancel` to abort.",
        ephemeral=False,
    )

    channel = interaction.channel
    user = interaction.user

    # Step 1: timezone
    tz_resolved = "UTC"
    while True:
        prompt = (
            "Timezone? (e.g., America/New_York, EST). You can also use GMT offsets like "
            "`GMT -05:00` or `GMT+05:30`. Reference: https://greenwichmeantime.com/current-time/ "
            "Reply `skip` for UTC."
        )
        status, value = await prompt_user_message(channel, user, prompt)
        if status == "timeout":
            await channel.send(f"{user.mention} Setup timed out.")
            return
        if status == "cancel":
            await channel.send(f"{user.mention} Setup cancelled.")
            return
        if status == "skip":
            tz_resolved = "UTC"
            break
        tz_candidate = resolve_timezone(value)
        tzinfo = get_tzinfo(tz_candidate, tz_fallback=value)
        if not tzinfo:
            await channel.send(f"{user.mention} Invalid timezone. Try again.")
            continue
        tz_resolved = tz_candidate
        break

    tzinfo = get_tzinfo(tz_resolved, tz_fallback=tz_resolved)
    if not tzinfo:
        await channel.send(f"{user.mention} Invalid timezone. Aborting.")
        return

    # Step 2: start time (optional)
    while True:
        prompt = "Start time? (e.g., 9:00 PM, 2 PM, 2/15 2:15 PM) or `skip` for now."
        status, value = await prompt_user_message(channel, user, prompt)
        if status == "timeout":
            await channel.send(f"{user.mention} Setup timed out.")
            return
        if status == "cancel":
            await channel.send(f"{user.mention} Setup cancelled.")
            return
        if status == "skip":
            start_local = datetime.now(tzinfo)
            start_dt = start_local.astimezone(timezone.utc)
            break
        start_local, start_dt, _ = parse_time_info(value, tzinfo)
        if not start_dt or not start_local:
            await channel.send(f"{user.mention} Invalid start time. Try again.")
            continue
        break

    # Step 3: end time OR duration
    while True:
        prompt = "End time or duration? (e.g., 11:00 PM, 2/15 11 PM OR 2h30m)"
        status, value = await prompt_user_message(channel, user, prompt)
        if status == "timeout":
            await channel.send(f"{user.mention} Setup timed out.")
            return
        if status == "cancel":
            await channel.send(f"{user.mention} Setup cancelled.")
            return
        if status in {"skip", "none"}:
            await channel.send(f"{user.mention} Please provide an end time or duration.")
            continue

        duration_minutes = parse_duration_minutes(value)
        if duration_minutes is not None:
            end_local = start_local + timedelta(minutes=duration_minutes)
            end_dt = end_local.astimezone(timezone.utc)
            break

        end_local, end_dt, end_time_only = parse_time_info(value, tzinfo)
        if not end_dt or not end_local:
            await channel.send(f"{user.mention} Invalid end time or duration. Try again.")
            continue
        if end_time_only and end_local <= start_local:
            end_local = end_local + timedelta(days=1)
            end_dt = end_local.astimezone(timezone.utc)
        break

    if end_dt <= start_dt:
        await channel.send(f"{user.mention} End time must be after start time.")
        return

    # Step 4: title (optional)
    title_value = "Scheduled Maintenance"
    prompt = "Title? (optional - `skip` for default)"
    status, value = await prompt_user_message(channel, user, prompt)
    if status == "timeout":
        await channel.send(f"{user.mention} Setup timed out.")
        return
    if status == "cancel":
        await channel.send(f"{user.mention} Setup cancelled.")
        return
    if status == "value" and value.strip():
        title_value = value.strip()

    downtime = get_downtime(interaction.guild_id)
    downtime["start"] = int(start_dt.timestamp())
    downtime["end"] = int(end_dt.timestamp())
    downtime["title"] = title_value
    save_data()
    await update_panels(interaction.guild_id)

    await channel.send(
        f"{user.mention} Downtime set: {title_value}\n"
        f"Start: <t:{downtime['start']}:f>\n"
        f"End: <t:{downtime['end']}:f>\n"
        f"Times shown in your local timezone."
    )




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


# ============ PUBLIC COMMAND ============
@tree.command(name="status", description="Check server status (only you can see)")
@app_commands.check(require_allowed_guild)
async def status(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    embed = get_status_embed(interaction.guild_id, full=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


if not BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")

client.run(BOT_TOKEN)
