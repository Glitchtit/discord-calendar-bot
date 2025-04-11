from discord import Interaction, Client
from bot.events import GROUPED_CALENDARS, TAG_NAMES
from utils.logging import logger

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

async def register(bot: Client):
    @bot.tree.command(name="who")
    async def who_command(interaction: Interaction):
        """List configured calendars and users"""
        await handle_who_command(interaction)
