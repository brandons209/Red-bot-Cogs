import asyncio
import re
import uuid
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Any

from dateutil.tz import tzlocal
import discord
from redbot.core import commands, config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.commands.converter import parse_timedelta

from .views import CampaignView


class Campaign:
    """Represents a feedback campaign."""

    __version__ = "1.0.0"

    def __init__(self, campaign_id: str, guild_id: int, name: str, description: str):
        self.campaign_id = campaign_id
        self.guild_id = guild_id
        self.name = name
        self.description = description
        self.questions: List[Dict[str, Any]] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.active = False
        self.message_id: Optional[int] = None
        self.channel_id: Optional[int] = None

    def add_question(
        self,
        question_text: str,
        question_type: str,
        options: Optional[List[str]] = None,
        validation_regex: Optional[str] = None,
        validation_error_message: Optional[str] = None,
    ) -> str:
        """Add a question to the campaign and return the question ID."""
        question_id = str(uuid.uuid4())[:8]  # Short UUID for readability
        question = {
            "question_id": question_id,
            "text": question_text,
            "type": question_type,
            "options": options or [],
            "validation_regex": validation_regex,
            "validation_error_message": validation_error_message or "Invalid input format.",
        }
        self.questions.append(question)
        return question_id

    def remove_question(self, question_id: str) -> bool:
        """Remove a question from the campaign. Returns True if successful."""
        for i, question in enumerate(self.questions):
            if question["question_id"] == question_id:
                del self.questions[i]
                return True
        return False

    def get_question(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Get a question by its ID."""
        for question in self.questions:
            if question["question_id"] == question_id:
                return question
        return None

    def is_expired(self) -> bool:
        """Check if the campaign has expired."""
        if not self.end_time:
            return False
        return discord.utils.utcnow() > self.end_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert campaign to dictionary for storage."""
        return {
            "campaign_id": self.campaign_id,
            "guild_id": self.guild_id,
            "name": self.name,
            "description": self.description,
            "questions": self.questions,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "active": self.active,
            "message_id": self.message_id,
            "channel_id": self.channel_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Campaign":
        """Create campaign from dictionary."""
        campaign = cls(data["campaign_id"], data["guild_id"], data["name"], data["description"])
        campaign.questions = data.get("questions", [])
        campaign.start_time = datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None
        campaign.end_time = datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        campaign.active = data.get("active", False)
        campaign.message_id = data.get("message_id")
        campaign.channel_id = data.get("channel_id")
        return campaign


class CampaignCog(commands.Cog):
    """A cog for creating and managing user feedback campaigns."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = config.Config.get_conf(self, identifier=1234567890, force_registration=True)

        # Default configuration structure
        default_guild = {
            "campaigns": {},  # campaign_id -> campaign_data
            "responses": {},  # campaign_id -> {user_id -> response_data}
        }

        self.config.register_guild(**default_guild)

        # Store active campaign timers
        self.campaign_timers: Dict[str, asyncio.Task] = {}

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        for task in self.campaign_timers.values():
            task.cancel()

    async def get_campaign(self, guild_id: int, campaign_id_or_name: str) -> Optional[Campaign]:
        """Retrieve a campaign by ID."""
        campaigns_data = await self.config.guild_from_id(guild_id).campaigns()
        if campaign_id_or_name in campaigns_data:
            return Campaign.from_dict(campaigns_data[campaign_id_or_name])
        else:  # by name
            for c, data in campaigns_data.items():
                if data["name"] == campaign_id_or_name:
                    return Campaign.from_dict(campaigns_data[c])
        return None

    async def save_campaign(self, campaign: Campaign):
        """Save a campaign to config."""
        guild_config = self.config.guild_from_id(campaign.guild_id)
        async with guild_config.campaigns() as campaigns:
            campaigns[campaign.campaign_id] = campaign.to_dict()

    async def delete_campaign(self, guild_id: int, campaign_id: str):
        """Delete a campaign and its responses."""
        guild_config = self.config.guild_from_id(guild_id)
        async with guild_config.campaigns() as campaigns:
            if campaign_id in campaigns:
                del campaigns[campaign_id]

        async with guild_config.responses() as responses:
            if campaign_id in responses:
                del responses[campaign_id]

        # Cancel timer if exists
        if campaign_id in self.campaign_timers:
            self.campaign_timers[campaign_id].cancel()
            del self.campaign_timers[campaign_id]

    async def get_user_response(self, guild_id: int, campaign_id: str, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user's response to a campaign."""
        responses = await self.config.guild_from_id(guild_id).responses()
        return responses.get(campaign_id, {}).get(str(user_id))

    async def save_user_response(self, guild_id: int, campaign_id: str, user_id: int, answers: Dict[str, str]):
        """Save a user's response to a campaign."""
        guild_config = self.config.guild_from_id(guild_id)
        async with guild_config.responses() as responses:
            if campaign_id not in responses:
                responses[campaign_id] = {}

            responses[campaign_id][str(user_id)] = {
                "user_id": user_id,
                "submission_time": discord.utils.utcnow().isoformat(),
                "answers": answers,
            }

    async def _stop_campaign_timer(self, campaign_id: str, guild_id: int):
        """Timer function to automatically stop a campaign."""
        campaign = await self.get_campaign(guild_id, campaign_id)
        if campaign and campaign.active:
            campaign.active = False
            await self.save_campaign(campaign)

            # Notify in the channel where the campaign was posted
            if campaign.channel_id:
                channel = self.bot.get_channel(campaign.channel_id)
                if channel:
                    embed = discord.Embed(
                        title="Campaign Expired",
                        description=f"The campaign '{campaign.name}' has expired and is no longer accepting responses.",
                        color=discord.Color.red(),
                    )
                    await channel.send(embed=embed)

        # Remove from active timers
        if campaign_id in self.campaign_timers:
            del self.campaign_timers[campaign_id]

    @commands.group(name="campaign")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def campaign_group(self, ctx):
        """Campaign management commands."""
        pass

    @campaign_group.command(name="create")
    async def create_campaign(self, ctx, name: str, *, description: str):
        """Create a new feedback campaign.

        Usage: [p]campaign create "Campaign Name" Description of the campaign
        """
        if len(name) > 100:
            await ctx.send("Campaign name must be 100 characters or less.")
            return

        if len(description) > 500:
            await ctx.send("Campaign description must be 500 characters or less.")
            return

        campaign_id = str(uuid.uuid4())[:8]
        campaign = Campaign(campaign_id, ctx.guild.id, name, description)

        await self.save_campaign(campaign)

        embed = discord.Embed(
            title="Campaign Created",
            description=f"Campaign '{name}' has been created with ID: `{campaign_id}`",
            color=discord.Color.green(),
        )
        embed.add_field(name="Description", value=description, inline=False)
        embed.add_field(
            name="Next Steps",
            value="Use `[p]campaign questions add` to add questions to your campaign.",
            inline=False,
        )

        await ctx.send(embed=embed)

    @campaign_group.group(name="questions", aliases=["question"])
    async def questions(self, ctx: commands.Context):
        """Manage campaign questions"""
        pass

    @questions.command(name="add")
    async def add_question(
        self,
        ctx,
        campaign_id_or_name: str,
        question_type: Literal["short_text", "long_text", "number"],
        *,
        question_text: str,
    ):
        """Add a question to a campaign.

        Types: short_text, long_text, number

        Usage: [p]campaign questions add <campaign_id_or_name> <type> Question text here?
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if campaign.active:
            await ctx.send("Cannot modify an active campaign.")
            return

        if len(campaign.questions) >= 19:
            await ctx.send("Maximum of 19 questions per campaign.")
            return

        question_id = campaign.add_question(question_text, question_type)
        await self.save_campaign(campaign)

        embed = discord.Embed(
            title="Question Added",
            description=f"Question added to campaign '{campaign.name}'",
            color=discord.Color.green(),
        )
        embed.add_field(name="Question ID", value=question_id, inline=True)
        embed.add_field(name="Type", value=question_type, inline=True)
        embed.add_field(name="Text", value=question_text, inline=False)

        await ctx.send(embed=embed)

    @questions.command(name="choice")
    async def add_choice_question(
        self,
        ctx,
        campaign_id_or_name: str,
        question_type: Literal["multiple_choice", "single_choice"],
        question_text: str,
        *options,
    ):
        """Add a multiple choice question.

        Question type: "multiple_choice" or "single_choice"

        Usage: [p]campaign questions choice <campaign_id_or_name> <question_type> "Question text?" "Option 1" "Option 2" "Option 3"
        """
        if len(options) < 2:
            await ctx.send("Choice questions must have at least 2 options.")
            return

        if len(options) > 10:
            await ctx.send("Choice questions can have at most 10 options.")
            return

        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if campaign.active:
            await ctx.send("Cannot modify an active campaign.")
            return

        if len(campaign.questions) >= 19:
            await ctx.send("Maximum of 19 questions per campaign.")
            return

        question_id = campaign.add_question(question_text, question_type, list(options))
        await self.save_campaign(campaign)

        embed = discord.Embed(
            title="Choice Question Added",
            description=f"Question added to campaign '{campaign.name}'",
            color=discord.Color.green(),
        )
        embed.add_field(name="Question ID", value=question_id, inline=True)
        embed.add_field(name="Type", value=question_type, inline=True)
        embed.add_field(name="Text", value=question_text, inline=False)
        embed.add_field(name="Options", value="\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options)), inline=False)

        await ctx.send(embed=embed)

    @questions.command(name="validation")
    async def add_validation(
        self,
        ctx,
        campaign_id_or_name: str,
        question_id: str,
        regex_pattern: str,
        *,
        error_message: Optional[str] = None,
    ):
        """Add input validation to a question.

        Usage: [p]campaign questions validation <campaign_id_or_name> <question_id> "regex_pattern" Optional error message
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if campaign.active:
            await ctx.send("Cannot modify an active campaign.")
            return

        question = campaign.get_question(question_id)
        if not question:
            await ctx.send("Question not found.")
            return

        # Test if the regex is valid
        try:
            re.compile(regex_pattern)
        except re.error:
            await ctx.send("Invalid regex pattern.")
            return

        question["validation_regex"] = regex_pattern
        question["validation_error_message"] = error_message or "Input does not match required format."

        await self.save_campaign(campaign)

        embed = discord.Embed(
            title="Validation Added",
            description=f"Validation added to question in campaign '{campaign.name}'",
            color=discord.Color.green(),
        )
        embed.add_field(name="Question", value=question["text"], inline=False)
        embed.add_field(name="Regex Pattern", value=f"`{regex_pattern}`", inline=False)
        embed.add_field(name="Error Message", value=question["validation_error_message"], inline=False)

        await ctx.send(embed=embed)

    @questions.command(name="remove", aliases=["del", "delete", "rem"])
    async def remove_question(self, ctx, campaign_id_or_name: str, question_id: str):
        """Remove a question from a campaign.

        Usage: [p]campaign questions remove <campaign_id_or_name> <question_id>
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if campaign.active:
            await ctx.send("Cannot modify an active campaign.")
            return

        if campaign.remove_question(question_id):
            await self.save_campaign(campaign)
            await ctx.send(f"Question `{question_id}` removed from campaign '{campaign.name}'.")
        else:
            await ctx.send("Question not found.")

    @commands.command(name="clist")
    @commands.guild_only()
    async def list_campaigns(self, ctx):
        """List all campaigns in this server."""
        campaigns_data = await self.config.guild(ctx.guild).campaigns()

        if not campaigns_data:
            await ctx.send("No campaigns found in this server.")
            return

        embed = discord.Embed(
            title="Campaigns", description=f"Found {len(campaigns_data)} campaign(s)", color=discord.Color.blue()
        )

        for campaign_data in campaigns_data.values():
            campaign = Campaign.from_dict(campaign_data)
            status = "🟢 Active" if campaign.active else "🔴 Inactive"
            if campaign.is_expired():
                status = "⏰ Expired"

            embed.add_field(
                name=f"{campaign.name} (`{campaign.campaign_id}`)",
                value=f"{status}\n{len(campaign.questions)} questions\n{campaign.description[:100]}{'...' if len(campaign.description) > 100 else ''}",
                inline=True,
            )

        await ctx.send(embed=embed)

    @campaign_group.command(name="view")
    async def view_campaign(self, ctx, campaign_id_or_name: str):
        """View details of a specific campaign."""
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        embed = discord.Embed(
            title=f"Campaign: {campaign.name}", description=campaign.description, color=discord.Color.blue()
        )

        embed.add_field(name="ID", value=campaign.campaign_id, inline=True)
        embed.add_field(name="Status", value="🟢 Active" if campaign.active else "🔴 Inactive", inline=True)
        embed.add_field(name="Questions", value=str(len(campaign.questions)), inline=True)

        if campaign.start_time:
            embed.add_field(name="Started", value=campaign.start_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        if campaign.end_time:
            embed.add_field(name="Expires", value=campaign.end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        # Show questions
        if campaign.questions:
            questions_text = ""
            for i, question in enumerate(campaign.questions[:5]):  # Show first 5 questions
                questions_text += f"**{i+1}.** {question['text'][:100]}{'...' if len(question['text']) > 100 else ''}\n"
                questions_text += f"   Type: {question['type']}, ID: `{question['question_id']}`\n\n"

            if len(campaign.questions) > 5:
                questions_text += f"... and {len(campaign.questions) - 5} more questions"

            embed.add_field(name="Questions", value=questions_text, inline=False)

        await ctx.send(embed=embed)

    @campaign_group.command(name="start")
    async def start_campaign(self, ctx, campaign_id_or_name: str, duration: Optional[str] = None):
        """Start a campaign with optional duration.

        Duration format: 1d, 2h, 30m, 1d2h30m
        If no duration is provided, campaign runs until manually stopped.

        Usage: [p]campaign start <campaign_id_or_name> [duration]
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.questions:
            await ctx.send("Cannot start a campaign with no questions.")
            return

        if campaign.active:
            await ctx.send("Campaign is already active.")
            return

        # Parse duration if provided
        end_time = None
        if duration:
            try:
                end_time = parse_timedelta(duration)
            except ValueError as e:
                await ctx.send(f"Invalid duration format: {e}")
                return

        # Start the campaign
        campaign.active = True
        campaign.start_time = discord.utils.utcnow()
        end_time = end_time + campaign.start_time if end_time else None
        campaign.end_time = end_time

        await self.save_campaign(campaign)

        # Set up timer if duration was specified
        if end_time:
            duration_seconds = (end_time - discord.utils.utcnow()).total_seconds()
            if duration_seconds > 0:
                timer_task = asyncio.create_task(
                    self._campaign_timer(campaign.campaign_id, ctx.guild.id, duration_seconds)
                )
                self.campaign_timers[campaign.campaign_id] = timer_task

        embed = discord.Embed(
            title="Campaign Started",
            description=f"Campaign '{campaign.name}' is now active!",
            color=discord.Color.green(),
        )

        if end_time:
            embed.add_field(
                name="Expires", value=f"<t:{int(end_time.astimezone(tzlocal()).timestamp())}>", inline=False
            )
        else:
            embed.add_field(name="Duration", value="Indefinite (until manually stopped)", inline=False)

        embed.add_field(
            name="How to participate",
            value=f"Users can submit responses with: `{ctx.prefix}submit {campaign.name}`",
            inline=False,
        )

        await ctx.send(embed=embed)

    async def _campaign_timer(self, campaign_id: str, guild_id: int, duration_seconds: float):
        """Timer coroutine for campaign expiration."""
        await asyncio.sleep(duration_seconds)
        await self._stop_campaign_timer(campaign_id, guild_id)

    @campaign_group.command(name="stop")
    async def stop_campaign(self, ctx, campaign_id_or_name: str):
        """Stop an active campaign."""
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.active:
            await ctx.send("Campaign is not active.")
            return

        campaign.active = False
        campaign_id = campaign.campaign_id
        await self.save_campaign(campaign)

        # Cancel timer if exists
        if campaign_id in self.campaign_timers:
            self.campaign_timers[campaign_id].cancel()
            del self.campaign_timers[campaign_id]

        embed = discord.Embed(
            title="Campaign Stopped",
            description=f"Campaign '{campaign.name}' has been stopped and is no longer accepting responses.",
            color=discord.Color.red(),
        )

        await ctx.send(embed=embed)

    @campaign_group.command(name="clear")
    async def clear_camapign(self, ctx: commands.Context, campaign_id_or_name: str):
        """
        Clears all responses for a campaign

        Make sure to save your responses using [p]campaign export!
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        # Confirmation
        embed = discord.Embed(
            title="Confirm Deletion",
            description=f"Are you sure you want to delete all campaign responses for '{campaign.name}'?\n\n"
            f"**This action cannot be undone!**",
            color=discord.Color.red(),
        )

        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)

            if str(reaction.emoji) == "✅":
                async with self.config.guild(ctx.guild).responses() as responses:
                    if campaign.campaign_id in responses:
                        del responses[campaign.campaign_id]

                embed = discord.Embed(
                    title="Campaign Responses Cleared",
                    description=f"Cleared all responses for campaign '{campaign.name}'",
                    color=discord.Color.green(),
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send("Campaign response clearing cancelled.")

        except asyncio.TimeoutError:
            await ctx.send("Confirmation timed out. Campaign response clearing cancelled.")

    @campaign_group.command(name="delete")
    async def delete_campaign_c(self, ctx, campaign_id_or_name: str):
        """Delete a campaign and all its data."""
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        # Confirmation
        embed = discord.Embed(
            title="Confirm Deletion",
            description=f"Are you sure you want to delete campaign '{campaign.name}'?\n\n"
            f"This will permanently delete:\n"
            f"• The campaign configuration\n"
            f"• All user responses\n"
            f"• All associated data\n\n"
            f"**This action cannot be undone!**",
            color=discord.Color.red(),
        )

        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)

            if str(reaction.emoji) == "✅":
                await self.delete_campaign(ctx.guild.id, campaign.campaign_id)

                embed = discord.Embed(
                    title="Campaign Deleted",
                    description=f"Campaign '{campaign.name}' has been permanently deleted.",
                    color=discord.Color.green(),
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send("Campaign deletion cancelled.")

        except asyncio.TimeoutError:
            await ctx.send("Confirmation timed out. Campaign deletion cancelled.")

    @commands.command(name="submit")
    @commands.guild_only()
    async def submit_campaign(self, ctx, campaign_id_or_name: str):
        """Submit a response to a campaign.

        Usage: [p]submit <campaign_id or campaign_name>

        View campaigns using [p]clist
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.active:
            await ctx.send("This campaign is not currently active.")
            return

        if campaign.is_expired():
            await ctx.send("This campaign has expired.")
            return

        # Check if user has already submitted
        user_response = await self.get_user_response(ctx.guild.id, campaign.campaign_id, ctx.author.id)

        # Create the campaign view
        view = CampaignView(campaign, self)

        embed = discord.Embed(
            title=f"Campaign: {campaign.name}", description=campaign.description, color=discord.Color.blue()
        )

        embed.add_field(name="Questions", value=f"{len(campaign.questions)} questions available", inline=True)

        if campaign.end_time:
            embed.add_field(name="Expires", value=campaign.end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        if user_response:
            answered_count = len(user_response.get("answers", {}))
            embed.add_field(
                name="Your Progress",
                value=f"{answered_count}/{len(campaign.questions)} questions answered",
                inline=True,
            )
            embed.add_field(
                name="Note",
                value="You can modify your answers until the campaign ends.",
                inline=False,
            )

        embed.add_field(
            name="Instructions",
            value="Click the question buttons below to answer each question. Click 'Submit Response' when you're ready to finalize your answers.",
            inline=False,
        )

        await ctx.send(embed=embed, view=view)

    @campaign_group.command(name="send")
    async def send_campaign(self, ctx, campaign_id_or_name: str, channel: Optional[discord.TextChannel] = None):
        """Send a campaign message to a channel.

        Usage: [p]campaign send <campaign_id_or_name> [#channel]
        If no channel is specified, sends to the current channel.
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.active:
            await ctx.send("Campaign must be active to send.")
            return

        if not campaign.questions:
            await ctx.send("Campaign must have questions to send.")
            return

        target_channel = channel or ctx.channel

        # Create the campaign view
        view = CampaignView(campaign, self)

        embed = discord.Embed(title=f"📋 {campaign.name}", description=campaign.description, color=discord.Color.blue())

        embed.add_field(name="Questions", value=f"{len(campaign.questions)} questions", inline=True)

        if campaign.end_time:
            embed.add_field(name="Expires", value=campaign.end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        embed.add_field(
            name="How to Participate",
            value="Click the question buttons below to answer each question, then click 'Submit Response' to finalize your answers.",
            inline=False,
        )

        embed.set_footer(text=f"Campaign ID: {campaign.campaign_id}")

        try:
            message = await target_channel.send(embed=embed, view=view)

            # Save message info to campaign
            campaign.message_id = message.id
            campaign.channel_id = target_channel.id
            await self.save_campaign(campaign)

            if target_channel != ctx.channel:
                await ctx.send(f"Campaign sent to {target_channel.mention}")

        except discord.Forbidden:
            await ctx.send("I don't have permission to send messages in that channel.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to send campaign: {e}")

    @campaign_group.command(name="dm_all")
    async def dm_all_users(self, ctx, campaign_id_or_name: str):
        """DM the campaign to all users in the server.

        Usage: [p]campaign dm_all <campaign_id_or_name>

        Warning: This will send a DM to every user in the server. Use with caution.
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.active:
            await ctx.send("Campaign must be active to send.")
            return

        if not campaign.questions:
            await ctx.send("Campaign must have questions to send.")
            return

        # Confirmation
        embed = discord.Embed(
            title="Confirm Mass DM",
            description=f"Are you sure you want to DM the campaign '{campaign.name}' to **all {len(ctx.guild.members)} members** in this server?\n\n"
            f"⚠️ **Warning:** This action will send a DM to every user and cannot be undone. "
            f"Some users may not appreciate unsolicited DMs.",
            color=discord.Color.orange(),
        )

        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)

            if str(reaction.emoji) == "✅":
                await self._send_campaign_dms(ctx, campaign, ctx.guild.members)
            else:
                await ctx.send("Mass DM cancelled.")

        except asyncio.TimeoutError:
            await ctx.send("Confirmation timed out. Mass DM cancelled.")

    @campaign_group.command(name="dm_role")
    async def dm_role_users(self, ctx, campaign_id_or_name: str, role: discord.Role):
        """DM the campaign to all users with a specific role.

        Usage: [p]campaign dm_role <campaign_id_or_name> @role
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        if not campaign.active:
            await ctx.send("Campaign must be active to send.")
            return

        if not campaign.questions:
            await ctx.send("Campaign must have questions to send.")
            return

        role_members = [member for member in role.members if not member.bot]

        if not role_members:
            await ctx.send(f"No non-bot users found with the role {role.mention}.")
            return

        # Confirmation
        embed = discord.Embed(
            title="Confirm Role DM",
            description=f"Are you sure you want to DM the campaign '{campaign.name}' to **{len(role_members)} members** with the role {role.mention}?",
            color=discord.Color.orange(),
        )

        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)

            if str(reaction.emoji) == "✅":
                await self._send_campaign_dms(ctx, campaign, role_members)
            else:
                await ctx.send("Role DM cancelled.")

        except asyncio.TimeoutError:
            await ctx.send("Confirmation timed out. Role DM cancelled.")

    async def _send_campaign_dms(self, ctx, campaign, members):
        """Send campaign DMs to a list of members."""
        from .views import CampaignView

        # Create the campaign view
        view = CampaignView(campaign, self)

        embed = discord.Embed(title=f"📋 {campaign.name}", description=campaign.description, color=discord.Color.blue())

        embed.add_field(name="Questions", value=f"{len(campaign.questions)} questions", inline=True)

        if campaign.end_time:
            embed.add_field(name="Expires", value=campaign.end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        embed.add_field(name="Server", value=ctx.guild.name, inline=True)

        embed.add_field(
            name="How to Participate",
            value="Click the question buttons below to answer each question, then click 'Submit Response' to finalize your answers.",
            inline=False,
        )

        embed.set_footer(text=f"Campaign ID: {campaign.campaign_id}")

        # Send DMs with rate limiting
        successful = 0
        failed = 0

        # Create progress message
        progress_embed = discord.Embed(
            title="Sending DMs...", description=f"Progress: 0/{len(members)}", color=discord.Color.blue()
        )
        progress_msg = await ctx.send(embed=progress_embed)

        for i, member in enumerate(members):
            if member.bot:
                continue

            try:
                await member.send(embed=embed, view=view)
                successful += 1
                await asyncio.sleep(1)  # Rate limiting: 1 second between DMs

            except discord.Forbidden:
                # User has DMs disabled
                failed += 1
            except discord.HTTPException:
                # Other error (user not found, etc.)
                failed += 1

            # Update progress every 10 users
            if (i + 1) % 10 == 0 or i == len(members) - 1:
                progress_embed.description = (
                    f"Progress: {i + 1}/{len(members)}\nSuccessful: {successful}\nFailed: {failed}"
                )
                try:
                    await progress_msg.edit(embed=progress_embed)
                except discord.NotFound:
                    pass  # Message was deleted

        # Final result
        result_embed = discord.Embed(
            title="DM Campaign Complete",
            description=f"Campaign '{campaign.name}' has been sent via DM.",
            color=discord.Color.green(),
        )
        result_embed.add_field(name="Successful", value=str(successful), inline=True)
        result_embed.add_field(name="Failed", value=str(failed), inline=True)
        result_embed.add_field(name="Total Attempted", value=str(len(members)), inline=True)

        if failed > 0:
            result_embed.add_field(
                name="Note",
                value="Failed DMs are usually due to users having DMs disabled or blocking the bot.",
                inline=False,
            )

        await ctx.send(embed=result_embed)

    @campaign_group.command(name="export")
    async def export_campaign(self, ctx, campaign_id_or_name: str):
        """Export campaign responses to a CSV file.

        Usage: [p]campaign export <campaign_id_or_name>
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        # Get all responses for this campaign
        responses_data = await self.config.guild(ctx.guild).responses()
        campaign_responses = responses_data.get(campaign.campaign_id, {})

        if not campaign_responses:
            await ctx.send("No responses found for this campaign.")
            return

        # Generate CSV
        csv_content = await self._generate_csv(campaign, campaign_responses)

        csv_buffer = io.StringIO(csv_content)
        csv_file = discord.File(
            io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
            filename=f"campaign_{campaign.campaign_id}_{campaign.name.replace(' ', '_')}_responses.csv",
        )

        embed = discord.Embed(
            title="Campaign Export",
            description=f"Exported responses for campaign '{campaign.name}'",
            color=discord.Color.green(),
        )
        embed.add_field(name="Total Responses", value=str(len(campaign_responses)), inline=True)
        embed.add_field(name="Questions", value=str(len(campaign.questions)), inline=True)

        await ctx.send(embed=embed, file=csv_file)

    async def _generate_csv(self, campaign, responses_data):
        """Generate CSV content from campaign and responses."""

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        # 1) Build header row with a stable Q1, Q2, … ordering
        header = ["User ID", "Username", "Submission Time"]
        for idx, question in enumerate(campaign.questions, start=1):
            header.append(f"Q{idx}: {question['text']}")
        writer.writerow(header)

        # 2) Build each response row in the same question order
        for user_id, response in responses_data.items():
            username = self._get_username(int(user_id))
            submission_time = response.get("submission_time", "Unknown")

            row = [user_id, username, submission_time]

            answers = response.get("answers", {})
            for question in campaign.questions:
                raw = answers.get(question["question_id"], "")
                if not raw:
                    clean = "No response"
                else:
                    clean = str(raw).replace("\n", " ").replace("\r", " ")
                row.append(clean)

            writer.writerow(row)

        return output.getvalue()

    def _get_username(self, user_id: int) -> str:
        """Get username for a user ID, with fallback."""
        user = self.bot.get_user(user_id)
        if user:
            return f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
        return f"Unknown User ({user_id})"

    @campaign_group.command(name="stats")
    async def campaign_stats(self, ctx, campaign_id_or_name: str):
        """Show statistics for a campaign.

        Usage: [p]campaign stats <campaign_id_or_name>
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        campaign_id = campaign.campaign_id
        # Get all responses for this campaign
        responses_data = await self.config.guild(ctx.guild).responses()
        campaign_responses = responses_data.get(campaign_id, {})

        embed = discord.Embed(title=f"Campaign Statistics: {campaign.name}", color=discord.Color.blue())

        # Basic stats
        embed.add_field(name="Total Responses", value=str(len(campaign_responses)), inline=True)
        embed.add_field(name="Questions", value=str(len(campaign.questions)), inline=True)
        embed.add_field(name="Status", value="🟢 Active" if campaign.active else "🔴 Inactive", inline=True)

        if campaign.start_time:
            embed.add_field(name="Started", value=campaign.start_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        if campaign.end_time:
            embed.add_field(name="Expires", value=campaign.end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)

        # Response completion stats
        if campaign_responses:
            completion_stats = self._calculate_completion_stats(campaign, campaign_responses)

            embed.add_field(
                name="Completion Rate", value=f"{completion_stats['avg_completion']:.1f}% average", inline=True
            )

            embed.add_field(
                name="Fully Completed",
                value=f"{completion_stats['fully_completed']}/{len(campaign_responses)} responses",
                inline=True,
            )

            # Question-specific stats
            if len(campaign.questions) > 0:
                question_stats = []
                for i, question in enumerate(campaign.questions[:5]):  # Show first 5 questions
                    answered_count = sum(
                        1
                        for response in campaign_responses.values()
                        if question["question_id"] in response.get("answers", {})
                    )
                    percentage = (answered_count / len(campaign_responses)) * 100
                    question_stats.append(f"Q{i+1}: {answered_count}/{len(campaign_responses)} ({percentage:.1f}%)")

                if len(campaign.questions) > 5:
                    question_stats.append(f"... and {len(campaign.questions) - 5} more questions")

                embed.add_field(name="Question Response Rates", value="\n".join(question_stats), inline=False)

        await ctx.send(embed=embed)

    def _calculate_completion_stats(self, campaign, responses_data):
        """Calculate completion statistics for a campaign."""
        total_questions = len(campaign.questions)
        if total_questions == 0:
            return {"avg_completion": 0, "fully_completed": 0}

        completion_rates = []
        fully_completed = 0

        for response in responses_data.values():
            answers = response.get("answers", {})
            answered_count = len(answers)
            completion_rate = (answered_count / total_questions) * 100
            completion_rates.append(completion_rate)

            if answered_count == total_questions:
                fully_completed += 1

        avg_completion = sum(completion_rates) / len(completion_rates) if completion_rates else 0

        return {"avg_completion": avg_completion, "fully_completed": fully_completed}

    @campaign_group.command(name="responses")
    async def view_responses(self, ctx, campaign_id_or_name: str, user: Optional[discord.Member] = None):
        """View responses for a campaign or a specific user.

        Usage: [p]campaign responses <campaign_id> [@user]
        If no user is specified, shows a summary of all responses.
        """
        campaign = await self.get_campaign(ctx.guild.id, campaign_id_or_name)
        if not campaign:
            await ctx.send("Campaign not found.")
            return

        # Get all responses for this campaign
        responses_data = await self.config.guild(ctx.guild).responses()
        campaign_responses = responses_data.get(campaign.campaign_id, {})

        if not campaign_responses:
            await ctx.send("No responses found for this campaign.")
            return

        if user:
            # Show specific user's response
            user_response = campaign_responses.get(str(user.id))
            if not user_response:
                await ctx.send(f"{user.mention} has not responded to this campaign.")
                return

            embed = discord.Embed(
                title=f"Response from {user.display_name}",
                description=f"Campaign: {campaign.name}",
                color=discord.Color.blue(),
            )

            submission_time = user_response.get("submission_time", "Unknown")
            submission_time = datetime.fromisoformat(submission_time)
            embed.add_field(
                name="Submitted",
                value=f"<t:{int(submission_time.astimezone(tzlocal()).timestamp())}>",
                inline=True,
            )

            answers = user_response.get("answers", {})
            embed.add_field(name="Questions Answered", value=f"{len(answers)}/{len(campaign.questions)}", inline=True)

            # Show answers
            for i, question in enumerate(campaign.questions):
                answer = answers.get(question["question_id"], "No response")
                # Truncate long answers
                if len(str(answer)) > 100:
                    answer = str(answer)[:97] + "..."

                embed.add_field(
                    name=f"Q{i+1}: {question['text'][:50]}{'...' if len(question['text']) > 50 else ''}",
                    value=str(answer),
                    inline=False,
                )

            await ctx.send(embed=embed)

        else:
            # Show summary of all responses
            embed = discord.Embed(
                title=f"Response Summary: {campaign.name}",
                description=f"Total responses: {len(campaign_responses)}",
                color=discord.Color.blue(),
            )

            # Show list of respondents
            respondents = []
            for user_id, response in list(campaign_responses.items())[:10]:  # Show first 10
                submission_time = response.get("submission_time", "Unknown")
                submission_time = datetime.fromisoformat(submission_time)

                username = self._get_username(int(user_id))
                answered_count = len(response.get("answers", {}))
                respondents.append(
                    f"**{username}** - {answered_count}/{len(campaign.questions)} questions (<t:{int(submission_time.astimezone(tzlocal()).timestamp())}>)"
                )

            if len(campaign_responses) > 10:
                respondents.append(f"... and {len(campaign_responses) - 10} more responses")

            if respondents:
                embed.add_field(name="Recent Responses", value="\n".join(respondents), inline=False)

            embed.add_field(
                name="Export Data",
                value=f"Use `{ctx.prefix}campaign export {campaign.campaign_id}` to download all responses as CSV",
                inline=False,
            )

            await ctx.send(embed=embed)
