# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT GREET COMMAND HANDLER                      ║
# ║    Handles posting of themed morning greetings to announcement channels   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import discord
from discord import Interaction
from utils.logging import logger
from utils.ai_helpers import generate_themed_greeting
from config.server_config import get_announcement_channel_id

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST GREETING                                                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝
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
# ║ GREET COMMAND HANDLER                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝
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
async def register(bot):
    @bot.tree.command(name="greet")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def greet_command(interaction: discord.Interaction):
        await handle_greet_command(interaction)
