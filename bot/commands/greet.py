import discord
from discord import Interaction
from utils.ai_helpers import generate_greeting, generate_image
from utils.logging import logger
from .utilities import send_embed

# Greet command implementation
async def handle_greet_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        # Let the user know we're working on it
        await interaction.followup.send("🧙‍♂️ Summoning the herald... please wait.")
        
        # Generate the greeting text with AI
        greeting_text, persona = await generate_greeting([], [])
        
        # Generate image based on the greeting
        image_path = await generate_image(greeting_text, persona)
        
        # Create embed for the message
        embed = discord.Embed(
            title="🌅 Morning Greeting",
            description=greeting_text,
            color=0xf1c40f  # Golden color
        )
        
        # Add image if one was generated
        if image_path:
            # Send the message with attachment
            await send_embed(
                interaction.client,
                embed=embed,
                image_path=image_path
            )
            await interaction.followup.send("✅ The herald has delivered their message!")
        else:
            # Send text-only message if image generation failed
            await send_embed(
                interaction.client,
                embed=embed
            )
            await interaction.followup.send("✅ The herald has delivered their message (without illustration).")
            
    except Exception as e:
        logger.error(f"Error in greet command: {e}")
        await interaction.followup.send("⚠️ Failed to generate greeting. The royal illustrator seems to be on vacation.")

async def register(bot: discord.Client):
    @bot.tree.command(name="greet")
    async def greet_command(interaction: discord.Interaction):
        """Post morning greeting with generated image"""
        await handle_greet_command(interaction)
