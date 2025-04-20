# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                CALENDAR BOT COMMAND UTILITIES MODULE                     ║
# ║    Shared helper functions for command modules and Discord operations     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import discord
from discord.errors import Forbidden, HTTPException, GatewayNotFound
from typing import Coroutine, Optional
import asyncio
import random
import os
import logging
from config.server_config import get_announcement_channel_id

logger = logging.getLogger(__name__)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ DISCORD OPERATION RETRY                                                   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- _retry_discord_operation ---
# A wrapper to retry a Discord API operation with exponential backoff.
# Useful for handling transient network issues or rate limits.
# Args:
#     operation: The coroutine or function to execute.
#     max_retries: The maximum number of times to retry (default 3).
# Returns: The result of the operation if successful.
# Raises: The last exception encountered if all retries fail.
async def _retry_discord_operation(operation, max_retries=3):
    last_error = None
    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(operation):
                return await operation()
            else:
                return operation()
        except Exception as e:
            last_error = e
            wait_time = (2 ** attempt) + (0.1 * attempt)
            logger.warning(f"Discord operation failed (attempt {attempt+1}/{max_retries}), retrying in {wait_time:.1f}s: {e}")
            await asyncio.sleep(wait_time)
    logger.error(f"Discord operation failed after {max_retries} attempts: {last_error}")
    raise last_error

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CHANNEL PERMISSION CHECK                                                  ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- check_channel_permissions ---
# Checks if the bot has the necessary permissions in a given channel.
# Required permissions: view_channel, send_messages, embed_links.
# Args:
#     channel: The discord.TextChannel to check.
#     bot_member: The discord.Member object representing the bot in the guild.
# Returns: A tuple (bool, list[str]) indicating if permissions are sufficient
#          and a list of missing permission names if not.
def check_channel_permissions(channel, bot_member) -> tuple[bool, list[str]]:
    required_perms = ["view_channel", "send_messages", "embed_links"]
    missing = [perm for perm in required_perms if not getattr(channel.permissions_for(bot_member), perm)]
    return (not missing, missing)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EMBED SENDING UTILITY                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- send_embed ---
# A robust utility for sending embeds to a specified channel.
# Handles finding the channel via ID, server config, or interaction.
# Checks for necessary permissions before sending.
# Supports sending text content alongside the embed and attaching images.
# Logs errors encountered during sending.
# Args:
#     bot: The discord.Client instance.
#     embed: (Optional) The discord.Embed object to send. Can also be a string, which will be used as the embed description.
#     **kwargs: Additional arguments:
#         server_id: ID of the server to find the announcement channel for.
#         channel_id: Explicit ID of the channel to send to.
#         interaction: discord.Interaction object to derive server/channel from.
#         content: Optional text content to send with the embed.
#         image_path: Optional path to a local image file to attach.
#         color: Optional color for the embed if `embed` is provided as a string.
async def send_embed(bot, embed: Optional[discord.Embed] = None, **kwargs):
    try:
        server_id = kwargs.get('server_id')
        channel_id = kwargs.get('channel_id')
        if not channel_id and server_id:
             channel_id = get_announcement_channel_id(server_id)
        interaction = kwargs.get('interaction')
        if not channel_id and interaction and interaction.guild_id:
            channel_id = get_announcement_channel_id(interaction.guild_id)
        if not channel_id:
            logger.warning("send_embed called without a valid channel_id or server_id/interaction")
            return
        channel = bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"send_embed could not find channel with ID: {channel_id}")
            return
        if isinstance(embed, str):
            embed = discord.Embed(description=embed, color=kwargs.get('color', 5814783))
        bot_member = channel.guild.get_member(bot.user.id)
        can_send, missing_perms = check_channel_permissions(channel, bot_member)
        if not can_send:
            logger.error(f"Cannot send embed to channel {channel.name} ({channel_id}). Missing permissions: {', '.join(missing_perms)}")
            return
        if 'image_path' in kwargs:
            file = discord.File(kwargs['image_path'], filename="image.png")
            if embed:
                embed.set_image(url="attachment://image.png")
            await channel.send(content=kwargs.get('content'), embed=embed, file=file)
        else:
            await channel.send(content=kwargs.get('content'), embed=embed)
    except Forbidden:
        logger.error(f"Permission error sending embed to channel {channel_id}. Check bot permissions.")
    except HTTPException as e:
        logger.error(f"HTTP error sending embed to channel {channel_id}: {e}")
    except Exception as e:
        logger.exception(f"Error in send_embed to channel {channel_id}: {e}")
