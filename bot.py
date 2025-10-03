import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import dateparser
import asyncio
import random

from log import logger
from events import (
    load_calendar_sources,
    GROUPED_CALENDARS,
    USER_TAG_MAP,
    TAG_NAMES,
    TAG_COLORS,
    get_events
)
from ai import generate_greeting, generate_image
from commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
    autocomplete_tag,
    autocomplete_range,
    autocomplete_agenda_target,
    autocomplete_agenda_input
)
from tasks import initialize_event_snapshots, start_all_tasks, post_todays_happenings
from utils import get_today, get_monday_of_week, resolve_input_to_tags
from environ import AI_TOGGLE

# ╔═════════════════════════════════════════════════════════════╗
# ║ 🤖 Discord Bot Initialization                               ║
# ║ Configures the bot with necessary intents and slash system ║
# ╚═════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Track initialization state to avoid duplicate startups
bot.is_initialized = False


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🟢 on_ready                                                  ║
# ║ Called once the bot is online and ready                     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    
    # Prevent multiple initializations if Discord reconnects
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return
    
    # Perform initialization with progressive backoff for retries
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Step 1: Resolve tag mappings
            await resolve_tag_mappings()
            
            # Step 2: Add slight delay to avoid rate limiting
            await asyncio.sleep(1)
            
            # Step 3: Sync slash commands
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} commands.")
            
            # Step 4: Initialize event snapshots
            await initialize_event_snapshots()
            
            # Step 5: Start recurring tasks
            start_all_tasks(bot)
            
            # Mark successful initialization
            bot.is_initialized = True
            logger.info("Bot initialization completed successfully")
            break
            
        except discord.errors.HTTPException as e:
            # Handle Discord API issues with exponential backoff
            retry_delay = 2 ** attempt + random.uniform(0, 1)
            logger.warning(f"Discord API error during initialization (attempt {attempt}/{max_retries}): {e}")
            
            if attempt < max_retries:
                logger.info(f"Retrying initialization in {retry_delay:.2f} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Maximum retries reached. Continuing with partial initialization.")
                # Still mark as initialized to prevent endless retries on reconnect
                bot.is_initialized = True
                
        except Exception as e:
            logger.exception(f"Unexpected error during initialization: {e}")
            # Mark as initialized despite error to prevent retry loops
            bot.is_initialized = True


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_disconnect                                            ║
# ║ Called when the bot disconnects from Discord                ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord. Waiting for reconnection...")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_resumed                                               ║
# ║ Called when the bot reconnects after a disconnect           ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_resumed():
    logger.info("Bot connection resumed")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📜 /herald                                                   ║
# ║ Posts the weekly + daily event summaries for all tags       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="herald",
    description="Post all weekly and daily events for every calendar tag"
)
async def herald_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        today = get_today()
        monday = get_monday_of_week(today)

        for tag in GROUPED_CALENDARS:
            await post_tagged_week(bot, tag, monday)
        for tag in GROUPED_CALENDARS:
            await post_tagged_events(bot, tag, today)

        await interaction.followup.send("Herald posted for **all** tags — week and today.")
    except Exception as e:
        logger.exception(f"Error in /herald command: {e}")
        await interaction.followup.send("An error occurred while posting the herald.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🗓️ /agenda                                                   ║
# ║ Posts events for a given date or natural language input     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="agenda",
    description="Post events for a date or range (e.g. 'tomorrow', 'week'), with optional tag filter"
)
@app_commands.describe(
    input="A natural date or keyword: 'today', 'week', 'next monday', 'April 10', 'DD.MM'",
    target="Optional calendar tag or display name (e.g. Bob, xXsNiPeRkId69Xx)"
)
@app_commands.autocomplete(input=autocomplete_agenda_input, target=autocomplete_agenda_target)
async def agenda_command(interaction: discord.Interaction, input: str, target: str = ""):
    try:
        await interaction.response.defer()

        today = get_today()
        tags = resolve_input_to_tags(target, TAG_NAMES, GROUPED_CALENDARS) if target.strip() else list(GROUPED_CALENDARS.keys())

        if not tags:
            await interaction.followup.send("No matching tags or names found.")
            return

        any_posted = False
        if input.lower() == "today":
            for tag in tags:
                posted = await post_tagged_events(bot, tag, today)
                any_posted |= posted
            label = today.strftime("%A, %B %d")
        elif input.lower() == "week":
            monday = get_monday_of_week(today)
            for tag in tags:
                await post_tagged_week(bot, tag, monday)
            any_posted = True  # Weekly always posts if calendars are valid
            label = f"week of {monday.strftime('%B %d')}"
        else:
            parsed = dateparser.parse(input)
            if not parsed:
                await interaction.followup.send("Could not understand the date. Try 'today', 'week', or a real date.")
                return
            day = parsed.date()
            for tag in tags:
                posted = await post_tagged_events(bot, tag, day)
                any_posted |= posted
            label = day.strftime("%A, %B %d")

        tag_names = ", ".join(TAG_NAMES.get(t, t) for t in tags)
        if any_posted:
            await interaction.followup.send(f"Agenda posted for **{tag_names}** on **{label}**.")
        else:
            await interaction.followup.send(f"No events found for **{tag_names}** on **{label}**.")
    except Exception as e:
        logger.exception(f"Error in /agenda command: {e}")
        await interaction.followup.send("An error occurred while processing the agenda.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🎭 /greet                                                    ║
# ║ Generates a persona-based medieval greeting with image      ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="greet", description="Post the morning greeting with image")
async def greet_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Check if AI is enabled before proceeding
        if not AI_TOGGLE:
            await interaction.followup.send("AI features are currently disabled. Cannot generate greeting.")
            logger.info("Greet command skipped because AI_TOGGLE is false.")
            return
            
        await post_todays_happenings(bot, include_greeting=True)
        await interaction.followup.send("Greeting and image posted.")
    except Exception as e:
        logger.exception(f"Error in /greet command: {e}")
        await interaction.followup.send("An error occurred while posting the greeting.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔄 /reload                                                   ║
# ║ Reloads calendar sources and tag-to-user mapping            ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="reload", description="Reload calendar sources and tag-user mappings")
async def reload_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        load_calendar_sources()
        await resolve_tag_mappings()
        await interaction.followup.send("Reloaded calendar sources and tag mappings.")
    except Exception as e:
        logger.exception(f"Error in /reload command: {e}")
        await interaction.followup.send("An error occurred while reloading.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📇 /who                                                      ║
# ║ Displays all active tags and their mapped display names     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="who", description="List calendar tags and their assigned users")
async def who_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        lines = [f"**{tag}** → {TAG_NAMES.get(tag, tag)}" for tag in sorted(GROUPED_CALENDARS)]
        await interaction.followup.send("**Calendar Tags:**\n" + "\n".join(lines))
    except Exception as e:
        logger.exception(f"Error in /who command: {e}")
        await interaction.followup.send("An error occurred while listing tags.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔍 /verify_status                                           ║
# ║ Shows the status of pending change verifications (debug)    ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="verify_status", description="Show status of pending change verifications (debug)")
async def verify_status_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        from tasks import get_pending_changes_status
        status = get_pending_changes_status()
        
        if not status:
            await interaction.followup.send("No pending change verifications.")
            return
        
        lines = ["**📋 Pending Change Verifications:**\n"]
        for tag, info in status.items():
            ready = "✅ Ready" if info['ready_for_verification'] else f"⏳ {info['time_remaining_minutes']:.1f}min left"
            lines.append(f"**{tag}**: +{info['added_count']} -{info['removed_count']} ({ready})")
        
        await interaction.followup.send("\n".join(lines))
    except Exception as e:
        logger.exception(f"Error in /verify_status command: {e}")
        await interaction.followup.send("An error occurred while checking verification status.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🧹 /clear_pending                                           ║
# ║ Clears all pending change verifications (debug/admin)       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="clear_pending", description="Clear all pending change verifications (admin)")
async def clear_pending_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        from tasks import _pending_changes
        count = len(_pending_changes)
        _pending_changes.clear()
        
        await interaction.followup.send(f"Cleared {count} pending change verification(s).")
        logger.info(f"Manually cleared {count} pending change verifications")
    except Exception as e:
        logger.exception(f"Error in /clear_pending command: {e}")
        await interaction.followup.send("An error occurred while clearing pending verifications.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📊 /health                                                  ║
# ║ Shows calendar system health metrics and status            ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="health", description="Show calendar system health metrics and status")
@app_commands.describe(detailed="Show detailed breakdown including circuit breaker status")
async def health_command(interaction: discord.Interaction, detailed: bool = False):
    try:
        await interaction.response.defer()
        
        # Import here to avoid circular imports
        from calendar_health import get_health_summary, get_circuit_breaker_status
        from events import get_metrics_summary
        
        health = get_health_summary()
        metrics = health['metrics']
        
        # Determine status emoji and color
        status_info = {
            "healthy": {"emoji": "✅", "color": 0x00ff00},
            "degraded": {"emoji": "⚠️", "color": 0xffa500}, 
            "unhealthy": {"emoji": "❌", "color": 0xff0000},
            "unknown": {"emoji": "❓", "color": 0x808080}
        }
        
        current_status = status_info.get(health['status'], status_info['unknown'])
        
        # Create embed
        embed = discord.Embed(
            title=f"{current_status['emoji']} Calendar System Health",
            description=f"Status: **{health['status'].title()}**",
            color=current_status['color'],
            timestamp=datetime.now()
        )
        
        # Add metrics fields
        if metrics['requests_total'] > 0:
            embed.add_field(
                name="📈 Request Statistics",
                value=(
                    f"**Total:** {metrics['requests_total']}\n"
                    f"**Successful:** {metrics['requests_successful']}\n"
                    f"**Failed:** {metrics['requests_failed']}\n"
                    f"**Success Rate:** {metrics['success_rate_percent']}%"
                ),
                inline=True
            )
            
            embed.add_field(
                name="📊 Processing Stats",
                value=(
                    f"**Events Processed:** {metrics['events_processed']}\n"
                    f"**Duration:** {metrics['duration_minutes']:.1f} min\n"
                    f"**Circuit Breakers:** {metrics['circuit_breakers_active']}"
                ),
                inline=True
            )
            
            # Error breakdown
            if metrics['parsing_errors'] + metrics['network_errors'] + metrics['auth_errors'] > 0:
                embed.add_field(
                    name="⚠️ Error Breakdown",
                    value=(
                        f"**Parsing Errors:** {metrics['parsing_errors']}\n"
                        f"**Network Errors:** {metrics['network_errors']}\n"
                        f"**Auth Errors:** {metrics['auth_errors']}"
                    ),
                    inline=True
                )
        else:
            embed.add_field(
                name="ℹ️ Activity",
                value="No recent calendar processing activity",
                inline=False
            )
        
        # Add alerts if any
        if health['alerts']:
            alert_text = []
            for alert in health['alerts'][:5]:  # Limit to 5 alerts to avoid embed limits
                emoji = {"critical": "🚨", "error": "❌", "warning": "⚠️"}.get(alert['level'], "ℹ️")
                alert_text.append(f"{emoji} {alert['message']}")
            
            embed.add_field(
                name="🚨 Active Alerts",
                value="\n".join(alert_text),
                inline=False
            )
        
        # Add detailed circuit breaker info if requested
        if detailed and health['circuit_breakers']:
            breakers = health['circuit_breakers']
            breaker_text = []
            
            for calendar_id, status in list(breakers.items())[:10]:  # Limit to 10 to fit in embed
                # Truncate long calendar IDs for display
                display_id = calendar_id[:30] + "..." if len(calendar_id) > 30 else calendar_id
                backoff_min = status['backoff_remaining_seconds'] / 60
                breaker_text.append(
                    f"🔴 `{display_id}`\n"
                    f"   Failures: {status['failure_count']}, Retry in: {backoff_min:.1f}m"
                )
            
            if breaker_text:
                embed.add_field(
                    name=f"🚫 Circuit Breakers ({len(breakers)} total)",
                    value="\n\n".join(breaker_text),
                    inline=False
                )
        
        # Add footer
        embed.set_footer(text="Use /health detailed:True for circuit breaker details")
        
        await interaction.followup.send(embed=embed)
        logger.info(f"Health command executed by {interaction.user}")
        
    except Exception as e:
        logger.exception(f"Error in /health command: {e}")
        await interaction.followup.send("❌ An error occurred while retrieving health metrics.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔄 /reset_health                                           ║
# ║ Resets health metrics and circuit breakers (admin)         ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="reset_health", description="Reset calendar health metrics and circuit breakers (admin)")
@app_commands.describe(
    component="Which component to reset: 'metrics', 'circuits', or 'all'"
)
@app_commands.choices(component=[
    app_commands.Choice(name="metrics", value="metrics"),
    app_commands.Choice(name="circuits", value="circuits"), 
    app_commands.Choice(name="all", value="all")
])
async def reset_health_command(interaction: discord.Interaction, component: str = "all"):
    try:
        await interaction.response.defer()
        
        # Import here to avoid circular imports
        from events import reset_metrics, _failed_calendars
        
        results = []
        
        if component in ["metrics", "all"]:
            reset_metrics()
            results.append("✅ Health metrics reset")
            
        if component in ["circuits", "all"]:
            circuit_count = len(_failed_calendars)
            _failed_calendars.clear()
            results.append(f"✅ {circuit_count} circuit breakers reset")
        
        result_message = "\n".join(results)
        await interaction.followup.send(f"**Health Reset Complete:**\n{result_message}")
        logger.info(f"Health reset ({component}) executed by {interaction.user}")
        
    except Exception as e:
        logger.exception(f"Error in /reset_health command: {e}")
        await interaction.followup.send("❌ An error occurred while resetting health metrics.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📝 /log_health                                              ║
# ║ Manually trigger health status logging (debug)             ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="log_health", description="Manually log current health status to system logs")
async def log_health_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Import here to avoid circular imports
        from calendar_health import log_health_status, get_health_summary
        
        # Log to system logs
        log_health_status()
        
        # Get summary for response
        health = get_health_summary()
        status_emoji = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌", "unknown": "❓"}
        emoji = status_emoji.get(health['status'], "❓")
        
        await interaction.followup.send(
            f"{emoji} Health status logged to system logs.\n"
            f"Current status: **{health['status'].title()}**\n"
            f"Active alerts: **{len(health['alerts'])}**"
        )
        logger.info(f"Manual health logging triggered by {interaction.user}")
        
    except Exception as e:
        logger.exception(f"Error in /log_health command: {e}")
        await interaction.followup.send("❌ An error occurred while logging health status.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📋 /calendars                                               ║
# ║ Shows status of all configured calendar sources            ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="calendars", description="Show status of all configured calendar sources")
async def calendars_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Import here to avoid circular imports
        from calendar_health import get_calendar_summary
        
        summary = get_calendar_summary()
        
        if "error" in summary:
            await interaction.followup.send(f"❌ Error getting calendar summary: {summary['error']}")
            return
        
        # Create embed
        embed = discord.Embed(
            title="📋 Calendar Sources Status",
            description=f"**Total:** {summary['total_calendars']} calendars configured",
            color=0x00ff00 if summary['failed_calendars'] == 0 else (0xffa500 if summary['failed_calendars'] < summary['total_calendars'] // 2 else 0xff0000),
            timestamp=datetime.now()
        )
        
        # Add summary field
        embed.add_field(
            name="📊 Overview",
            value=(
                f"✅ **Healthy:** {summary['healthy_calendars']}\n"
                f"❌ **Failed:** {summary['failed_calendars']}\n"
                f"📈 **Success Rate:** {(summary['healthy_calendars']/summary['total_calendars']*100):.1f}%" if summary['total_calendars'] > 0 else "N/A"
            ),
            inline=True
        )
        
        # Add details by tag
        for tag, tag_info in summary['calendars_by_tag'].items():
            if tag_info['total'] == 0:
                continue
                
            status_emoji = "✅" if tag_info['failed'] == 0 else "⚠️" if tag_info['failed'] < tag_info['total'] else "❌"
            
            calendar_lines = []
            for cal in tag_info['calendars'][:5]:  # Limit to 5 to avoid embed limits
                cal_emoji = "✅" if cal['status'] == 'healthy' else "❌"
                error_text = ""
                if cal['error']:
                    error_type = cal['error']['type']
                    if error_type == 'circuit_breaker':
                        error_text = f" (CB: {cal['error']['failure_count']} fails)"
                    else:
                        error_text = f" ({error_type})"
                
                calendar_lines.append(f"{cal_emoji} `{cal['name'][:20]}{'...' if len(cal['name']) > 20 else ''}`{error_text}")
            
            if len(tag_info['calendars']) > 5:
                calendar_lines.append(f"... and {len(tag_info['calendars']) - 5} more")
            
            embed.add_field(
                name=f"{status_emoji} Tag {tag} ({tag_info['healthy']}/{tag_info['total']} healthy)",
                value="\n".join(calendar_lines) if calendar_lines else "No calendars",
                inline=False
            )
        
        # Add footer with legend
        embed.set_footer(text="CB = Circuit Breaker active | Use /health for detailed metrics")
        
        await interaction.followup.send(embed=embed)
        logger.info(f"Calendars command executed by {interaction.user}")
        
    except Exception as e:
        logger.exception(f"Error in /calendars command: {e}")
        await interaction.followup.send("❌ An error occurred while retrieving calendar status.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔗 resolve_tag_mappings                                      ║
# ║ Assigns display names and colors to tags based on members   ║
# ╚═════════════════════════════════════════════════════════════╝
async def resolve_tag_mappings():
    try:
        logger.info("Resolving Discord tag-to-name mappings...")
        
        # Handle case where bot might be in multiple guilds
        if not bot.guilds:
            logger.warning("No guilds available. Tag mappings not resolved.")
            return
            
        # Process each guild the bot is in
        for guild in bot.guilds:
            logger.debug(f"Processing guild: {guild.name} (ID: {guild.id})")
            
            # Process each user-tag mapping
            for user_id, tag in USER_TAG_MAP.items():
                # Fetch member with retries
                member = None
                max_retries = 2
                
                for attempt in range(max_retries):
                    try:
                        # Try to get member from cache first
                        member = guild.get_member(user_id)
                        
                        # If not in cache, fetch from API
                        if member is None:
                            member = await guild.fetch_member(user_id)
                            
                        if member:
                            break
                    except discord.errors.NotFound:
                        # Member not in this guild, try the next one
                        logger.debug(f"User ID {user_id} not found in guild {guild.name}")
                        break
                    except Exception as e:
                        logger.warning(f"Error fetching member {user_id} (attempt {attempt+1}): {e}")
                        await asyncio.sleep(1)
                
                # Process member if found
                if member:
                    display_name = member.nick or member.display_name
                    TAG_NAMES[tag] = display_name
                    
                    # Get member's role color (defaulting to gray if none)
                    role_color = next((r.color.value for r in member.roles if r.color.value != 0), 0x95a5a6)
                    TAG_COLORS[tag] = role_color
                    
                    logger.info(f"Assigned {tag}: name={display_name}, color=#{role_color:06X}")
                else:
                    # Not found in any guild, set fallback name
                    TAG_NAMES[tag] = TAG_NAMES.get(tag, tag)
                    logger.warning(f"Could not resolve Discord member for ID {user_id} in any guild")
        
        logger.info(f"Tag mapping complete: {len(TAG_NAMES)} tags resolved")
    except Exception as e:
        logger.exception(f"Error in resolve_tag_mappings: {e}")
        # Don't re-raise, allow initialization to continue


# ╔═════════════════════════════════════════════════════════════╗
# ║ ⚠️ on_error                                                  ║
# ║ Global error handler for unhandled exceptions               ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler to log exceptions and prevent crashes."""
    try:
        import traceback
        import sys
        
        # Get exception info
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        # Log the full exception with context
        logger.exception(f"Unhandled exception in event '{event}': {exc_value}")
        
        # Also log the event arguments for debugging (safely)
        try:
            logger.error(f"Event arguments: {args[:3] if len(args) > 3 else args}")  # Limit to prevent spam
        except Exception:
            logger.error("Event arguments could not be logged safely")
            
        # Try to continue operation - don't re-raise the exception
        logger.info("Bot continuing operation despite error")
        
    except Exception as handler_error:
        # Even our error handler failed - log and continue
        logger.error(f"Error in error handler: {handler_error}")


# ╔═════════════════════════════════════════════════════════════╗
# ║ ⚠️ on_app_command_error                                      ║
# ║ Handle slash command errors gracefully                      ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle slash command errors gracefully."""
    try:
        error_msg = "An error occurred while processing your command."
        
        if isinstance(error, app_commands.CommandOnCooldown):
            error_msg = f"Command is on cooldown. Try again in {error.retry_after:.2f} seconds."
        elif isinstance(error, app_commands.MissingPermissions):
            error_msg = "You don't have permission to use this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            error_msg = "I don't have the necessary permissions to execute this command."
        
        # Log the full error
        logger.exception(f"Slash command error in {interaction.command.name if interaction.command else 'unknown'}: {error}")
        
        # Respond to user
        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
        except Exception as response_error:
            logger.error(f"Failed to send error response to user: {response_error}")
            
    except Exception as handler_error:
        logger.error(f"Error in command error handler: {handler_error}")
