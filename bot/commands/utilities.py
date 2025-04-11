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

async def _retry_discord_operation(operation: Coroutine, max_retries=3):
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return await operation()
        except Forbidden as e:
            raise e
        except (HTTPException, GatewayNotFound) as e:
            backoff = (2 ** attempt) + random.random()
            await asyncio.sleep(backoff)
            last_error = e
    
    if last_error:
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
