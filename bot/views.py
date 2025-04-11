import discord
from discord.ui import View, Modal, Button, Select, TextInput
from config.server_config import add_calendar, remove_calendar, load_server_config  # Import all server config functions from server_config
from utils.logging import logger
from bot.events import reinitialize_events
from utils.validators import detect_calendar_type
# Removing this import to fix circular dependency
# from bot.core import Bot

class AddCalendarModal(Modal, title="Add Calendar"):
    """Modal form for adding a new calendar."""
    calendar_url = TextInput(
        label="Calendar URL or ID",
        placeholder="Google Calendar ID or ICS URL",
        required=True,
        style=discord.TextStyle.short
    )
    display_name = TextInput(
        label="Calendar Display Name (Optional)",
        placeholder="e.g. 'Work Calendar' or 'Family Events'",
        required=False,
        style=discord.TextStyle.short
    )

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the form submission."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        calendar_url = self.calendar_url.value.strip()
        display_name = self.display_name.value.strip() or "Unnamed Calendar"

        # Detect calendar type
        calendar_type = detect_calendar_type(calendar_url)
        
        # If we couldn't detect the calendar type, inform the user
        if not calendar_type:
            await interaction.followup.send(
                "❌ Could not detect calendar type. Please provide either a Google Calendar ID or an ICS URL.",
                ephemeral=True
            )
            return
            
        # Test the calendar connection before adding
        from utils.validators import test_calendar_connection
        
        await interaction.followup.send(
            f"⏳ Testing connection to calendar...",
            ephemeral=True
        )
        
        success, message = await test_calendar_connection(calendar_type, calendar_url)
        
        # If the connection test failed, don't add the calendar
        if not success:
            await interaction.followup.send(
                f"❌ Connection test failed: {message}\n\nPlease check the calendar ID/URL and try again.",
                ephemeral=True
            )
            return

        # Add the calendar
        calendar_data = {
            'type': calendar_type,
            'id': calendar_url,
            'user_id': str(interaction.user.id),
            'name': display_name
        }
        
        success, add_message = add_calendar(self.guild_id, calendar_data)

        # Reload calendar configuration and reinitialize events
        if success:
            try:
                # Inform user the calendar passed connection test
                await interaction.followup.send(
                    f"✅ {message}\n\nAdding calendar to your configuration...",
                    ephemeral=True
                )
                
                # Reinitialize events
                await reinitialize_events()
                
                # Final success message
                await interaction.followup.send(
                    f"✅ Calendar **{display_name}** has been added successfully!",
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"Error during reinitialization: {e}")
                await interaction.followup.send(
                    f"⚠️ Calendar added but there was an error refreshing events: {str(e)}",
                    ephemeral=True
                )
        else:
            # Something went wrong during the add_calendar operation
            await interaction.followup.send(
                f"❌ {add_message}",
                ephemeral=True
            )

class CalendarRemoveView(View):
    """View for selecting which calendar to remove."""
    def __init__(self, bot, guild_id, calendars):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.calendars = calendars

        # Create the dropdown
        self.update_dropdown()

    def update_dropdown(self):
        """Update the dropdown with the list of calendars."""
        self.clear_items()
        select = Select(placeholder="Select calendar to remove...", min_values=1, max_values=1)
        for cal in self.calendars:
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_id = cal.get("id", "unknown")
            select.add_option(
                label=cal_name,
                value=cal_id,
                description=f"ID: {cal_id}"
            )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle calendar selection for removal."""
        calendar_id = interaction.data["values"][0]
        confirm_view = ConfirmRemovalView(self.bot, self.guild_id, calendar_id)
        await interaction.response.send_message(
            f"Are you sure you want to remove this calendar?\n`{calendar_id}`",
            view=confirm_view,
            ephemeral=True
        )

class ConfirmRemovalView(View):
    """Confirmation view for calendar removal."""
    def __init__(self, bot, guild_id, calendar_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_id = calendar_id

    @discord.ui.button(label="Confirm Removal", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove the calendar when confirmed."""
        # Create removal data structure
        removal_data = {
            'calendar_id': self.calendar_id,
            'confirmation_token': str(interaction.id),
            'initiator_id': interaction.user.id
        }
        success, message = remove_calendar(self.guild_id, removal_data)

        # Reload calendar configuration and reinitialize events
        if success:
            try:
                await reinitialize_events()
            except Exception as e:
                logger.error(f"Error during reinitialization: {e}")

        await interaction.response.send_message(
            f"{'✅' if success else '❌'} {message}",
            ephemeral=True
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the removal."""
        await interaction.response.send_message("Calendar removal cancelled.", ephemeral=True)
        self.stop()

class CalendarSetupView(View):
    """Main view for the calendar setup wizard."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    async def on_timeout(self):
        logger.info(f"CalendarSetupView for guild {self.guild_id} timed out.")
        # Optionally notify the user about the timeout
        await self.bot.get_guild(self.guild_id).system_channel.send(
            "The calendar setup session has timed out. Please restart the setup process."
        )

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
