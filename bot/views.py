import discord
from discord.ui import View, Modal, Button, Select, TextInput, ChannelSelect # Added ChannelSelect
from config.server_config import add_calendar, remove_calendar, load_server_config, set_announcement_channel, get_announcement_channel_id # Added set/get announcement channel
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
    # Removed calendar_scope input field - will be handled by a dropdown after modal submission

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the form submission."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        calendar_url = self.calendar_url.value.strip()
        display_name = self.display_name.value.strip()

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

        # Extract calendar name from the connection test message if no display name was provided
        if not display_name and success:
            try:
                # Extract the name from the success message, which is between single quotes
                import re
                name_match = re.search(r"'(.*?)'", message)
                if name_match:
                    display_name = name_match.group(1)
                else:
                    display_name = "Unnamed Calendar"
            except Exception:
                display_name = "Unnamed Calendar"
        elif not display_name:
            display_name = "Unnamed Calendar"

        # Now show the user selection view for assigning the calendar
        user_selector = CalendarUserSelectView(
            self.bot, 
            self.guild_id, 
            {
                'type': calendar_type,
                'id': calendar_url,
                'name': display_name,
                'user_id': None  # This will be set by the user selector view
            },
            message
        )
        
        await interaction.followup.send(
            f"✅ {message}\n\nPlease select which user(s) to assign this calendar to:",
            view=user_selector,
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
        # Log the removal attempt
        logger.debug(f"Attempting to remove calendar with ID: {self.calendar_id} from guild {self.guild_id}")
        
        # Call remove_calendar with the proper parameters - direct calendar_id, not a dict
        success, message = remove_calendar(self.guild_id, self.calendar_id)

        # Reload calendar configuration and reinitialize events
        if success:
            try:
                logger.info(f"Successfully removed calendar {self.calendar_id}, reinitializing events")
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

# View for selecting the announcement channel
class AnnouncementChannelView(View):
    """View for selecting the announcement channel."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id

        # Create the channel select dropdown
        self.channel_select = ChannelSelect(
            placeholder="Select the announcement channel...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text] # Only allow text channels
        )
        self.channel_select.callback = self.select_callback
        self.add_item(self.channel_select)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle channel selection."""
        selected_channel = interaction.data["values"][0] # Channel ID as string
        channel_id = int(selected_channel)

        # Save the channel ID to server config
        success, message = set_announcement_channel(self.guild_id, channel_id)

        if success:
            channel = self.bot.get_channel(channel_id)
            channel_mention = channel.mention if channel else f"ID: {channel_id}"
            await interaction.response.send_message(f"✅ Announcement channel set to {channel_mention}.", ephemeral=True)
            logger.info(f"Announcement channel for guild {self.guild_id} set to {channel_id}")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
            logger.error(f"Failed to set announcement channel for guild {self.guild_id}: {message}")
        self.stop() # Stop the view after selection

class CalendarSetupView(View):
    """Main view for the calendar setup wizard."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        # Add button to set announcement channel dynamically
        self.update_announcement_button()

    async def on_timeout(self):
        logger.info(f"CalendarSetupView for guild {self.guild_id} timed out.")
        # Optionally notify the user about the timeout
        #await self.bot.get_guild(self.guild_id).system_channel.send(
        #    "The calendar setup session has timed out. Please restart the setup process."
        #)

    def update_announcement_button(self):
        """Adds or updates the announcement channel button based on current config."""
        # Remove existing button if it exists
        for item in self.children[:]: # Iterate over a copy
            if isinstance(item, Button) and item.custom_id == "set_announcement_channel_button":
                self.remove_item(item)

        # Get current channel ID
        current_channel_id = get_announcement_channel_id(self.guild_id)
        channel = self.bot.get_channel(current_channel_id) if current_channel_id else None
        
        button_label = "Set Announcement Channel"
        button_style = discord.ButtonStyle.secondary
        if channel:
            button_label = f"Announcements: #{channel.name}"
            button_style = discord.ButtonStyle.success
        elif current_channel_id: # ID exists but channel not found (maybe deleted?)
             button_label = f"Announcements: ID {current_channel_id} (Not Found)"
             button_style = discord.ButtonStyle.danger


        announcement_button = Button(
            label=button_label,
            style=button_style,
            emoji="📢",
            custom_id="set_announcement_channel_button" # Add custom_id for identification
        )
        announcement_button.callback = self.set_announcement_channel_button
        # Insert the button before the 'List Calendars' button if possible, otherwise append
        list_button_index = -1
        for i, item in enumerate(self.children):
             if isinstance(item, Button) and item.label == "List Calendars":
                 list_button_index = i
                 break
        if list_button_index != -1:
             self.add_item(announcement_button)
             # Move button before list button - requires rebuilding items list
             items = self.children[:] # Copy items
             self.clear_items()
             for i, item in enumerate(items):
                 if i == list_button_index:
                     self.add_item(announcement_button) # Add announcement button first
                 if item.custom_id != "set_announcement_channel_button": # Avoid adding it twice
                    self.add_item(item) # Add original item
        else:
             self.add_item(announcement_button) # Append if list button not found


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

    # Callback for the new announcement channel button
    async def set_announcement_channel_button(self, interaction: discord.Interaction):
        """Callback for the 'Set Announcement Channel' button."""
        logger.info(f"User {interaction.user.id} clicked 'Set Announcement Channel' in guild {self.guild_id}.")
        # Show the channel selection view
        view = AnnouncementChannelView(self.bot, self.guild_id)
        await interaction.response.send_message("Please select the channel where announcements should be posted:", view=view, ephemeral=True)
        
        # Wait for the view to finish (optional, depends on desired UX)
        await view.wait()
        
        # Update the button label/style in the original setup view
        self.update_announcement_button()
        # We need to edit the original message to reflect the button change
        await interaction.edit_original_response(view=self)

class CalendarUserSelectView(View):
    """View for selecting users to assign a calendar to."""
    def __init__(self, bot, guild_id, calendar_data, connection_message):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_data = calendar_data
        self.connection_message = connection_message
        
        # Create the dropdown for user selection
        self.create_user_dropdown()
    
    def create_user_dropdown(self):
        """Create the dropdown with server members and 'Everyone' option."""
        guild = self.bot.get_guild(self.guild_id)
        
        # Create the dropdown
        select = Select(
            placeholder="Select user to assign calendar to...", 
            min_values=1, 
            max_values=1
        )
        
        # Add 'Everyone' option
        select.add_option(
            label="Everyone (Server-wide)",
            value="server",
            description="Make this calendar available to everyone",
            emoji="👥"
        )
        
        # Add guild members (if we can access them)
        if guild and guild.members:
            # Sort members by name for easier selection
            sorted_members = sorted(guild.members, key=lambda m: m.display_name.lower())
            
            for member in sorted_members:
                # Skip bots
                if member.bot:
                    continue
                    
                # Add member to dropdown
                select.add_option(
                    label=member.display_name,
                    value=str(member.id),
                    description=f"{member.name}#{member.discriminator}" if member.discriminator != "0" else member.name,
                    emoji="👤"
                )
        
        # Set callback and add to view
        select.callback = self.user_selected
        self.add_item(select)
    
    async def user_selected(self, interaction: discord.Interaction):
        """Handle user selection for calendar assignment."""
        selected_value = interaction.data["values"][0]
        
        # Check if "server" (Everyone) was selected
        if selected_value == "server":
            # Server-wide calendar - set user_id to "1"
            self.calendar_data["user_id"] = "1"
            user_display = "everyone in the server"
        else:
            # User-specific calendar
            self.calendar_data["user_id"] = selected_value
            # Try to get user info for display
            try:
                guild = self.bot.get_guild(self.guild_id)
                member = guild.get_member(int(selected_value))
                user_display = f"{member.display_name}" if member else f"user ID {selected_value}"
            except:
                user_display = f"user ID {selected_value}"
        
        # Add the calendar to the server config
        success, add_message = add_calendar(self.guild_id, self.calendar_data)
        
        # Reload calendar configuration and reinitialize events if successful
        if success:
            try:
                await interaction.response.defer(ephemeral=True)
                
                # Reinitialize events
                logger.info("Calling reinitialize_events from user_selected callback")
                await reinitialize_events()
                
                # Success message
                await interaction.followup.send(
                    f"✅ Calendar **{self.calendar_data['name']}** has been added successfully and assigned to **{user_display}**!",
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"Error during reinitialization: {e}")
                await interaction.followup.send(
                    f"⚠️ Calendar added and assigned to {user_display}, but there was an error refreshing events: {str(e)}",
                    ephemeral=True
                )
        else:
            # Something went wrong during the add_calendar operation
            await interaction.response.send_message(
                f"❌ {add_message}",
                ephemeral=True
            )
