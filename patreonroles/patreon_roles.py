import asyncio
import discord
import patreon

from .patreon_api import *
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import *
from dateutil.relativedelta import relativedelta
from dateutil import parser
from datetime import datetime, timedelta
from bisect import bisect_left


class Patreon(commands.Cog):
    """
    Patreon Role Management System
    """

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=15616849861323186, force_registration=True)

        # roles: role_id --> {time: total time of patreon subscription to get role, tiers: list of tiers to check for subscription}
        # mode:
        #   - current: Only consider continous pledge time (i.e no cancellations)
        #   - total: Consider total pledge time regardless of times when not pledged
        default_guild = {
            "access_token": None,
            "campaign_id": None,
            "tiers": {},
            "roles": {},
            "mode": "current",
        }
        # total_time_pledged: tier_id --> time_in_seconds
        # current_time_pledged represents the number of seconds pledged
        self.default_member = {
            "total_time_pledged": {},
            "total_pledge_amount": 0,
            "current_time_pledged": {},
            "current_pledge_amount": 0,
            "tier": None,
            "next_charge_date": None,
            "last_update_date": None,
            "patreon_id": None,
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**self.default_member)

        self.clients = {}

        self.task = asyncio.create_task(self.initialize())

    async def cog_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def initialize(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(1)

        # create clients for each guild
        for guild in self.bot.guilds:
            guild_data = await self.config.guild(guild).all()

            if guild_data["access_token"] is not None:
                self.clients[guild] = patreon.API(guild_data["access_token"])
                campaign_id = await self.config.guild(guild).campaign_id()
                if campaign_id is not None:
                    # update tiers
                    # TODO: add this into a command
                    tiers = get_tier_data(self.clients[guild], campaign_id)
                    fixed_tiers = {}
                    for t in tiers:
                        fixed_tiers[t.id()] = t.attribute("amount_cents")
                    await self.config.guild(guild).tiers.set(fixed_tiers)
                # need to check if campaign id still matches
                if get_campaign_id(self.clients[guild], guild) != guild_data["campaign_id"]:
                    # TODO: need to figure out a good error handler for this, message guild owner about it maybe?
                    pass

    async def update_member(
        self, member: discord.Member, campaign_id: int = None, patreon_id: str = None, tiers: dict = None
    ):
        guild = member.guild
        client = self.clients[guild]
        new_member = False

        if campaign_id is None:
            campaign_id = await self.config.guild(guild).campaign_id()
            if campaign_id is None:
                return  # TODO error

        if patreon_id is None:
            patreon_id = await self.config.member(member).patreon_id()
            if patreon_id is None:
                patreon_id = get_patreon_member_id(client, campaign_id, member)
                new_member = True
            if patreon_id is None:
                return  # TODO error

        if tiers is None:
            tiers = await self.config.guild(guild).tiers()

        m_data = await self.config.member(member).all()

        patreon_data = get_member_info(client, campaign_id, patreon_id)

        # update totals
        m_data["total_pledge_amount"] = patreon_data.attribute("campaign_lifetime_support_cents")
        m_data["patreon_id"] = patreon_data.id()
        next_charge_date = parser.parse(patreon_data.attribute("next_charge_date"))
        m_data["next_charge_date"] = next_charge_date.timestamp()
        # update tier
        user_tiers = [ut.id() for ut in patreon_data.relationship("currently_entitled_tiers")]
        # set user's tier as highest entitled tier
        if user_tiers != []:
            m_data["tier"] = user_tiers[0]
            for t in user_tiers:
                if tiers[str(t)] > tiers[str(m_data["tier"])]:
                    m_data["tier"] = str(t)

        pledges = get_pledge_history(client, campaign_id, patreon_id)
        pledges_clean = []
        if not new_member:
            last_update = m_data["last_update_date"]
            # only need to process latest pledges
            for i in range(len(pledges), -1, -1):
                pledge = pledges[i]
                date = parser.parse(pledge.attribute("date")).replace(tzinfo=None)
                if date < last_update:
                    break
                pledges_clean.append(pledge)

            pledges = pledges_clean

        # process pledges
        start = None
        curr_tier = None
        all_time = {t: 0 for t in tiers.keys()}
        current_time = {t: 0 for t in tiers.keys()}
        for pledge in pledges:
            payment = pledge.attribute("pledge_payment_status")
            date = parser.parse(pledge.attribute("date")).replace(tzinfo=None)
            pledge_type = pledge.attribute("type")
            tier = str(pledge.attribute("tier_id"))

            if payment != "valid":
                pass
            elif pledge_type == "pledge_delete":
                ## this will miss if someone deletes their subscription then immeditatly resubscribes, which will reset stats. could fix this, althought
                ## it'll introduce more complicated logic
                # add remaining time
                total_time = (date - start).total_seconds()
                current_time[curr_tier] += total_time
                for t_id, t_time in current_time.items():
                    all_time[t_id] += t_time

                # clear current time
                current_time = {t: 0 for t in tiers.keys()}
                start = None
                curr_tier = None
            elif pledge_type == "pledge_start":
                # start of a new pledge from having no pledge before
                start = date
                curr_tier = tier
            elif pledge_type == "pledge_upgrade" or pledge_type == "pledge_downgrade" or pledge_type == "subscription":
                total_time = (date - start).total_seconds()
                current_time[curr_tier] += total_time

                start = date
                curr_tier = tier
            else:
                # unknown type, shouldn't occur
                print("Unknown patreon pledge type!")
                pass

        # need to do a final update based on the last pledge type:
        pledge = pledges[-1]
        pledge_type = pledge.attribute("type")
        payment = pledge.attribute("pledge_payment_status")
        if pledge_type != "pledge_delete" and payment == "valid":
            now = datetime.utcnow().replace(tzinfo=None)
            total_time = (now - start).total_seconds()
            current_time[curr_tier] += total_time
            for t_id, t_time in current_time.items():
                all_time[t_id] += t_time

            m_data["last_update_date"] = now.timestamp()

        m_data["current_pledge_amount"] = sum([tiers[t_id] * t_time for t_id, t_time in current_time.items()])

    async def update_all_members(self, guild: discord.Guild):
        client = self.clients[guild]
        campaign_id = await self.config.guild(guild).campaign_id()
        tiers = await self.config.guild(guild).tiers()

        if campaign_id is None:
            # TODO error
            return

        ids = get_patreon_member_id_all(client, campaign_id)
        for member in guild.members:
            patreon_id = ids.get(member.id, None)
            print(member, patreon_id)
            if patreon_id is None:
                continue

            m_data = self.default_member.copy()

            patreon_data = get_member_info(client, campaign_id, patreon_id)

            # update totals
            m_data["total_pledge_amount"] = patreon_data.attribute("campaign_lifetime_support_cents")
            m_data["patreon_id"] = patreon_data.id()
            next_charge_date = parser.parse(patreon_data.attribute("next_charge_date"))
            m_data["next_charge_date"] = next_charge_date.timestamp()
            # update tier
            user_tiers = [ut.id() for ut in patreon_data.relationship("currently_entitled_tiers")]
            # set user's tier as highest entitled tier
            if user_tiers != []:
                m_data["tier"] = user_tiers[0]
                for t in user_tiers:
                    if tiers[str(t)] > tiers[str(m_data["tier"])]:
                        m_data["tier"] = str(t)

            pledges = get_pledge_history(client, campaign_id, patreon_id)

            # process pledges
            start = None
            curr_tier = None
            all_time = {t: 0 for t in tiers.keys()}
            current_time = {t: 0 for t in tiers.keys()}
            for pledge in pledges:
                # theres 2 payment statuses, one is only populated if type == subscription, other one is valid for other types
                pledge_payment = pledge.attribute("pledge_payment_status")
                payment = pledge.attribute("payment_status")
                date = parser.parse(pledge.attribute("date")).replace(tzinfo=None)
                pledge_type = pledge.attribute("type")
                tier = str(pledge.attribute("tier_id"))

                if (pledge_payment != "valid" and pledge_type != "subscription") or (
                    payment != "Paid" and pledge_type == "subscription"
                ):
                    pass
                elif pledge_type == "pledge_delete":
                    ## this will miss if someone deletes their subscription then immeditatly resubscribes, which will reset stats. could fix this, althought
                    ## it'll introduce more complicated logic
                    # add remaining time
                    total_time = (date - start).total_seconds()
                    current_time[curr_tier] += total_time
                    for t_id, t_time in current_time.items():
                        all_time[t_id] += t_time

                    # clear current time
                    current_time = {t: 0 for t in tiers.keys()}
                    start = None
                    curr_tier = None
                elif pledge_type == "pledge_start":
                    # start of a new pledge from having no pledge before
                    start = date
                    curr_tier = tier
                elif (
                    pledge_type == "pledge_upgrade"
                    or pledge_type == "pledge_downgrade"
                    or pledge_type == "subscription"
                ):
                    total_time = (date - start).total_seconds()
                    current_time[curr_tier] += total_time

                    start = date
                    curr_tier = tier
                else:
                    # unknown type, shouldn't occur
                    # TODO proper error
                    print("Unknown patreon pledge type!")
                    pass
                print("=" * 25)
                print(f"start: {start}, tier: {curr_tier}, current_time: {current_time}, total_time: {all_time}")
                print(pledge.json_data)
                print("=" * 25)

            # need to do a final update for total times based on the last pledge type:
            pledge = pledges[-1]
            pledge_type = pledge.attribute("type")
            pledge_payment = pledge.attribute("pledge_payment_status")
            payment = pledge.attribute("payment_status")
            now = datetime.utcnow().replace(tzinfo=None)
            if pledge_type != "pledge_delete" and (
                (pledge_payment == "valid" and pledge_type != "subscription")
                or (payment == "Paid" and pledge_type == "subscription")
            ):
                total_time = (now - start).total_seconds()
                current_time[curr_tier] += total_time
                for t_id, t_time in current_time.items():
                    all_time[t_id] += t_time

            m_data["last_update_date"] = now.timestamp()

            m_data["current_pledge_amount"] = sum([tiers[t_id] * t_time for t_id, t_time in current_time.items()])
            print(m_data)
            print(current_time)
            print(all_time)
            # update member data
            await self.config.member(member).total_time_pledged.set(all_time)
            await self.config.member(member).total_pledge_amount.set(m_data["total_pledge_amount"])
            await self.config.member(member).current_time_pledged.set(current_time)
            await self.config.member(member).current_pledge_amount.set(m_data["current_pledge_amount"])
            await self.config.member(member).tier.set(m_data["tier"])
            await self.config.member(member).next_charge_date.set(m_data["next_charge_date"])
            await self.config.member(member).last_update_date.set(m_data["last_update_date"])
            await self.config.member(member).patreon_id.set(m_data["patreon_id"])

    @checks.admin()
    @commands.guild_only()
    @commands.group(name="patreon")
    async def patreon(self, ctx):
        """
        Manage patreon roles for discord.
        """
        pass

    @patreon.command(name="update")
    async def patreon_update(self, ctx):
        """
        Updates the campaign associated with this server.

        Use this if you change the campaign linked to this Discord server or sync all data from Patreon for your members.
        """
        # TODO
        pass

    @patreon.command(name="api")  # type: ignore
    async def patreon_api(self, ctx, access_token: str):
        """
        Set access token for patreon API client
        """
        # delete message to avoid access token sitting in chat
        await ctx.message.delete()
        try:
            client = patreon.API(access_token)
            # verify API connection and get campaign for this server
            campaign_id = get_campaign_id(client, ctx.guild)

            if campaign_id is None:
                return await ctx.send(
                    error(
                        "API Connected, but unable to find the campaign assoicated with this server. Please make sure you have linked this Discord server to your Patreon campaign! You can do this from your campaign page on Patreon's website."
                    )
                )
        except:
            return await ctx.send(
                error(
                    "Unable to log into API using that token! Make sure you are using the `Creator's Access Token` and not `Client Secret`."
                ),
                delete_after=60,
            )

        # TODO run a sync on all members with some helper function

        self.clients[ctx.guild] = client
        await self.config.guild(ctx.guild).access_token.set(access_token)
        await self.config.guild(ctx.guild).campaign_id.set(campaign_id)
        await ctx.send(info("Access token set and connected to API!"), delete_after=30)

    @patreon.command(name="test")  # type: ignore
    async def test(self, ctx):
        await self.initialize()
        await self.update_all_members(ctx.guild)
