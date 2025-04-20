# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                   CALENDAR BOT WHO COMMAND HANDLER                       ║
# ║    Lists all configured calendars and their associated users/tags         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from discord import Interaction, Client
from bot.events import GROUPED_CALENDARS, TAG_NAMES
from utils.logging import logger

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ WHO COMMAND HANDLER                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_who_command ---
# The core logic for the /who slash command.
# Iterates through the `GROUPED_CALENDARS` dictionary.
# Formats a list showing each user/tag (using `TAG_NAMES` for friendly names)
# and the names of the calendars associated with them.
# Sends the list as an ephemeral message.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
async def handle_who_command(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        lines = ["📅 **Configured Calendars**"]
        for user_id, sources in GROUPED_CALENDARS.items():
            lines.append(f"**{TAG_NAMES.get(user_id, user_id)}**")
            lines.extend(f"- {s['name']}" for s in sources)
        await interaction.followup.send("\n".join(lines), ephemeral=True)
    except Exception as e:
        logger.error(f"Who error: {e}")
        await interaction.followup.send("⚠️ Failed to list calendars")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /who slash command with the bot's command tree.
# Args:
#     bot: The discord.Client instance to register the command with.
async def register(bot: Client):
    # --- who_command ---
    # The actual slash command function invoked by Discord.
    # Calls `handle_who_command` to process the request.
    # Args:
    #     interaction: The discord.Interaction object.
    @bot.tree.command(name="who")
    async def who_command(interaction: Interaction):
        """List configured calendars and users"""
        await handle_who_command(interaction)
