"""
Task utility functions shared across task modules.
"""
import discord
from utils.logging import logger
from config.server_config import get_all_server_ids, get_announcement_channel_id

async def send_embed(bot, title=None, description=None, color=None, channel=None, **kwargs):
    """Send an embed message to the specified channel or the default announcement channel"""
    try:
        # If no specific channel was provided, try to get the default announcement channel
        if channel is None:
            # Try to find an appropriate channel from any configured server
            # Prioritize channel_id from kwargs if provided
            channel_id = kwargs.get('channel_id')
            server_id = kwargs.get('server_id')

            if not channel_id and server_id:
                channel_id = get_announcement_channel_id(server_id)
            
            # If still no channel_id, iterate through servers (less ideal)
            if not channel_id:
                for sid in get_all_server_ids():
                    c_id = get_announcement_channel_id(sid)
                    if c_id:
                        channel_id = c_id
                        break # Use the first one found
            
            if channel_id:
                channel = bot.get_channel(channel_id)
            
            if not channel:
                logger.error("send_embed (tasks): No channel provided and couldn't find a default announcement channel via config.")
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
