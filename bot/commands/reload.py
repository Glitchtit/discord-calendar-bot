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

# --- reload_calendars_and_mappings ---
# Reloads calendar configurations from server config files and reinitializes event data.
# This is the core function triggered by the /reload command.
async def reload_calendars_and_mappings():
    from bot.events import load_calendars_from_server_configs, reinitialize_events
    load_calendars_from_server_configs()
    logger.info("Calling reinitialize_events from reload.py, line 9")
    await reinitialize_events()

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ RELOAD COMMAND HANDLER                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_reload_command ---
# The logic for the /reload slash command (Admin only).
# Calls `reload_calendars_and_mappings` and sends a confirmation or error message.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
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

# --- register ---
# Registers the /reload slash command with the bot's command tree.
# Requires administrator permissions.
# Args:
#     bot: The discord.Client instance to register the command with.
async def register(bot: discord.Client):
    # --- reload_command ---
    # The actual slash command function invoked by Discord.
    # Requires administrator permissions.
    # Calls `handle_reload_command` to process the request.
    # Args:
    #     interaction: The discord.Interaction object.
    @bot.tree.command(name="reload")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def reload_command(interaction: discord.Interaction):
        await handle_reload_command(interaction)
