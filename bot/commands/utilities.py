"""
command utilities: Shared helper functions for command modules
"""

import discord
from discord.errors import Forbidden, HTTPException, GatewayNotFound
from typing import Coroutine, Optional
import asyncio
import random
import os
import logging

logger = logging.getLogger(__name__)

async def _retry_discord_operation(operation, max_retries=3):
    """
    Retry a Discord operation with exponential backoff.
    Works with both async and sync functions.
    
    Args:
        operation: Function to retry (can be async or sync)
        max_retries: Maximum number of retries
        
    Returns:
        The result of the operation
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Check if the operation is a coroutine function (async)
            if asyncio.iscoroutinefunction(operation):
                return await operation()
            else:
                # Handle regular functions
                return operation()
                
        except Exception as e:
            last_error = e
            wait_time = (2 ** attempt) + (0.1 * attempt)
            logger.warning(f"Discord operation failed (attempt {attempt+1}/{max_retries}), retrying in {wait_time:.1f}s: {e}")
            await asyncio.sleep(wait_time)
    
    # If we get here, all retries failed
    logger.error(f"Discord operation failed after {max_retries} attempts: {last_error}")
    raise last_error

def check_channel_permissions(channel, bot_member) -> tuple[bool, list[str]]:
    required_perms = ["view_channel", "send_messages", "embed_links"]
    missing = [perm for perm in required_perms if not getattr(channel.permissions_for(bot_member), perm)]
    return (not missing, missing)

async def send_embed(bot, embed: Optional[discord.Embed] = None, **kwargs):
    try:
        channel = bot.get_channel(int(os.getenv("ANNOUNCEMENT_CHANNEL_ID")))
        if not channel:
            return

        if isinstance(embed, str):
            embed = discord.Embed(description=embed, color=kwargs.get('color', 5814783))
        
        if 'image_path' in kwargs:
            file = discord.File(kwargs['image_path'], filename="image.png")
            embed.set_image(url="attachment://image.png")
            await channel.send(content=kwargs.get('content'), embed=embed, file=file)
        else:
            await channel.send(content=kwargs.get('content'), embed=embed)
    except Exception as e:
        logger.exception(f"Error in send_embed: {e}")
