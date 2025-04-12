"""
Task utility functions shared across task modules.
"""
import discord
from utils.logging import logger
from config.server_config import get_all_server_ids, load_server_config

async def send_embed(bot, title=None, description=None, color=None, channel=None, **kwargs):
    """Send an embed message to the specified channel or the default announcement channel"""
    try:
        # If no specific channel was provided, try to get the default announcement channel
        if channel is None:
            # Try to find an appropriate channel from any configured server
            for server_id in get_all_server_ids():
                config = load_server_config(server_id)
                if config and config.get("announcement_channel_id"):
                    channel_id = int(config.get("announcement_channel_id"))
                    channel = bot.get_channel(channel_id)
                    if channel:
                        break
            
            if not channel:
                logger.error("No channel provided and couldn't find default announcement channel")
                return
        
        # Create the embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=color if color is not None else 0x3498db  # Default to blue
        )
        
        # Add any image if provided
        if 'image_path' in kwargs:
            file = discord.File(kwargs['image_path'], filename="image.png")
            embed.set_image(url="attachment://image.png")
            await channel.send(content=kwargs.get('content'), embed=embed, file=file)
        else:
            await channel.send(content=kwargs.get('content'), embed=embed)
            
    except Exception as e:
        logger.exception(f"Error in send_embed: {e}")
