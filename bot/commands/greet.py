# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    CALENDAR BOT GREET COMMAND HANDLER                    ║
# ║    Simple command for testing bot responsiveness                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Handles the `/greet` slash command.

A basic command primarily used for testing if the bot is online and responding
to commands. It simply replies with a friendly greeting.
"""

import discord
from discord import Interaction
from utils.logging import logger
from utils.ai_helpers import generate_themed_greeting
from config.server_config import get_announcement_channel_id

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST GREETING                                                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- post_greeting ---
# Generates a themed greeting using the AI helper and sends it to the specified channel.
# Args:
#     bot: The discord.Client instance (unused in current implementation but good practice).
#     channel: The discord.TextChannel to send the greeting to.
# Returns: True if the greeting was posted successfully, False otherwise.
async def post_greeting(bot, channel):
    try:
        greeting = await generate_themed_greeting()
        await channel.send(greeting)
        logger.info(f"Posted greeting to channel {channel.name}")
        return True
    except Exception as e:
        logger.error(f"Error posting greeting: {e}")
        return False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ GREET COMMAND HANDLER                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_greet_command ---
# The core logic for the /greet slash command.
# Sends a simple, ephemeral greeting message back to the user who invoked the command.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
async def handle_greet_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        channel_id = get_announcement_channel_id(interaction.guild_id)
        channel = interaction.client.get_channel(channel_id) if channel_id else None
        if not channel:
            channel = interaction.channel
        success = await post_greeting(interaction.client, channel)
        if success:
            await interaction.followup.send("✅ Posted greeting message")
        else:
            await interaction.followup.send("⚠️ Failed to post greeting")
    except Exception as e:
        logger.error(f"Greet command error: {e}")
        await interaction.followup.send("⚠️ Failed to post greeting")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /greet slash command with the bot's command tree.
# This function is typically called during bot setup.
# It defines the command name and description.
# Args:
#     bot: The discord.ext.commands.Bot instance.
async def register(bot):
    # --- greet_command ---
    # The actual slash command function decorated with `@bot.tree.command`.
    # This is the function directly invoked by Discord when the command is used.
    # It simply calls `handle_greet_command` to send the greeting.
    # Args:
    #     interaction: The discord.Interaction object.
    @bot.tree.command(name="greet", description="Say hello to the bot!")
    async def greet_command(interaction: discord.Interaction):
        """Say hello to the bot!"""
        await handle_greet_command(interaction)
    logger.info("Registered /greet command.")
