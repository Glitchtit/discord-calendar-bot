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
def check_channel_permissions(channel, bot_member) -> tuple[bool, list[str]]:
    required_perms = ["view_channel", "send_messages", "embed_links"]
    missing = [perm for perm in required_perms if not getattr(channel.permissions_for(bot_member), perm)]
    return (not missing, missing)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EMBED SENDING UTILITY                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝
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
