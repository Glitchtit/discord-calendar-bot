import discord  # Add missing import for discord
from discord.ui import View
from utils import load_server_config  # Ensure load_server_config is imported from utils.py
from bot import AddCalendarModal, CalendarRemoveView
from log import logger  # Add missing logger import

class CalendarSetupView(View):
    """Main view for the calendar setup wizard."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    async def on_timeout(self):
        logger.info(f"CalendarSetupView for guild {self.guild_id} timed out.")
        # Optionally notify the user about the timeout
        # ...

    @discord.ui.button(label="Add Calendar", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"User {interaction.user.id} clicked 'Add Calendar' in guild {self.guild_id}.")
        modal = AddCalendarModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Calendar", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"User {interaction.user.id} clicked 'Remove Calendar' in guild {self.guild_id}.")
        config = load_server_config(self.guild_id)
        if not isinstance(config, dict):
            logger.error(f"Failed to load server configuration for guild {self.guild_id}.")
            await interaction.response.send_message("Failed to load server configuration.", ephemeral=True)
            return
        calendars = config.get("calendars", [])
        if not calendars:
            await interaction.response.send_message("No calendars configured for this server yet.", ephemeral=True)
            return
        view = CalendarRemoveView(self.bot, self.guild_id, calendars)
        await interaction.response.send_message("Select the calendar you want to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="List Calendars", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_calendars_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"User {interaction.user.id} clicked 'List Calendars' in guild {self.guild_id}.")
        config = load_server_config(self.guild_id)
        if not isinstance(config, dict):
            logger.error(f"Failed to load server configuration for guild {self.guild_id}.")
            await interaction.response.send_message("Failed to load server configuration.", ephemeral=True)
            return
        calendars = config.get("calendars", [])
        if not calendars:
            await interaction.response.send_message(
                "No calendars configured for this server yet. Click 'Add Calendar' to get started.",
                ephemeral=True
            )
            return
        lines = ["**Configured Calendars:**\n"]
        for cal in calendars:
            lines.append(f"- {cal.get('name', 'Unnamed Calendar')} (ID: {cal.get('id', 'unknown')})")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
