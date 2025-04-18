# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT RELOAD COMMAND HANDLER                     ║
# ║    Handles reloading of calendar sources and user mappings                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import discord
from discord import Interaction
from utils.logging import logger

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ RELOAD CALENDARS AND MAPPINGS                                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def reload_calendars_and_mappings():
    from bot.events import load_calendars_from_server_configs, reinitialize_events
    load_calendars_from_server_configs()
    logger.info("Calling reinitialize_events from reload.py, line 9")
    await reinitialize_events()

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ RELOAD COMMAND HANDLER                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def handle_reload_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        await reload_calendars_and_mappings()
        await interaction.followup.send("✅ Calendar sources reloaded")
    except Exception as e:
        logger.error(f"Reload error: {e}")
        await interaction.followup.send("⚠️ Failed to reload calendars")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def register(bot: discord.Client):
    @bot.tree.command(name="reload")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def reload_command(interaction: discord.Interaction):
        await handle_reload_command(interaction)
