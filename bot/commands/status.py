# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT STATUS COMMAND HANDLER                     ║
# ║    Provides system health and calendar status dashboard for admins        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import discord
from discord import Interaction
import platform
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from utils.logging import logger
from utils.cache import event_cache, metadata_cache
from bot.events import GROUPED_CALENDARS
from utils.rate_limiter import CALENDAR_API_LIMITER, EVENT_LIST_LIMITER

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ STATUS COMMAND HANDLER                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def handle_status_command(interaction: Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "⚠️ You need administrator permissions to use this command.",
            ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        embed = discord.Embed(
            title="📊 Calendar Bot Status Dashboard",
            description="System health and calendar status information",
            color=0x3498db,
            timestamp=datetime.now()
        )
        system_info = get_system_info()
        embed.add_field(
            name="🖥️ System Status",
            value="\n".join([f"**{k}:** {v}" for k, v in system_info.items()]),
            inline=False
        )
        calendar_status = get_calendar_status()
        embed.add_field(
            name="📆 Calendar Status",
            value=calendar_status,
            inline=False
        )
        api_status = get_api_status()
        embed.add_field(
            name="🔄 API Status",
            value=api_status,
            inline=False
        )
        cache_info = get_cache_info()
        embed.add_field(
            name="💾 Cache Status",
            value=cache_info,
            inline=False
        )
        embed.set_footer(text="Use /status again to refresh the dashboard")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.exception(f"Error generating status dashboard: {e}")
        await interaction.followup.send(
            "⚠️ An error occurred while generating the status dashboard.",
            ephemeral=True
        )

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ STATUS DATA HELPERS                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝
def get_system_info() -> Dict[str, str]:
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    memory = psutil.virtual_memory()
    memory_used_gb = memory.used / (1024 * 1024 * 1024)
    memory_total_gb = memory.total / (1024 * 1024 * 1024)
    memory_percent = memory.percent
    cpu_percent = psutil.cpu_percent(interval=0.5)
    process = psutil.Process(os.getpid())
    process_memory = process.memory_info().rss / (1024 * 1024)
    return {
        "OS": platform.system() + " " + platform.release(),
        "Python": platform.python_version(),
        "Host Uptime": uptime_str,
        "CPU Usage": f"{cpu_percent}%",
        "Memory": f"{memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB ({memory_percent}%)",
        "Bot Memory": f"{process_memory:.1f}MB"
    }

def get_calendar_status() -> str:
    if not GROUPED_CALENDARS:
        return "No calendars configured."
    google_count = 0
    ics_count = 0
    other_count = 0
    error_count = 0
    user_count = len(GROUPED_CALENDARS)
    for user_id, calendars in GROUPED_CALENDARS.items():
        for cal in calendars:
            cal_type = cal.get("type", "unknown")
            if cal_type == "google":
                google_count += 1
            elif cal_type == "ics":
                ics_count += 1
            else:
                other_count += 1
            if cal.get("error", False):
                error_count += 1
    total_count = google_count + ics_count + other_count
    lines = [
        f"**Total Calendars:** {total_count}",
        f"**Users with Calendars:** {user_count}",
        f"**Google Calendars:** {google_count}",
        f"**ICS Calendars:** {ics_count}"
    ]
    if error_count > 0:
        lines.append(f"**⚠️ Calendars with Errors:** {error_count}")
    else:
        lines.append("**Calendar Status:** All calendars OK ✅")
    return "\n".join(lines)

def get_api_status() -> str:
    lines = []
    cal_tokens = CALENDAR_API_LIMITER.get_token_count()
    event_tokens = EVENT_LIST_LIMITER.get_token_count()
    lines.append(f"**Calendar API Tokens:** {cal_tokens:.1f}/{CALENDAR_API_LIMITER.max_tokens}")
    lines.append(f"**Event List Tokens:** {event_tokens:.1f}/{EVENT_LIST_LIMITER.max_tokens}")
    return "\n".join(lines)

def get_cache_info() -> str:
    event_stats = event_cache.get_stats()
    metadata_stats = metadata_cache.get_stats()
    event_hit_ratio = event_stats["hit_ratio"] * 100
    metadata_hit_ratio = metadata_stats["hit_ratio"] * 100
    lines = [
        f"**Event Cache Size:** {event_stats['size']} items",
        f"**Event Cache Hit Rate:** {event_hit_ratio:.1f}% ({event_stats['hits']} hits, {event_stats['misses']} misses)",
        f"**Metadata Cache Size:** {metadata_stats['size']} items",
        f"**Metadata Cache Hit Rate:** {metadata_hit_ratio:.1f}% ({metadata_stats['hits']} hits, {metadata_stats['misses']} misses)"
    ]
    return "\n".join(lines)

async def register(bot):
    @bot.tree.command(name="status")
    @discord.app_commands.describe(
        show_details="Show detailed system information"
    )
    async def status_command(interaction: discord.Interaction, show_details: bool = False):
        await handle_status_command(interaction)