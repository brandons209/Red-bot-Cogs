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


"""This cog generates scripts based on imported model, I used a keras model. """
class ScriptCog:

    def __init__(self, bot):
        self.bot = bot

        os.makedirs("data/scriptcog/", exist_ok=True)
        os.makedirs("data/scriptcog/dicts", exist_ok=True)
        self.model_path = "data/scriptcog/model.h5"
        self.dict_path = "data/scriptcog/dicts/"

        self.cooldown = time.time()

        try:
            self.model = load_model(self.model_path)
        except:
            self.model = None

        if os.path.isfile("data/scriptcog/config.txt"):
            with open("data/scriptcog/config.txt", "r") as f:
                content = f.read()
                content = content.split()
            self.word_limit = int(content[0])
            self.cooldown_limit = int(content[1])
            self.tv_show = content[2]
        else:
            with open("data/scriptcog/config.txt", "w") as f:
                f.write("100 30 MLP")
            self.word_limit = 100
            self.cooldown_limit = 30
            self.tv_show = "MLP"

        try:
            self.word_to_int = _load_dict(self.dict_path + 'word_to_int.pkl')
            self.int_to_word = _load_dict(self.dict_path  + 'int_to_word.pkl')
            self.sequence_length = _load_dict(self.dict_path  + 'sequence_length.pkl')
        except:
            self.word_to_int = None
            self.int_to_word = None
            self.sequence_length = None

    def _write_config(self):
        with open("data/scriptcog/config.txt", "w") as f:
            f.write("{} {} {}".format(self.word_limit, self.cooldown_limit, self.tv_show))

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def setwordlimit(self, ctx, num_words : int = 100):
        #if ctx.invoked_subcommand is None:
        #    await self.bot.say("Usage: setwordlimit limit")
        #    return
        self.word_limit = num_words
        self._write_config()
        await self.bot.say("Maximum number of words is now {}".format(self.word_limit))

    @commands.command(pass_context=True, no_pm=True)
    async def genscriptinfo(self, ctx):
        await self.bot.say("Word Limit: {}, Cooldown Time: {}, Show: {}".format(self.word_limit, self.cooldown_limit, self.tv_show))

    @commands.command(pass_context=True, no_pm=True)
    async def genscripthelp(self, ctx):
        await self.bot.say("--------------------\nGenerate original TV scripts for {} using Neural Networks!\nUsage: `genscript number_of_words_to_generate word_variance starting_text`\nUse starting texts such as:\n`pinkie pie::`\n`fluttershy::`\n`twilight sparkle::`\nor other names of characters in the show. Otherwise, you can use any words said in the show.-------------------".format(self.tv_show))

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def settvshow(self, ctx, show : str = "MLP"):
        self.tv_show = show
        self._write_config()
        await self.bot.say("TV show is now {}.".format(self.tv_show))

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def setcooldown(self, ctx, cooldown : int = 30):
        self.cooldown_limit = cooldown
        self._write_config()
        await self.bot.say("Script cooldown is now {}.".format(self.cooldown_limit))


    @commands.command(pass_context=True, no_pm=True)
    async def genscript(self, ctx, num_words_to_generate : int = 100, variance : float = 0.5, seed : str = "pinkie pie::"):
        #if ctx.invoked_subcommand is None:
        #    await self.bot.say("Usage: genscript num_words randomness(between 0 and 1) seed_text")
        #    return
        if num_words_to_generate > self.word_limit:
            await self.bot.say("Please keep script sizes to {} words or less.".format(self.word_limit))
            return
        elif time.time() - self.cooldown < self.cooldown_limit:
            await self.bot.say("Sorry, I am cooling down, please wait {:.0f} seconds.".format(self.cooldown_limit - (time.time() - self.cooldown)))
            return

        self.cooldown = time.time()

        if variance > 1.0:
            variance = 1.0
        elif variance < 0:
            variance = 0

        await self.bot.say("Generating script, please wait...")
        input_text = seed
        for _  in range(num_words_to_generate):
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
            output_word = self.int_to_word[_sample(prediction, temp=variance)]
            #append to the result
            input_text += ' ' + output_word
        #convert tokenized punctuation and other characters back
        result = _untokenize_punctuation(input_text)
        await self.bot.say("------------------------")
        await self.bot.say(result)
        await self.bot.say("------------------------")

def setup(bot):
    bot.add_cog(ScriptCog(bot))
