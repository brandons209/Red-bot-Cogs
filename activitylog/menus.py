import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import error
from discord.ui import View, Select, ChannelSelect, UserSelect, Button, TextInput, Modal
from typing import Literal, Union, Tuple, Optional, List
from datetime import datetime
from dateutil.tz import tzlocal


class LogView(View):

    def __init__(self, ctx: commands.Context, cog, *, timeout: Optional[int] = 180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.log_type: str = None
        self.channel: Union[discord.app_commands.AppCommandChannel, discord.app_commands.AppCommandThread] = None
        self.user: Union[discord.Member, discord.User] = None
        self.interval_data: Tuple[datetime, Union[datetime, None]] = (None, None)
        self.message: Optional[discord.Message] = None

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    def update_location_select(self):
        if self.log_type is None:
            return
        if self.log_type != "audit":
            if self.log_type == "voice":
                self.location_select.channel_types = [discord.ChannelType.voice]
            else:
                self.location_select.channel_types = [
                    discord.ChannelType.text,
                    discord.ChannelType.public_thread,
                    discord.ChannelType.private_thread,
                    discord.ChannelType.news_thread,
                ]
            self.location_select.disabled = False
            self.user_select.disabled = False
        else:
            self.location_select.disabled = True
            self.user_select.disabled = False

        self.log_type_select.placeholder = self.log_type.capitalize()

    def validation(self):
        if self.log_type == "channel":
            return (
                (
                    isinstance(self.channel, discord.app_commands.AppCommandChannel)
                    ^ isinstance(self.user, discord.Member)
                )
                and self.log_type in ["channel", "voice", "audit"]
                and isinstance(self.interval_data[0], datetime)
            )
        elif self.log_type == "voice":
            return (
                isinstance(self.channel, discord.app_commands.AppCommandChannel)
                and self.log_type in ["channel", "voice", "audit"]
                and isinstance(self.interval_data[0], datetime)
            )
        else:
            return self.log_type in ["channel", "voice", "audit"] and isinstance(self.interval_data[0], datetime)

    @discord.ui.select(
        placeholder="Select log type...",
        options=[
            discord.SelectOption(label="Channel", value="channel"),
            discord.SelectOption(label="Voice", value="voice"),
            discord.SelectOption(label="Audit", value="audit"),
        ],
    )
    async def log_type_select(self, interaction: discord.Interaction, select: Select):
        self.log_type = select.values[0] if select.values else None
        await interaction.response.defer()
        self.update_location_select()
        await interaction.edit_original_response(view=self)

    @discord.ui.select(
        placeholder="Select a channel",
        cls=ChannelSelect,
        custom_id="location_select",
        min_values=0,
        disabled=True,
    )
    async def location_select(self, interaction: discord.Interaction, select: ChannelSelect):
        self.channel = select.values[0] if select.values else None
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select a user",
        cls=UserSelect,
        custom_id="user_select",
        min_values=0,
        disabled=True,
    )
    async def user_select(self, interaction: discord.Interaction, select: UserSelect):
        self.user = select.values[0] if select.values else None
        await interaction.response.defer()

    @discord.ui.button(label="Time Delta", style=discord.ButtonStyle.secondary)
    async def delta_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DeltaModal(self))

    @discord.ui.button(label="Date Range", style=discord.ButtonStyle.primary)
    async def range_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DateRangeModal(self))

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.success)
    async def submit_button(self, interaction: discord.Interaction, button: Button):
        # Gather all state
        lt = self.log_type
        ch = self.channel
        usr = self.user
        start_time, end_time = self.interval_data

        if not self.validation():
            if not lt:
                msg = error("You must select a log type!")
            elif lt == "channel":
                msg = error("You must select either a channel or user and submit a time delta or a date range!")
            elif lt == "voice":
                msg = error("You must select a channel and either a time delta or date range!")
            else:
                msg = error("You must enter a time delta or date range!")
            await interaction.response.send_message(msg, ephemeral=True, delete_after=10)
            return

        await interaction.response.defer()
        # Call your existing functions
        if lt == "channel":
            if ch:
                obj = await ch.fetch()
            else:
                obj = usr
            await self.cog.chat_log_sender(self.ctx, obj, start_time, end_time=end_time)
        elif lt == "voice":
            channel = await ch.fetch()
            await self.cog.voice_log_sender(self.ctx, channel, start_time, end_time=end_time, member=usr)
        else:
            await self.cog.audit_log_sender(
                self.ctx, self.ctx.guild, start_time=start_time, end_time=end_time, member=usr
            )

        await interaction.delete_original_response()
        self.stop()


class GraphView(View):
    def __init__(self, ctx: commands.Context, cog, *, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.ctx: commands.Context = ctx
        self.cog = cog
        self.message: Optional[discord.Message] = None

        self.action: Literal[
            "activity",
            "correlation",
            "active_hours_channel",
            "active_hours_guild",
            "leaves",
            "retention",
            "text",
            "voice_channel",
            "voice_user",
        ] = None
        self.interval_data: str = None
        self.split: str = None
        self.channel: Union[discord.app_commands.AppCommandChannel, discord.app_commands.AppCommandThread] = None
        self.user: discord.Member = None

        ## remove until user selects a type
        self.current_items: List[discord.ui.Item] = []
        remove_items = [
            self.delta_button,
            self.range_button,
            self.submit_button,
            self.split_select,
            self.channel_select,
            self.user_select,
        ]
        for item in remove_items:
            self = self.remove_item(item)

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    def update_view(self):
        while len(self.current_items) > 0:
            item = self.current_items.pop()
            self.remove_item(item)

        if self.action == "activity":
            rows = [1, 2, 2, 2]
            self.current_items = [self.split_select, self.delta_button, self.range_button, self.submit_button]
        elif self.action == "correlation":
            rows = [1]
            self.current_items = [self.submit_button]
        elif self.action == "active_hours_channel":
            rows = [1, 2, 2, 2]
            self.channel_select.channel_types = [
                discord.ChannelType.text,
                discord.ChannelType.voice,
                discord.ChannelType.public_thread,
                discord.ChannelType.private_thread,
                discord.ChannelType.news_thread,
            ]
            self.current_items = [self.channel_select, self.delta_button, self.range_button, self.submit_button]
        elif self.action == "active_hours_guild":
            rows = [1, 1, 1]
            self.current_items = [self.delta_button, self.range_button, self.submit_button]
        elif self.action == "leaves":
            rows = [1, 2, 2, 2]
            self.current_items = [self.split_select, self.delta_button, self.range_button, self.submit_button]
        elif self.action == "retention":
            rows = [1]
            self.current_items = [self.submit_button]
        elif self.action == "text":
            rows = [1, 2, 3, 3, 3]
            self.current_items = [
                self.split_select,
                self.user_select,
                self.delta_button,
                self.range_button,
                self.submit_button,
            ]
        elif self.action == "voice_channel":
            rows = [1, 2, 2, 2]
            self.channel_select.channel_types = [discord.ChannelType.voice]
            self.current_items = [self.channel_select, self.delta_button, self.range_button, self.submit_button]
        elif self.action == "voice_user":
            rows = [1, 2, 2, 2]
            self.current_items = [self.user_select, self.delta_button, self.range_button, self.submit_button]
        else:
            rows = []

        for row, item in zip(rows, self.current_items):
            item.row = row
            self.add_item(item)

    @discord.ui.select(
        row=0,
        placeholder="What do you want to graph?",
        options=[
            discord.SelectOption(label="Text Channel Activity", value="activity"),
            discord.SelectOption(label="Voice Channel Activity", value="voice_channel"),
            discord.SelectOption(label="Channel Active Hours", value="active_hours_channel"),
            discord.SelectOption(label="Server Active Hours", value="active_hours_guild"),
            discord.SelectOption(label="Joins and Leaves", value="leaves"),
            discord.SelectOption(label="Member Correlation", value="correlation"),
            discord.SelectOption(label="Member Retention", value="retention"),
            discord.SelectOption(label="Member Text Activity", value="text"),
            discord.SelectOption(label="Member Voice Activity", value="voice_user"),
        ],
    )
    async def graph_type_select(self, interaction: discord.Interaction, select: Select):
        self.action = select.values[0] if select.values else None
        await interaction.response.defer()
        self.update_view()
        if self.action:
            options = [o.value for o in self.graph_type_select.options]
            key = options.index(self.action)
            self.graph_type_select.placeholder = self.graph_type_select.options[key].label
        await interaction.edit_original_response(view=self)

    @discord.ui.select(
        row=1,
        placeholder="Data Split",
        options=[
            discord.SelectOption(label="Hourly", value="h"),
            discord.SelectOption(label="Daily", value="d"),
            discord.SelectOption(label="Weekly", value="w"),
            discord.SelectOption(label="Monthly", value="m"),
            discord.SelectOption(label="Yearly", value="y"),
        ],
    )
    async def split_select(self, interaction: discord.Interaction, select: Select):
        self.split = select.values[0] if select.values else None
        await interaction.response.defer()

    @discord.ui.select(
        row=2,
        placeholder="Select a channel",
        cls=ChannelSelect,
    )
    async def channel_select(self, interaction: discord.Interaction, select: ChannelSelect):
        self.channel = select.values[0] if select.values else None
        await interaction.response.defer()

    @discord.ui.select(
        row=3,
        placeholder="Select a user",
        cls=UserSelect,
        custom_id="user_select",
    )
    async def user_select(self, interaction: discord.Interaction, select: UserSelect):
        self.user = select.values[0] if select.values else None
        await interaction.response.defer()

    @discord.ui.button(row=4, label="Time Delta", style=discord.ButtonStyle.secondary, custom_id="time_delta")
    async def delta_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DeltaModal(self))

    @discord.ui.button(row=4, label="Date Range", style=discord.ButtonStyle.primary, custom_id="date_range")
    async def range_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DateRangeModal(self))

    @discord.ui.button(row=4, label="Submit", style=discord.ButtonStyle.success, custom_id="submit")
    async def submit_button(self, interaction: discord.Interaction, button: Button):
        for item in self.current_items:
            if type(item) in [Select, ChannelSelect, UserSelect]:
                if not item.values:
                    await interaction.response.send_message(
                        error("Make sure to fill every option box."), ephemeral=True, delete_after=10
                    )
                    return

        cmd, args, kwargs = None, None, None
        if self.action == "activity":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_activity
            args = (self.split,)
            kwargs = {"till": self.interval_data}
        elif self.action == "correlation":
            cmd = self.cog.graphstats_correlation
            args = tuple()
            kwargs = {}
        elif self.action == "active_hours_channel":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_hours_channel
            args = (self.channel,)
            kwargs = {"till": self.interval_data}
        elif self.action == "active_hours_guild":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_hours_guild
            args = tuple()
            kwargs = {"till": self.interval_data}
        elif self.action == "leaves":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_leaves
            args = (self.split,)
            kwargs = {"till": self.interval_data}
        elif self.action == "retention":
            cmd = self.cog.graphstats_retention
            args = tuple()
        elif self.action == "text":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.user_stats_graph
            args = (
                self.user,
                self.split,
            )
            kwargs = {"till": self.interval_data}
        elif self.action == "voice_channel":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_users_voice
            args = (self.channel,)
            kwargs = {"till": self.interval_data}
        elif self.action == "voice_user":
            if self.interval_data is None:
                await interaction.response.send_message(
                    error("You must enter a valid time delta or date range!"), ephemeral=True, delete_after=10
                )
                return
            cmd = self.cog.graphstats_voice_user
            args = (self.user,)
            kwargs = {"till": self.interval_data}

        await interaction.response.defer()
        await self.ctx.invoke(cmd, *args, **kwargs)

        await interaction.delete_original_response()
        self.stop()


class DeltaModal(Modal, title="Enter Time Delta"):
    delta = TextInput(
        label="Delta (e.g. 5 minutes, 4 weeks, 5h)", style=discord.TextStyle.short, custom_id="delta_input"
    )

    def __init__(self, view: Union[LogView, GraphView]):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        start_time, end_time = self.view.cog.interval_parser(self.delta.value)
        if not start_time:
            await interaction.response.send_message(
                error(f"Invalid delta! Try again."), ephemeral=True, delete_after=10
            )
            # await interaction.followup.send_modal(DeltaModal(self.view))
        else:
            await interaction.response.defer()
            self.view.interval_data = (start_time, end_time) if isinstance(self.view, LogView) else self.delta.value
            await interaction.edit_original_response(
                content=f"Date Range: <t:{int(start_time.astimezone(tzlocal()).timestamp())}> -- <t:{int(end_time.astimezone(tzlocal()).timestamp())}>"
            )


class DateRangeModal(Modal, title="Enter Date Range"):
    start = TextInput(label="Start Date", style=discord.TextStyle.short)
    end = TextInput(label="End Date", style=discord.TextStyle.short)

    def __init__(self, view: Union[LogView, GraphView]):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        start_time, end_time = self.view.cog.interval_parser(f"{self.start.value};{self.end.value}")
        if not start_time:
            await interaction.response.send_message(
                error(f"Invalid dates, try again!"), ephemeral=True, delete_after=10
            )
            # await interaction.response.send_modal(DeltaModal(self.view))
        else:
            await interaction.response.defer()
            self.view.interval_data = (
                (start_time, end_time) if isinstance(self.view, LogView) else f"{self.start.value};{self.end.value}"
            )
            await interaction.edit_original_response(
                content=f"Date Range: <t:{int(start_time.astimezone(tzlocal()).timestamp())}> -- <t:{int(end_time.astimezone(tzlocal()).timestamp())}>"
            )
