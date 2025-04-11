from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import discord
from discord import Interaction
from utils.logging import logger
from utils.validators import detect_calendar_type
from bot.views import CalendarSetupView
from config.server_config import add_calendar, remove_calendar
from bot.events import reinitialize_events, get_service_account_email

async def handle_setup_command(interaction: Interaction):
    """Handle the setup command to configure calendars for a server"""
    try:
        # Check permissions first
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ You need administrator permissions to use this command.", ephemeral=True)
            return
            
        # Create the setup view with the right guild ID
        setup_view = CalendarSetupView(interaction.client, interaction.guild_id)
        
        # Send instructions with service account email
        service_email = get_service_account_email()
        embed = discord.Embed(
            title="🔧 Calendar Bot Setup",
            description=(
                "Welcome to the Calendar Bot setup wizard! You can configure your calendars with the buttons below.\n\n"
                f"**For Google Calendar:** Share your calendar with: `{service_email}`\n"
                "**For ICS Calendars:** Have the ICS URL ready\n\n"
                "Use the buttons below to add or manage calendars."
            ),
            color=0x4285F4  # Google blue
        )
        
        await interaction.response.send_message(embed=embed, view=setup_view, ephemeral=True)
        
    except Exception as e:
        logger.exception(f"Error in setup command: {e}")
        await interaction.response.send_message("⚠️ An error occurred during setup. Please try again later.", ephemeral=True)

async def register(bot):
    """Register setup command with the bot"""
    try:
        @bot.tree.command(name="setup", description="Configure calendar integration settings")
        @app_commands.checks.has_permissions(administrator=True)
        async def setup_command(interaction: Interaction):
            """Configure calendar settings for your server"""
            await handle_setup_command(interaction)
            
        logger.info('✅ Setup command registered')
    except Exception as e:
        logger.error(f'❌ Failed to register setup command: {e}')
        raise
