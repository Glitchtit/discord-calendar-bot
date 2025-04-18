"""
clear.py: Admin command to clear messages in the announcement channel.
"""

import discord
from discord import Interaction, app_commands
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta, timezone

from utils.logging import logger
from config.server_config import get_announcement_channel_id

async def handle_clear_command(interaction: Interaction):
    """Handles the /clear command logic."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Check for administrator permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "⚠️ You need administrator permissions to use this command.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    server_id = interaction.guild_id
    channel_id = get_announcement_channel_id(server_id)

    if not channel_id:
        await interaction.followup.send("⚠️ Announcement channel is not configured for this server. Use `/setup` to configure it.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.followup.send(f"⚠️ Announcement channel (ID: {channel_id}) not found or is not a text channel.", ephemeral=True)
        return

    # Check bot permissions in the target channel
    bot_member = interaction.guild.me
    if not channel.permissions_for(bot_member).manage_messages:
         await interaction.followup.send(f"⚠️ I don't have permission to manage messages in {channel.mention}. Please grant me the 'Manage Messages' permission there.", ephemeral=True)
         return

    try:
        logger.info(f"Admin {interaction.user} ({interaction.user.id}) initiated channel clear for #{channel.name} ({channel.id}) in server {server_id}")

        # Fetch all messages
        messages = []
        async for msg in channel.history(limit=None):
            messages.append(msg)

        # Threshold for bulk delete (msg younger than 14 days)
        threshold = datetime.now(timezone.utc) - timedelta(days=14)
        total_deleted = 0

        # Process in 100‑message chunks
        for chunk in (messages[i:i+100] for i in range(0, len(messages), 100)):
            # split into fresh vs old
            fresh = [m for m in chunk if m.created_at > threshold]
            old   = [m for m in chunk if m.created_at <= threshold]

            if fresh:
                try:
                    await channel.delete_messages(fresh)
                    total_deleted += len(fresh)
                except discord.HTTPException as e:
                    logger.error(f"HTTP error bulk deleting fresh msgs: {e}")

            for m in old:
                try:
                    await m.delete()
                    total_deleted += 1
                except discord.HTTPException as e:
                    logger.error(f"HTTP error deleting old msg {m.id}: {e}")
                await asyncio.sleep(1)  # small pause per delete

            await asyncio.sleep(1)  # pause between chunks

        await interaction.followup.send(
            f"✅ Successfully deleted {total_deleted} messages from {channel.mention}.",
            ephemeral=True
        )
        logger.info(f"Successfully deleted {total_deleted} messages from channel {channel.id}")

    except discord.Forbidden:
        logger.warning(f"Missing 'Manage Messages' permission in channel {channel.id} for server {server_id}")
        await interaction.followup.send(f"⚠️ I don't have permission to delete messages in {channel.mention}.", ephemeral=True)
    except discord.HTTPException as e:
        logger.error(f"HTTP error during message purge in channel {channel.id}: {e}")
        await interaction.followup.send(f"❌ An error occurred while trying to clear messages: {e}", ephemeral=True)
    except Exception as e:
        logger.exception(f"Unexpected error during /clear command for channel {channel.id}: {e}")
        await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)


async def register(bot: commands.Bot):
    """Register the /clear command."""
    @bot.tree.command(name="clear", description="[Admin] Clears all messages in the announcement channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_command(interaction: discord.Interaction):
        await handle_clear_command(interaction)
    logger.info("Registered /clear command.")

