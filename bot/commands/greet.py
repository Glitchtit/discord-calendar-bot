import discord
from discord import Interaction
from utils.logging import logger
from utils.ai_helpers import generate_themed_greeting

async def post_greeting(bot, channel):
    """Post a greeting to the specified channel"""
    try:
        greeting = await generate_themed_greeting()
        await channel.send(greeting)
        logger.info(f"Posted greeting to channel {channel.name}")
        return True
    except Exception as e:
        logger.error(f"Error posting greeting: {e}")
        return False

async def handle_greet_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        # Get the announcement channel
        from config.server_config import load_server_config
        config = load_server_config(str(interaction.guild_id))
        
        channel = None
        if config and config.get("announcement_channel_id"):
            channel_id = int(config.get("announcement_channel_id"))
            channel = interaction.client.get_channel(channel_id)
        
        # Fall back to the current channel if necessary
        if not channel:
            channel = interaction.channel
            
        # Post the greeting
        success = await post_greeting(interaction.client, channel)
        
        if success:
            await interaction.followup.send("✅ Posted greeting message")
        else:
            await interaction.followup.send("⚠️ Failed to post greeting")
    except Exception as e:
        logger.error(f"Greet command error: {e}")
        await interaction.followup.send("⚠️ Failed to post greeting")

async def register(bot):
    @bot.tree.command(name="greet")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def greet_command(interaction: discord.Interaction):
        """Post a themed morning greeting"""
        await handle_greet_command(interaction)
