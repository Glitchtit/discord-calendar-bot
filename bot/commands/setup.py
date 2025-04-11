from discord import app_commands
from discord.ui import View, Button, ButtonStyle
from ..core import Bot, Interaction
from ..utilities import _retry_discord_operation
from utils.logging import logger

async def setup(bot: Bot):
    """Register setup command with the bot"""
    try:
        bot.tree.add_command(setup_command)
        logger.info('✅ Setup command registered')
    except Exception as e:
        logger.error(f'❌ Failed to register setup command: {e}')
        raise

@app_commands.checks.has_permissions(manage_guild=True)
@_retry_discord_operation
async def setup_command(interaction: Interaction):
    """Guided calendar configuration workflow"""
    try:
        # Initial setup message with button-based workflow
        await interaction.response.send_message(
            "🔧 Let's configure your calendars!\n"
            "Please choose an option:",
            ephemeral=True,
            view=SetupView()
        )
    except Exception as e:
        logger.error(f'Setup command error: {e}')
        await interaction.followup.send(
            "⚠️ Failed to start setup. Please try again.",
            ephemeral=True
        )

class SetupView(View):
    """Interactive setup components"""
    def __init__(self):
        super().__init__(timeout=300)
        # Add buttons for different setup options
        self.add_item(Button(
            style=ButtonStyle.primary,
            label="Connect Google Calendar",
            custom_id="setup_gcal"
        ))
