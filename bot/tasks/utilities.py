# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                      BOT TASKS UTILITIES MODULE                            ║
# ║       Provides shared utility functions specifically for tasks,            ║
# ║       like sending embeds to configured announcement channels.             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Task utility functions shared across task modules.
"""
import discord
from utils.logging import logger
from config.server_config import get_all_server_ids, get_announcement_channel_id

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EMBED SENDING UTILITY                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- send_embed ---
# A utility function for tasks to send Discord embeds.
# Handles finding the appropriate announcement channel based on server configuration.
# If a specific `channel` object is provided, it uses that.
# Otherwise, it tries to find the announcement channel ID using `get_announcement_channel_id`,
# first checking for `channel_id` or `server_id` in `kwargs`, then iterating through all servers.
# Creates and sends a `discord.Embed` with the provided title, description, color, and optional content/image.
# Logs an error if no suitable channel can be found.
# Args:
#     bot: The discord.py Bot instance.
#     title: The title of the embed.
#     description: The main text content of the embed.
#     color: The color of the embed sidebar (integer).
#     channel: (Optional) A specific discord.TextChannel object to send to.
#     **kwargs: Additional arguments, potentially including:
#         channel_id: Specific channel ID to send to.
#         server_id: Server ID to look up the announcement channel for.
#         content: Text content to send alongside the embed (e.g., for mentions).
#         image_path: Local path to an image file to attach and display in the embed.
async def send_embed(bot, title=None, description=None, color=None, channel=None, **kwargs):
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
