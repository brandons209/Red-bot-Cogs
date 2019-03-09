import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.converters import GlobalUser

from keras.models import load_model
from keras.preprocessing.sequence import pad_sequences

import numpy as np
import os
import pickle
import time
import asyncio

from .utils.dataIO import dataIO
from .utils.chat_formatting import warning

#loads dictionary from file
def _load_dict(path):
    with open(path, 'rb') as file:
        dict = pickle.load(file)
    return dict

#dictionaries for tokenizing puncuation and converting it back
punctuation_to_tokens = {'!':' ||exclaimation_mark|| ', ',':' ||comma|| ', '"':' ||quotation_mark|| ',
                          ';':' ||semicolon|| ', '.':' ||period|| ', '?':' ||question_mark|| ', '(':' ||left_parentheses|| ',
                          ')':' ||right_parentheses|| ', '--':' ||dash|| ', '\n':' ||return|| ', ':':' ||colon|| '}

tokens_to_punctuation = {token.strip(): punc for punc, token in punctuation_to_tokens.items()}

#for all of the puncuation in replace_list, convert it to tokens
def _tokenize_punctuation(text):
    replace_list = ['.', ',', '!', '"', ';', '?', '(', ')', '--', '\n', ':']
    for char in replace_list:
        text = text.replace(char, punctuation_to_tokens[char])
    return text

#convert tokens back to puncuation
def _untokenize_punctuation(text):
    replace_list = ['||period||', '||comma||', '||exclaimation_mark||', '||quotation_mark||',
                    '||semicolon||', '||question_mark||', '||left_parentheses||', '||right_parentheses||',
                    '||dash||', '||return||', '||colon||']
    for char in replace_list:
        if char == '||left_parentheses||':#added this since left parentheses had an extra space
            text = text.replace(' ' + char + ' ', tokens_to_punctuation[char])
        text = text.replace(' ' + char, tokens_to_punctuation[char])
    return text

"""
helper function that instead of just doing argmax for prediction, actually taking a sample of top possible words
takes a tempature which defines how many predictions to consider. lower means the word picked will be closer to the highest predicted word.
"""
def _sample(prediction, temp=0):
    if temp <= 0:
        return np.argmax(prediction)
    prediction = prediction[0]
    prediction = np.asarray(prediction).astype('float64')
    prediction = np.log(prediction) / temp
    expo_prediction = np.exp(prediction)
    prediction = expo_prediction / np.sum(expo_prediction)
    probabilities = np.random.multinomial(1, prediction, 1)
    return np.argmax(probabilities)

def _resolve_role_list(server: discord.Server, roles: list) -> list:
    gen = (_role_from_string(server, name) for name in roles)
    return list(filter(None, gen))

def _role_from_string(server, rolename, roles=None):
    if roles is None:
        roles = server.roles

    roles = [r for r in roles if r is not None]
    role = discord.utils.find(lambda r: r.name.lower() == rolename.lower(), roles)
    # if couldnt find by role name, try to find by role id
    if role is None:
        role = discord.utils.find(lambda r: r.id == rolename, roles)

    return role

def format_list(*items, join='and', delim=', '):
    if len(items) > 1:
        return (' %s ' % join).join((delim.join(items[:-1]), items[-1]))
    elif items:
        return items[0]
    else:
        return ''

"""This cog generates scripts based on imported model, I used a keras model. """
class ScriptCog:

    def __init__(self, bot):
        self.bot = bot
        self.model_path = "data/scriptcog/model.h5"
        self.dict_path = "data/scriptcog/dicts/"

        self.cooldown = time.time()

        try:
            self.model = load_model(self.model_path)
        except:
            self.model = None

        self.settings_path = "data/scriptcog/settings.json"
        self.settings = dataIO.load_json(self.settings_path)

        self.default_word_limit = 300
        self.default_cooldown_limit = 30
        self.default_tv_show = "My Little Pony"
        self.default_price = 0

        try:
            self.word_to_int = _load_dict(self.dict_path + 'word_to_int.pkl')
            self.int_to_word = _load_dict(self.dict_path  + 'int_to_word.pkl')
            self.sequence_length = _load_dict(self.dict_path  + 'sequence_length.pkl')
        except:
            self.word_to_int = None
            self.int_to_word = None
            self.sequence_length = None

    @commands.group(pass_context=True, invoke_without_command=True, no_pm=True)
    @checks.admin_or_permissions(administrator=True)
    async def genscriptset(self, ctx):
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @genscriptset.command(pass_context=True, no_pm=True, name="word-limit")
    @checks.is_owner()
    async def genscriptset_set_word_limit(self, ctx, num_words : int):
        """
        Set the word limit for generating scripts.
        """
        try:
            self.settings[ctx.message.server.id]["WORD_LIMIT"] = num_words
        except:
            self.settings[ctx.message.server.id] = {}
            self.settings[ctx.message.server.id]["WORD_LIMIT"] = num_words

        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("Maximum number of words is now {}".format(num_words))

    @genscriptset.command(pass_context=True, no_pm=True, name="tv-show")
    @checks.is_owner()
    async def genscriptset_set_tv_show(self, ctx, *, show):
        """
        Sets the TV show the scripts are generated from.
        """
        try:
            self.settings[ctx.message.server.id]["TV_SHOW"] = show
        except:
            self.settings[ctx.message.server.id] = {}
            self.settings[ctx.message.server.id]["TV_SHOW"] = show

        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("TV show is now {}.".format(show))

    @genscriptset.command(pass_context=True, no_pm=True, name="cooldown")
    @checks.is_owner()
    async def genscriptset_set_cooldown(self, ctx, cooldown : int):
        """
        Sets the cooldown period between generating scripts in seconds.
        """
        try:
            self.settings[ctx.message.server.id]["COOLDOWN"] = cooldown
        except:
            self.settings[ctx.message.server.id] = {}
            self.settings[ctx.message.server.id]["COOLDOWN"] = cooldown

        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("Script cooldown is now {}.".format(cooldown))

    @genscriptset.command(pass_context=True, no_pm=True, name="price")
    async def genscriptset_set_price(self, ctx, price : int):
        """
        Sets the price for generating scripts.
        """
        try:
            self.settings[ctx.message.server.id]["PRICE"] = price
        except:
            self.settings[ctx.message.server.id] = {}
            self.settings[ctx.message.server.id]["PRICE"] = price

        dataIO.save_json(self.settings_path, self.settings)
        await self.bot.say("Price is now {}.".format(price))

    @genscriptset.command(pass_context=True, no_pm=True, name="free-roles")
    async def genscriptset_free_roles(self, ctx, *, rolelist=None):
        """Set roles that do not have to pay to generate scripts.

        COMMA SEPARATED LIST (e.g. Admin,Staff,Mod), Can also use role IDs as well.

        To get current list, run command with no roles.

        Add role_list_clear as the role to clear the server\'s free role list.
        """
        server = ctx.message.server
        current_roles = _resolve_role_list(server, self.settings[server.id].get("FREE_ROLE_LIST", []))

        if rolelist is None:
            if current_roles:
                names_list = format_list(*(r.name for r in current_roles))
                await self.bot.say("Current list of roles that do not have to pay: {}".format(names_list))
            else:
                await self.bot.say("No roles defined.")
            return
        elif "role_list_clear" in rolelist.lower():
            await self.bot.say("Free role list cleared.")
            self.settings[server.id]["FREE_ROLE_LIST"] = []
            dataIO.save_json(self.settings_path, self.settings)
            return

        found_roles = set()
        notfound_names = set()

        for lookup in rolelist.split(","):
            lookup = lookup.strip()
            role = _role_from_string(server, lookup)

            if role:
                found_roles.add(role)
            else:
                notfound_names.add(lookup)

        if notfound_names:
            fmt_list = format_list(*("`{}`".format(x) for x in notfound_names))
            await self.bot.say(warning("These roles were not found: {}\n\nPlease try again.".format(fmt_list)))
        elif server.default_role in found_roles:
            await self.bot.say(warning("The everyone role cannot be added.\n\nPlease try again."))
        elif found_roles == set(current_roles):
            await self.bot.say("No changes to make.")
        else:
            if server.id not in self.settings:
                self.settings[server.id] = {}
            else:
                extra = ""

            self.settings[server.id]["FREE_ROLE_LIST"] = [r.id for r in found_roles]
            dataIO.save_json(self.settings_path, self.settings)

            fmt_list = format_list(*(r.name for r in found_roles))
            await self.bot.say("These roles will not have to pay for scripts: {}.{}".format(fmt_list, extra))

    @commands.command(pass_context=True, no_pm=True)
    async def genscriptinfo(self, ctx):
        server_id = ctx.message.server.id
        word_limit = self.settings.get(server_id, {}).get("WORD_LIMIT", self.default_word_limit)
        cooldown = self.settings.get(server_id, {}).get("COOLDOWN", self.default_cooldown_limit)
        tv_show =  self.settings.get(server_id, {}).get("TV_SHOW", self.default_tv_show)
        price = self.settings.get(server_id, {}).get("PRICE", self.default_price)
        await self.bot.say("Word Limit: {}, Cooldown Time: {}, Show: {}, Price: {}".format(word_limit, cooldown, tv_show, price))

    @commands.command(pass_context=True, no_pm=True)
    async def genscripthelp(self, ctx):
        await self.bot.say("--------------------\nGenerate original TV scripts for {} using Neural Networks!\nUsage: `genscript <number of words to generate> <word variance> <starting text>`\nUse starting texts such as:\n`pinkie pie::`\n`fluttershy::`\n`twilight sparkle::`\nor other names of characters in the show. Otherwise, you can use any words said in the show.\n\nWord variance helps gives the script better results. A variance of 0 will mean that with the same starting text, it will always have the same output. Variance up to 1.0 will give more variety to words, however going closer to 1 can introduce more grammar and spelling mistakes.\n-------------------".format(self.settings.get(ctx.message.server.id, {}).get("TV_SHOW", self.default_tv_show)))

    @commands.command(pass_context=True, no_pm=True)
    async def genscript(self, ctx, num_words_to_generate : int, variance : float, *, seed):
        """
        Generate a script using the power of Neural Networks!
        Please use the genscripthelp command to get a complete explaination of how to use the command.
        """
        server_id = ctx.message.server.id
        word_limit = self.settings.get(server_id, {}).get("WORD_LIMIT", self.default_word_limit)
        cooldown = self.settings.get(server_id, {}).get("COOLDOWN", self.default_cooldown_limit)
        price = self.settings.get(server_id, {}).get("PRICE", self.default_price)
        user = ctx.message.author

        if num_words_to_generate > word_limit:
            await self.bot.say("Please keep script sizes to {} words or less.".format(word_limit))
            return
        elif time.time() - self.cooldown < cooldown:
            await self.bot.say("Sorry, I am cooling down, please wait {:.0f} seconds.".format(cooldown - (time.time() - self.cooldown)))
            return

        if not self.check_free_role(user):
            return_val = self.charge_user(user, price)
            if return_val == 1: #if this worked, dont need to check when getting econ cog
                balance = self.bot.get_cog('Economy').bank.get_balance(user)
                await self.bot.say("Charged: {}, Balance: {}".format(price, balance))
            else:
                await self.charge_user_check(return_val, price, user)
                return

        self.cooldown = time.time()

        if variance > 1.0:
            variance = 1.0
        elif variance < 0:
            variance = 0

        await self.bot.say("Generating script, please wait...")
        await self.get_model_output(num_words_to_generate, variance, seed)

    async def get_model_output(self, num_words, temp, seed):
        input_text = seed
        for _  in range(num_words):
            #tokenize text to ints
            int_text = _tokenize_punctuation(input_text)
            int_text = int_text.lower()
            int_text = int_text.split()
            try:
                int_text = np.array([self.word_to_int[word] for word in int_text], dtype=np.int32)
            except KeyError:
                await self.bot.say("Sorry, that seed word is not in my vocabulary.\nPlease try an English word from the show.\n")
                return
            #pad text if it is too short, pads with zeros at beginning of text, so shouldnt have too much noise added
            int_text = pad_sequences([int_text], maxlen=self.sequence_length)
            #predict next word:
            prediction = self.model.predict(int_text, verbose=0)
            output_word = self.int_to_word[_sample(prediction, temp=temp)]
            #append to the result
            input_text += ' ' + output_word
        #convert tokenized punctuation and other characters back
        result = _untokenize_punctuation(input_text)
        await self.bot.say("------------------------")
        await self.bot.say(result)
        await self.bot.say("------------------------")

    def charge_user(self, user, amount):
        """
        Takes a user and a amount and charges the user. Returns 1 on success, 0 if economy cog cannot be loaded, -1 if the user does not have a bank account, and -2 if the user doesn't have enough credits.
        """
        econ_cog = self.bot.get_cog('Economy')
        if not econ_cog:
            return 0
        if not econ_cog.bank.account_exists(user):
            return -1
        if not econ_cog.bank.can_spend(user, amount):
            return -2
        econ_cog.bank.withdraw_credits(user, amount)
        return 1

    async def charge_user_check(self, return_val, amount, user):
        """
        takes in return vals from charge_user and gives apporiate response
        """
        econ_cog = self.bot.get_cog('Economy')
        if not econ_cog:
            await self.bot.say("Error loading economy cog!")
            return
        if return_val == 0:
            await self.bot.say("Economy cog not found! Please check to make sure the economy cog is loaded.")
        elif return_val == -1:
            await self.bot.say("You appear to not have a bank account. Use [p]bank register to open an account.")
        elif return_val == -2:
            await self.bot.say("You do not have enough credits. The sound command costs {} and you have {} credits in your bank account.".format(amount, econ_cog.bank.get_balance(user)))

    def check_free_role(self, user):
        """
        Checks if the user has a role that grants them free sounds. Returns 1 if the user does have one of these roles, zero otherwise.
        """
        server = user.server
        free_roles = self.settings.get(server.id, {}).get("FREE_ROLE_LIST", [])
        if not free_roles:
            return 0
        user_roles = [r.id for r in user.roles]

        for role in free_roles:
            if role in user_roles:
                return 1

        return 0

def check_folders():
    os.makedirs("data/scriptcog", exist_ok=True)
    os.makedirs("data/scriptcog/dicts", exist_ok=True)
    f = "data/scriptcog/settings.json"
    if not dataIO.is_valid_json(f):
        dataIO.save_json(f, {})

def setup(bot):
    check_folders()
    bot.add_cog(ScriptCog(bot))
