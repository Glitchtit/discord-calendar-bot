# Removed unused imports
import discord
from discord import Interaction
from utils.logging import logger

async def reload_calendars_and_mappings():
    from bot.events import load_calendars_from_server_configs, reinitialize_events
    load_calendars_from_server_configs()
    await reinitialize_events()

async def handle_reload_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        await reload_calendars_and_mappings()
        await interaction.followup.send("✅ Calendar sources reloaded")
    except Exception as e:
        logger.error(f"Reload error: {e}")
        await interaction.followup.send("⚠️ Failed to reload calendars")

async def register(bot: discord.Client):
    @bot.tree.command(name="reload")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def reload_command(interaction: discord.Interaction):
        """Reload calendar configurations (Admin only)"""
        await handle_reload_command(interaction)
