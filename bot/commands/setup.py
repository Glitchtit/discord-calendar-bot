# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT SETUP COMMAND HANDLER                      ║
# ║    Handles server calendar configuration and admin management             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import discord
from discord import Interaction
from utils.logging import logger
from utils.validators import detect_calendar_type
from bot.views import CalendarSetupView
from config.server_config import add_calendar, remove_calendar, add_admin_user, remove_admin_user, is_superadmin
from bot.events import reinitialize_events, get_service_account_email

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SETUP COMMAND HANDLER                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_setup_command ---
# The core logic for the /setup slash command (Admin only).
# Checks for administrator permissions.
# Creates and sends the main `CalendarSetupView` which contains buttons for adding/removing calendars
# and setting the announcement channel. Includes an informational embed.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
async def handle_setup_command(interaction: Interaction):
    try:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ You need administrator permissions to use this command.", ephemeral=True)
            return
        setup_view = CalendarSetupView(interaction.client, interaction.guild_id)
        service_email = get_service_account_email()
        embed = discord.Embed(
            title="🔧 Calendar Bot Setup",
            description=(
                "Welcome to the Calendar Bot setup wizard! You can configure your calendars with the buttons below.\n\n"
                f"**For Google Calendar:** Share your calendar with: `{service_email}`\n"
                "**For ICS Calendars:** Have the ICS URL ready\n\n"
                "Use the buttons below to add or manage calendars."
            ),
            color=0x4285F4
        )
        await interaction.response.send_message(embed=embed, view=setup_view, ephemeral=True)
    except Exception as e:
        logger.exception(f"Error in setup command: {e}")
        await interaction.response.send_message("⚠️ An error occurred during setup. Please try again later.", ephemeral=True)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /setup and /admins slash commands with the bot's command tree.
# Args:
#     bot: The discord.Client or discord.ext.commands.Bot instance.
async def register(bot):
    try:
        # --- setup_command ---
        # The actual slash command function invoked by Discord for /setup.
        # Requires administrator permissions and checks if the user is a configured bot admin.
        # Calls `handle_setup_command` to display the setup view.
        # Args:
        #     interaction: The discord.Interaction object.
        @bot.tree.command(name="setup", description="Configure calendar integration settings")
        @app_commands.checks.has_permissions(administrator=True)
        async def setup_command(interaction: Interaction):
            server_id = interaction.guild_id
            user_id = str(interaction.user.id)
            from config.server_config import get_admin_user_ids, is_superadmin
            admin_ids = get_admin_user_ids(server_id)
            if user_id not in admin_ids and not is_superadmin(server_id, user_id):
                await interaction.response.send_message("⚠️ You do not have permission to use this command.", ephemeral=True)
                return
            await handle_setup_command(interaction)

        # --- admins_command ---
        # The actual slash command function invoked by Discord for /admins.
        # Requires administrator permissions.
        # Allows adding or removing bot administrators for the server.
        # Args:
        #     interaction: The discord.Interaction object.
        #     action: The action to perform ("add" or "remove").
        #     user: The discord.Member to add or remove as an admin.
        @bot.tree.command(name="admins", description="Manage server admins (Admin only)")
        @app_commands.checks.has_permissions(administrator=True)
        async def admins_command(interaction: Interaction, action: str, user: discord.Member):
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
