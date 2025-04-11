from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import discord
from discord import Interaction
from utils.logging import logger
from utils.validators import detect_calendar_type
from bot.views import CalendarSetupView
from config.server_config import add_calendar, remove_calendar, add_admin_user, remove_admin_user, is_superadmin
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
            """
            Configure calendar settings for your server. Accessible only by admins and superadmin.
            """
            server_id = interaction.guild_id
            user_id = str(interaction.user.id)

            # Check if the user is an admin or superadmin
            from config.server_config import get_admin_user_ids, is_superadmin
            admin_ids = get_admin_user_ids(server_id)

            if user_id not in admin_ids and not is_superadmin(server_id, user_id):
                await interaction.response.send_message("⚠️ You do not have permission to use this command.", ephemeral=True)
                return

            await handle_setup_command(interaction)
            
        @bot.tree.command(name="admins", description="Manage server admins (Admin only)")
        @app_commands.checks.has_permissions(administrator=True)
        async def admins_command(interaction: Interaction, action: str, user: discord.Member):
            """
            Command to manage server admins. Superadmins cannot be removed.

            Args:
                interaction: The interaction object
                action: The action to perform (add/remove)
                user: The user to add or remove
            """
            server_id = interaction.guild_id
            user_id = str(user.id)

            if action not in ["add", "remove"]:
                await interaction.response.send_message("Invalid action. Use 'add' or 'remove'.", ephemeral=True)
                return

            if action == "add":
                success, message = add_admin_user(server_id, user_id)
                await interaction.response.send_message(message, ephemeral=True)

            elif action == "remove":
                if is_superadmin(server_id, user_id):
                    await interaction.response.send_message("Cannot remove the superadmin (server owner).", ephemeral=True)
                else:
                    success, message = remove_admin_user(server_id, user_id)
                    await interaction.response.send_message(message, ephemeral=True)

        logger.info('✅ Setup command registered')
    except Exception as e:
        logger.error(f'❌ Failed to register setup command: {e}')
        raise
