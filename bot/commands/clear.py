# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT CLEAR COMMAND HANDLER                        ║
# ║    Admin command to clear messages in the announcement channel             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Handles the `/clear` slash command.

Provides an administrative function to delete all messages from the configured
announcement channel for the server where the command is invoked.
Requires administrator permissions.
"""

import discord
from discord import Interaction, app_commands
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta, timezone
from utils.logging import logger
from config.server_config import get_announcement_channel_id

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CLEAR COMMAND HANDLER                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_clear_command ---
# The core logic for the /clear slash command (Admin only).
# 1. Checks if the command is used within a server (guild).
# 2. Verifies if the invoking user has administrator permissions.
# 3. Defers the interaction response (ephemeral, thinking) while processing.
# 4. Retrieves the announcement channel ID for the server using `get_announcement_channel_id`.
# 5. Handles cases where the announcement channel is not configured.
# 6. Fetches the channel object and verifies it's a text channel.
# 7. Checks if the bot has the necessary 'Manage Messages' permission in the channel.
# 8. Fetches all messages from the channel's history.
# 9. Separates messages into 'fresh' (within 14 days, deletable in bulk) and 'old' (older than 14 days, must be deleted individually).
# 10. Deletes messages in chunks (up to 100 at a time for bulk deletion).
# 11. Includes `asyncio.sleep(1)` delays between deletion operations (especially for old messages) to avoid hitting Discord API rate limits.
# 12. Sends a confirmation message upon successful completion.
# 13. Includes specific error handling for `discord.Forbidden` (missing permissions) and `discord.HTTPException` (API errors), as well as general exceptions.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
async def handle_clear_command(interaction: Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
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
    bot_member = interaction.guild.me
    if not channel.permissions_for(bot_member).manage_messages:
         await interaction.followup.send(f"⚠️ I don't have permission to manage messages in {channel.mention}. Please grant me the 'Manage Messages' permission there.", ephemeral=True)
         return
    try:
        logger.info(f"Admin {interaction.user} ({interaction.user.id}) initiated channel clear for #{channel.name} ({channel.id}) in server {server_id}")
        messages = []
        async for msg in channel.history(limit=None):
            messages.append(msg)
        threshold = datetime.now(timezone.utc) - timedelta(days=14)
        total_deleted = 0
        for chunk in (messages[i:i+100] for i in range(0, len(messages), 100)):
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
                await asyncio.sleep(1)
            await asyncio.sleep(1)
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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /clear slash command with the bot's command tree.
# This function is typically called during bot setup.
# It defines the command name, description, and crucially, restricts its use
# to users with administrator permissions using `@app_commands.checks.has_permissions`.
# Args:
#     bot: The discord.ext.commands.Bot instance.
async def register(bot: commands.Bot):
    # --- clear_command ---
    # The actual slash command function decorated with `@bot.tree.command`.
    # This is the function directly invoked by Discord when the command is used.
    # It's decorated to require administrator permissions.
    # It simply calls `handle_clear_command` to execute the clearing logic.
    # Args:
    #     interaction: The discord.Interaction object.
    @bot.tree.command(name="clear", description="[Admin] Clears all messages in the announcement channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_command(interaction: discord.Interaction):
        """[Admin] Clears all messages in the announcement channel."""
        await handle_clear_command(interaction)
    logger.info("Registered /clear command.")

