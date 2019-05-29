import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
import asyncio
import os
import random

class Referral:
    """
    Creates a referral system with raffle like selection for prizes for discord users.
    """
    def __init__(self, bot):
        self.settings_path = 'data/referral/settings.json'
        self.bot = bot
        self.settings = dataIO.load_json(self.settings_path)

    def add_non_refer(self, member):
        if member.server.id not in self.settings.keys():
            self.settings[member.server.id] = {}
            self.settings[member.server.id]["NON-REFERRALS"] = []
        elif "NON-REFERRALS" not in self.settings[member.server.id].keys():
            self.settings[member.server.id]["NON-REFERRALS"] = []

        self.settings[member.server.id]["NON-REFERRALS"].append(member.id)
        dataIO.save_json(self.settings_path, self.settings)

    def clear_refers(self, server):
        """
        Clears entire referral and non referral list, then adds all current users in server to non referral list.
        """
        self.settings[server.id]["NON-REFERRALS"] = []
        self.settings[server.id]["REFERRALS"] = {}
        for member in server.members:
            self.settings[server.id]["NON-REFERRALS"].append(member.id)

        dataIO.save_json(self.settings_path, self.settings)

    async def member_join_listener(self, member):
        """
        Checks user against main invite link to determine if they went through the main invite link or an alternate one
        """
        server = member.server
        default_inv = self.settings.get(server.id, {}).get("DEFAULT_INVITE", {})
        invite = None

        if not default_inv:
            # TODO logging
            return
        else:
            try:
                invite = await self.bot.get_invite(default_inv["ID"])
            except:
                invite = None

        if not invite:
            # TODO: put logging here
            return

        if invite.uses > int(default_inv["USES"]):
            self.add_non_refer(member)
            self.settings[server.id]["DEFAULT_INVITE"]["USES"] = invite.uses
            dataIO.save_json(self.settings_path, self.settings)

    @commands.group(pass_context=True, invoke_without_command=True, no_pm=True)
    @checks.admin_or_permissions(administrator=True)
    async def referralset(self, ctx):
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @referralset.command(pass_context=True, no_pm=True, name="default-invite")
    async def default_invite(self, ctx, invite_id : str):
        """
        !!! Not functional !!!
        Set default invite for server. Give a valid invite ID.
        """
        server = ctx.message.server
        try:
            invite = await self.bot.get_invite(invite_id)
        except:
            await self.bot.say("Could not retrieve invite, make sure to use a valid invite ID.")
            return

        if server.id not in self.settings.keys():
            self.settings[server.id] = {}
            self.settings[server.id]["DEFAULT_INVITE"] = {}
        elif "DEFAULT_INVITE" not in self.settings[server.id].keys():
            self.settings[server.id]["DEFAULT_INVITE"] = {}

        self.settings[server.id]["DEFAULT_INVITE"]["ID"] = invite_id
        self.settings[server.id]["DEFAULT_INVITE"]["USES"] = invite.uses
        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("Counts: {}".format(invite.uses))
        await self.bot.say("Default invite changed.")

    @referralset.command(pass_context=True, no_pm=True, name="min-account-age")
    async def min_account_age(self, ctx, days : int):
        """
        Set the min age (in days) a new user must have been on discord before they can set a referer.
        """
        server = ctx.message.server

        if server.id not in self.settings.keys():
            self.settings[server.id] = {}
            self.settings[server.id]["MIN_ACCOUNT_AGE"] = 0
        elif "MIN_ACCOUNT_AGE" not in self.settings[server.id].keys():
            self.settings[server.id]["MIN_ACCOUNT_AGE"] = 0

        self.settings[server.id]["MIN_ACCOUNT_AGE"] = days
        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("Minimum account age set to {}.".format(days))

    @referralset.command(pass_context=True, no_pm=True, name="clear")
    async def clear_refer_data(self, ctx):
        """
        Clears ALL current referrals and refer blacklist.
        It then puts all current server's members onto the blacklist.
        """
        await self.bot.say("All current referral data (not settings) will be cleared, continue? (y/n)")
        message = await self.bot.wait_for_message(author=ctx.message.author, channel=ctx.message.channel)
        server = ctx.message.server

        if message.content.lower() == "y":
            self.clear_refers(ctx.message.server)
            await self.bot.say("Referral data cleared.")
        else:
            await self.bot.say("Cancelled.")

    @referralset.command(pass_context=True, no_pm=True, name="setup")
    async def setup(self, ctx):
        """
        Setup referral cog for server.
        When first loading the referral module, make sure to run setup to add all current users to the blacklist for referrals.
        !!! WILL CLEAR ALL DATA FOR SERVER! !!!
        """
        await self.bot.say("All current data will be cleared, continue? (y/n)")
        message = await self.bot.wait_for_message(author=ctx.message.author, channel=ctx.message.channel)
        server = ctx.message.server

        if message.content.lower() == "y":
            self.settings[server.id] = {}
            self.settings[server.id]["MIN_ACCOUNT_AGE"] = 0
            self.settings[server.id]["DEFAULT_INVITE"] = {}
            #self.settings[server.id]["NON-REFERRALS"] = []
            #self.settings[server.id]["REFERRALS"] = {}
            self.clear_refers(server)
            await self.bot.say("Referral cog setup for this server!")
            dataIO.save_json(self.settings_path, self.settings)
        else:
            await self.bot.say("Canceled. No changes made")

    @commands.group(pass_context=True, invoke_without_command=True, no_pm=True)
    async def refer(self, ctx, user: discord.Member):
        server = ctx.message.server
        if user:
            author = ctx.message.author
            thresh = self.settings.get(server.id, {}).get("MIN_ACCOUNT_AGE", 0)
            author_days_old = (ctx.message.timestamp - author.created_at).days
            user_days_old = (ctx.message.timestamp - user.created_at).days
            if author_days_old > thresh and user_days_old > thresh:
                if author.id in self.settings[server.id]["NON-REFERRALS"]:
                    await self.bot.say("Sorry, you already set someone as your referrer or were already on the server.")
                    return
                elif author.id == user.id:
                    await self.bot.say("Sorry, you cannot refer yourself.")
                    return
                elif user.id == self.bot.user.id:
                    await self.bot.say("Thanks for trying, but you cannot set me as your referrer.")
                    return
                if user.id not in self.settings[server.id]["REFERRALS"].keys():
                    self.settings[server.id]["REFERRALS"][user.id] = [author.id]
                else:
                    self.settings[server.id]["REFERRALS"][user.id].append(author.id)
                await self.bot.say("Referrer set to {}, thank you!".format(user.name))
                self.add_non_refer(author)
                dataIO.save_json(self.settings_path, self.settings)
            elif author_days_old < thresh:
                await self.bot.say("Sorry, your account is too new! Your account needs to be at least {} days old but it is {} days old.".format(thresh, author_days_old))
            else:
                await self.bot.say("Sorry, your referrer's account is too new! Their account needs to be at least {} days old but it is {} days old.".format(thresh, user_days_old))
        elif ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @refer.command(pass_context=True, no_pm=True, name="list")
    async def check_referrals(self, ctx):
        """
        Checks how many people you have referred, and who referred you.
        """
        author = ctx.message.author
        server = ctx.message.server
        settings = self.settings.get(server.id, {})
        msg = "Your Referrals:\n"
        referrals = settings.get("REFERRALS", {})
        author_referrals = settings.get("REFERRALS", {}).get(author.id, None)

        if not author_referrals:
            msg += "**None**\n"
        else:
            for refer in author_referrals:
                member = await self.bot.get_user_info(refer)
                msg += "`{}`\n".format(member.name)

        msg += "\nYour referer:\n"
        flag = 0
        for user_id in referrals.keys():
            for refer in referrals[user_id]:
                if refer == author.id:
                    user = await self.bot.get_user_info(user_id)
                    msg += "`{}`\n".format(user.name)
                    flag = 1
                    break
            if flag:
                break

        if not flag:
            msg += "**None**\n"

        await self.bot.say(msg)

    @refer.command(pass_context=True, no_pm=True, name="raffle")
    @checks.admin_or_permissions(administrator=True)
    async def raffle(self, ctx, winners : int):
        """
        Chooses specified amount of winners from users who have referrals. Each referral is a "raffle ticket" for the user.
        Once a winner is chooses, they cannot be choosen again.
        """
        server = ctx.message.server
        settings = self.settings.get(server.id, {})

        referrers = list(settings.get("REFERRALS", {}).keys())
        raffle_list = []

        if not referrers:
            await self.bot.say("No one has referred anyone yet.")
            return

        for refer in referrers:
            for _ in range(len(settings.get("REFERRALS", {}).get(refer, []))):
                raffle_list.append(refer)

        random.shuffle(raffle_list)
        selection = []
        for i in range(winners):
            winner = random.choice(raffle_list)
            selection.append(winner)
            raffle_list = [x for x in raffle_list if x != winner]
            if not raffle_list:
                break


        msg = "**Here are the winners!**\n"
        for i, winner in enumerate(selection):
            user = await self.bot.get_user_info(winner)
            msg += "{}. `{}`\n".format(i + 1, user.display_name)

        await self.bot.say(msg)


def check_files():
    if not os.path.exists('data/referral/settings.json'):
        os.makedirs('data/referral', exist_ok=True)
        dataIO.save_json('data/referral/settings.json', {})


def setup(bot):
    check_files()
    n = Referral(bot)
    bot.add_cog(n)
    #bot.add_listener(n.member_join_listener, "on_member_join")
