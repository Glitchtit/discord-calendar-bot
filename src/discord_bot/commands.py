import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import dateparser
import asyncio
from src.core.logger import logger
from src.core.environment import USER_TAG_MAPPING, AI_TOGGLE
from src.calendar.sources import load_calendar_sources, get_user_tag_mapping
from src.calendar.events import get_events
from src.discord_bot.embeds import create_events_embed, create_announcement_embed
from src.ai.generator import generate_greeting, generate_image
from src.utils import get_date_range

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📋 Discord Bot Commands                                            ║
# ║ Handles user interactions and slash commands                       ║
# ╚════════════════════════════════════════════════════════════════════╝

def get_today():
    """Get today's date."""
    return datetime.now().date()

def get_monday_of_week(date):
    """Get Monday of the week for a given date."""
    days_since_monday = date.weekday()
    return date - timedelta(days=days_since_monday)

def resolve_input_to_tags(target: str, tag_names: dict, calendar_sources: dict) -> list:
    """Resolve user input to calendar tags."""
    if not target.strip():
        return list(calendar_sources.keys())
    
    # Check if it's a direct tag match
    if target in calendar_sources:
        return [target]
    
    # Check if it matches a display name
    for tag, name in tag_names.items():
        if name.lower() == target.lower():
            return [tag]
    
    return []

async def post_tagged_events(bot, tag: str, date):
    """Post events for a specific tag and date."""
    try:
        if not bot.announcement_channel:
            logger.warning("No announcement channel configured")
            return False
        
        calendar_sources = load_calendar_sources()
        if tag not in calendar_sources:
            logger.warning(f"Tag {tag} not found in calendar sources")
            return False
        
        all_events = []
        for source in calendar_sources[tag]:
            try:
                events = get_events(source, date, date + timedelta(days=1))
                all_events.extend(events)
            except Exception as e:
                logger.warning(f"Error fetching events from {source.get('name', 'unknown')}: {e}")
        
        if all_events:
            embed = create_events_embed(all_events, tag, 1)
            await bot.announcement_channel.send(embed=embed)
            return True
        
        return False
    except Exception as e:
        logger.exception(f"Error posting tagged events: {e}")
        return False

async def post_tagged_week(bot, tag: str, monday_date):
    """Post weekly events for a specific tag."""
    try:
        if not bot.announcement_channel:
            logger.warning("No announcement channel configured")
            return False
        
        calendar_sources = load_calendar_sources()
        if tag not in calendar_sources:
            logger.warning(f"Tag {tag} not found in calendar sources")
            return False
        
        end_date = monday_date + timedelta(days=7)
        all_events = []
        
        for source in calendar_sources[tag]:
            try:
                events = get_events(source, monday_date, end_date)
                all_events.extend(events)
            except Exception as e:
                logger.warning(f"Error fetching events from {source.get('name', 'unknown')}: {e}")
        
        if all_events:
            embed = create_events_embed(all_events, tag, 7)
            await bot.announcement_channel.send(embed=embed)
            return True
        
        return False
    except Exception as e:
        logger.exception(f"Error posting tagged week: {e}")
        return False

async def post_todays_happenings(bot, include_greeting=True):
    """Post today's happenings with optional greeting."""
    try:
        if not bot.announcement_channel:
            logger.warning("No announcement channel configured")
            return
        
        # Get today's events
        calendar_sources = load_calendar_sources()
        today = get_today()
        
        all_events = []
        event_titles = []
        
        for tag, sources in calendar_sources.items():
            for source in sources:
                try:
                    events = get_events(source, today, today + timedelta(days=1))
                    all_events.extend(events)
                    
                    for event in events:
                        title = event.get('summary', 'Event')
                        if title not in event_titles:
                            event_titles.append(title)
                except Exception as e:
                    logger.warning(f"Error fetching events from {source.get('name', 'unknown')}: {e}")
        
        if include_greeting and AI_TOGGLE:
            try:
                # Get present users
                present_users = []
                if bot.announcement_channel.guild:
                    user_tag_mapping = get_user_tag_mapping()
                    for user_id in user_tag_mapping.keys():
                        try:
                            member = bot.announcement_channel.guild.get_member(user_id)
                            if member and member.status != discord.Status.offline:
                                present_users.append(member.display_name)
                        except Exception:
                            pass
                
                greeting, persona = generate_greeting(event_titles[:5], present_users)
                image_path = generate_image(greeting, persona) if greeting else None
                
                embed = create_announcement_embed(greeting, all_events, persona)
                
                files = []
                if image_path:
                    try:
                        import os
                        if os.path.exists(image_path):
                            files.append(discord.File(image_path, filename="daily_greeting.png"))
                            embed.set_image(url="attachment://daily_greeting.png")
                    except Exception as e:
                        logger.warning(f"Error attaching image: {e}")
                
                await bot.announcement_channel.send(embed=embed, files=files)
                
            except Exception as e:
                logger.warning(f"Error generating greeting: {e}")
                # Fallback to simple event post
                if all_events:
                    embed = create_events_embed(all_events, "Today", 1)
                    await bot.announcement_channel.send(embed=embed)
        else:
            # Just post events without greeting
            if all_events:
                embed = create_events_embed(all_events, "Today", 1)
                await bot.announcement_channel.send(embed=embed)
        
    except Exception as e:
        logger.exception(f"Error posting today's happenings: {e}")

async def setup_commands(bot: commands.Bot):
    """Set up all bot commands."""
    
    # Create tag names mapping for display
    TAG_NAMES = {}
    
    @bot.tree.command(name="events", description="Show upcoming events for your calendar")
    async def events_command(interaction: discord.Interaction, days: int = 7):
        """Show upcoming events for the user's assigned calendar tag."""
        try:
            await interaction.response.defer()
            
            user_id = interaction.user.id
            user_tag_mapping = get_user_tag_mapping()
            
            # Check if user has a mapped tag
            if user_id not in user_tag_mapping:
                await interaction.followup.send(
                    "❌ You don't have access to any calendars. Contact an administrator.",
                    ephemeral=True
                )
                return
            
            tag = user_tag_mapping[user_id]
            logger.info(f"User {interaction.user.name} ({user_id}) requested events for tag {tag}")
            
            # Load calendar sources
            calendar_sources = load_calendar_sources()
            
            if tag not in calendar_sources:
                await interaction.followup.send(
                    f"❌ No calendars found for your tag '{tag}'. Contact an administrator.",
                    ephemeral=True
                )
                return
            
            # Fetch events
            start_date = datetime.now().date()
            end_date = start_date + timedelta(days=days)
            
            all_events = []
            for source in calendar_sources[tag]:
                events = get_events(source, start_date, end_date)
                all_events.extend(events)
            
            # Sort events by start time
            all_events.sort(key=lambda e: e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '')))
            
            # Create and send embed
            embed = create_events_embed(all_events, tag, days)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception(f"Error in events command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while fetching events. Please try again later.",
                ephemeral=True
            )

    @bot.tree.command(name="herald", description="Post all weekly and daily events for every calendar tag")
    async def herald_command(interaction: discord.Interaction):
        """Posts the weekly + daily event summaries for all tags."""
        try:
            await interaction.response.defer()
            today = get_today()
            monday = get_monday_of_week(today)
            
            calendar_sources = load_calendar_sources()
            
            for tag in calendar_sources:
                await post_tagged_week(bot, tag, monday)
            for tag in calendar_sources:
                await post_tagged_events(bot, tag, today)
            
            await interaction.followup.send("Herald posted for **all** tags — week and today.")
        except Exception as e:
            logger.exception(f"Error in /herald command: {e}")
            await interaction.followup.send("An error occurred while posting the herald.")

    @bot.tree.command(name="agenda", description="Post events for a date or range (e.g. 'tomorrow', 'week'), with optional tag filter")
    @app_commands.describe(
        input="A natural date or keyword: 'today', 'week', 'next monday', 'April 10', 'DD.MM'",
        target="Optional calendar tag or display name (e.g. Bob, xXsNiPeRkId69Xx)"
    )
    async def agenda_command(interaction: discord.Interaction, input: str, target: str = ""):
        """Posts events for a given date or natural language input."""
        try:
            await interaction.response.defer()
            
            today = get_today()
            calendar_sources = load_calendar_sources()
            tags = resolve_input_to_tags(target, TAG_NAMES, calendar_sources) if target.strip() else list(calendar_sources.keys())
            
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

    @bot.tree.command(name="greet", description="Post the morning greeting with image")
    async def greet_command(interaction: discord.Interaction):
        """Generates a persona-based medieval greeting with image."""
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

    @bot.tree.command(name="reload", description="Reload calendar sources and tag-user mappings")
    async def reload_command(interaction: discord.Interaction):
        """Reloads calendar sources and tag-to-user mapping."""
        try:
            await interaction.response.defer()
            load_calendar_sources()
            # Refresh tag mappings
            await resolve_tag_mappings(bot)
            await interaction.followup.send("Reloaded calendar sources and tag mappings.")
        except Exception as e:
            logger.exception(f"Error in /reload command: {e}")
            await interaction.followup.send("An error occurred while reloading.")

    @bot.tree.command(name="who", description="List calendar tags and their assigned users")
    async def who_command(interaction: discord.Interaction):
        """Displays all active tags and their mapped display names."""
        try:
            await interaction.response.defer()
            calendar_sources = load_calendar_sources()
            lines = [f"**{tag}** → {TAG_NAMES.get(tag, tag)}" for tag in sorted(calendar_sources)]
            await interaction.followup.send("**Calendar Tags:**\n" + "\n".join(lines))
        except Exception as e:
            logger.exception(f"Error in /who command: {e}")
            await interaction.followup.send("An error occurred while listing tags.")

    @bot.tree.command(name="calendars", description="List available calendar sources")
    async def calendars_command(interaction: discord.Interaction):
        """List all available calendar sources and their tags."""
        try:
            await interaction.response.defer()
            
            # Check if user has admin permissions (can see all calendars)
            is_admin = interaction.user.guild_permissions.administrator
            
            calendar_sources = load_calendar_sources()
            user_tag_mapping = get_user_tag_mapping()
            user_tag = user_tag_mapping.get(interaction.user.id)
            
            embed = discord.Embed(
                title="📅 Calendar Sources",
                color=0x3498db,
                timestamp=datetime.now()
            )
            
            if not calendar_sources:
                embed.description = "No calendar sources configured."
                await interaction.followup.send(embed=embed)
                return
            
            for tag, sources in calendar_sources.items():
                # Show tag only if user has access or is admin
                if is_admin or user_tag == tag:
                    source_list = []
                    for source in sources:
                        name = source.get('name', 'Unknown')
                        source_type = source.get('type', 'unknown')
                        status = "✅" if not source.get('error') else "❌"
                        source_list.append(f"{status} {name} ({source_type})")
                    
                    embed.add_field(
                        name=f"Tag: {tag}" + (" (Your Tag)" if user_tag == tag else ""),
                        value="\n".join(source_list) if source_list else "No sources",
                        inline=False
                    )
            
            if not embed.fields:
                embed.description = "You don't have access to any calendars."
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception(f"Error in calendars command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while fetching calendar information.",
                ephemeral=True
            )
    
    @bot.tree.command(name="status", description="Check bot status and configuration")
    async def status_command(interaction: discord.Interaction):
        """Show bot status and basic configuration info."""
        try:
            embed = discord.Embed(
                title="🤖 Bot Status",
                color=0x2ecc71,
                timestamp=datetime.now()
            )
            
            # Basic status
            embed.add_field(
                name="Status",
                value="🟢 Online and operational",
                inline=True
            )
            
            # Calendar sources count
            calendar_sources = load_calendar_sources()
            total_sources = sum(len(sources) for sources in calendar_sources.values())
            embed.add_field(
                name="Calendar Sources",
                value=f"{total_sources} sources across {len(calendar_sources)} tags",
                inline=True
            )
            
            # User mappings
            user_mappings = get_user_tag_mapping()
            embed.add_field(
                name="User Mappings",
                value=f"{len(user_mappings)} users configured",
                inline=True
            )
            
            # Show user's access
            user_tag = user_mappings.get(interaction.user.id)
            if user_tag:
                embed.add_field(
                    name="Your Access",
                    value=f"Tag: {user_tag}",
                    inline=True
                )
            else:
                embed.add_field(
                    name="Your Access",
                    value="❌ No access configured",
                    inline=True
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.exception(f"Error in status command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while checking status.",
                ephemeral=True
            )

    async def resolve_tag_mappings(bot):
        """Assigns display names and colors to tags based on members."""
        try:
            logger.info("Resolving Discord tag-to-name mappings...")
            
            # Handle case where bot might be in multiple guilds
            if not bot.guilds:
                logger.warning("No guilds available. Tag mappings not resolved.")
                return
                
            user_tag_mapping = get_user_tag_mapping()
            
            # Process each guild the bot is in
            for guild in bot.guilds:
                logger.debug(f"Processing guild: {guild.name} (ID: {guild.id})")
                
                # Process each user-tag mapping
                for user_id, tag in user_tag_mapping.items():
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
                        logger.info(f"Assigned {tag}: name={display_name}")
                    else:
                        # Not found in any guild, set fallback name
                        TAG_NAMES[tag] = TAG_NAMES.get(tag, tag)
                        logger.warning(f"Could not resolve Discord member for ID {user_id} in any guild")
            
            logger.info(f"Tag mapping complete: {len(TAG_NAMES)} tags resolved")
        except Exception as e:
            logger.exception(f"Error in resolve_tag_mappings: {e}")

    logger.info("Discord commands set up successfully")