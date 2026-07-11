# Brandons209's Cogs
## Cogs for discord's [Red-Bot](https://github.com/Cog-Creators/Red-DiscordBot)
![black-checker](https://github.com/brandons209/Red-Bot-Cogs/actions/workflows/black-checker.yml/badge.svg)


Thank you for taking a look at my cogs! Open an issue if you run into a problem or need help.

### Activitylog
Detailed logging for channels, audit events, voice activity, and more! Export chat logs to an easy to read HTML for moderation review and archiving. Logs can be stored in either sqlite or mysql databases. A variety of data analyses on logged data is available as well.
**Features:**
- Track messages, attachments (url or download), voice channel states, audit log entries, DMs, and also who deletes messages and performs other audit log actions.
- Global/per guild/per channel logging preferences
- Pull logs for a channel or audit logs, with customizable time ranges either in specifying exact dates or an interval from the current time.
- Track user statistics (how many messages sent, how many bot commands, how long in voice chats) per guild.
- Track username changes globally.
- Upgraded userinfo command that includes user stats and number of bans, mutes, and kicks.


### AntiBot
Automated anti-bot / anti-raid moderation. Several detectors feed one shared action pipeline, so every trip is handled the same way: an optional DM, the configured action, message deletion, a modlog case, and an alert to your notify channel.
**Features:**
- Detectors: cross-channel spam (same message posted across many channels quickly), suspicious joins by account age, role-ping abuse with automatic role lockdown, Discord's suspected-spammer badge, honeypot channels, unusual DMs to the bot, and human-in-the-loop bot "signature" learning.
- Per-detector actions: none, log, notify, timeout, kick, ban, or assign a quarantine role.
- Safeguards against false positives: immunity for owner/admin/bot-owner, whitelisted roles and channels, and per-detector new-account/new-member gates.
- Modlog cases and a configurable notify channel and ping role for every action.
- Configure by command or the interactive `[p]antibot panel`. Requires the Members and Message Content privileged intents.


### Birthday
Allow users to set their birthday and have it announced in a channel. Also gives the user a birthday role and sends them a customizable DM message. Checks for birthdays at user's configured timezone.


### Campaigns
Create and manage user feedback campaigns: ask a set of custom questions, validate the input, run them on a timer, and export responses to CSV.


### Chatbot Assistant
Your own chatbot assistant, available using Ollama or OpenAI compatible endpoints. Has built in functionality to use RAG (retrieval augmented generation) databases to dynamically use emojis, learn user profiles, and dynamic example injection into prompts. **Currently in Alpha, some things may not work or not easily customizable**.
**Features:**
- Chatbot assistant that acts like a member of your community: Customizable dynamic injection into chats, goodbye messages to have the assistant "leave" chats organically, welcoming new users, and more.
- Summary and TLDR: Generate summaries and TLDRs of chats/threads for moderation or note keeping.
- RAG: Automatic profile learning of users, proper emoji usage, example injections
- Fun general commands: Generate compliments or dadjokes on the fly!


### Disable
Disable all bot commands except for admins in a guild. Customizable error message.


### EveryoneEmoji
Upload and post emojis through the bot so non-nitro users can send animated emojis.


### Follower
Follow another user and get notified when they talk in a channel after a period of inactivity (1 hour). Users can opt out, view their followers, and block other users from following them.


### Image Magic
Image transformation commands to create funny or interesting photos.
**Features**
- Barrel effect
- Implode effect
- Zoom
- Black and white
- Sketch transformation
- Deepfry
- Nuke


### MayhemMaker
Allow your users to cause (controlled) mayhem! Allow for renaming of users, adding configurable roles, and shutting them up for 60 seconds!
**Features**:
- Customizable cooldowns for each command for both usage and application
- Integration with [vrt-cog's levelup](https://github.com/vertyco/vrt-cogs/tree/main/levelup) system for dynamic cooldowns based on level.


### Memeify
Turn text into memes.
**Features**
- Bify: make every word start with B emoji and every B into one.
- Frenchify: add a French accent to text


### MoreAdmin
More admin commands that provide various functionality.
**Features**:
- Set channel to display online/total users for guild.
- For communities - add a baited role check where bot accounts usually will select during onboarding that your bot can automatically kick/ban
- Log "suspicious" users who join. Suspicious users are new accounts, threshold to determine an account as new can be set.
- Give and remove roles based on user's current roles. This allows setting a role to be giveable by users who have a specific set role.
- Set a role to be pingable for a specific amount of time.
- Hidden say and selfdm commands for setting helpful aliases with these commands.
- Send, send attachment, edit, and get commands for bot's messages. Useful for sending rules by the bot so that anyone can edit those.
- Customized DM message for banning users.
- Mods/Admins can add notes to users


### Nitro Emoji
Allows nitro boosters to add one emoji to your server. Logs additions and removals of custom emojis to a channel. Can turn this off to stop more people from adding, but those who added can remove their emoji. Allows setting roles that can add a customizable amount of emojis to the server. If roles are removed/amount of emojis changed, the bot will automatically remove/update user's emojis.


### Patreon Roles
Manage roles for Patreon subscribers, assigning roles based on subscription length.


### Personal Roles
Modified from Fixator10, added functionality of automatically creating/deleting personal roles for users who are allowed to have one. Roles automatically created are placed in the hierarchy under an existing role set by the user. It also allows setting roles that allow users to automatically have their personal role created and used. Manual usage is still available as well.
**Features**
- Users can customize their role name and color through the bot.
- Blacklist words that aren't allowed in role names.
- Automatically create/manage personal roles.
- Users can add and remove role icons if the guild has the feature


### Pony
Search derpibooru for pony images. Ported from [Alzarath](https://github.com/Alzarath/Booru-Cogs).
**Features:**
- Filter by tags.
- Verbose mode.
- Get random and latest image results.
- Include Artist when posting images


### Punish
Port from [calebj](https://github.com/calebj/calebj-cogs) punish cog. Functionality mostly retained. Allows adding a custom Punished role to a user to lock them out of all channels in your server except a designated one.
**Features:**
- Set roles to remove when punishing to bypass per channel overrides on some roles.
- Customize channel overrides for the punish role.
- Creates modlog cases for punishments.
- Log cases created/updated when manually adding or removing role without the command.


### Role Management
Modified from [Sinbad](https://github.com/mikeshardmind/SinbadCogs).
**Features:**
- Adds in subscription based roles which renew every customized interval.
- Allows settings messages through DM to users who obtain a specific role (such as role info).
- Renames srole to selfrole and removes Red's default selfrole.
- Makes listing roles a bit prettier.
- Allow setting roles that are automatically added to user when they obtain a certain role.
- Allow setting roles to automatically add on guild join.
- Enhance exclusive roles, allow setting custom role groups where the bot enforces only one role to be on a user at a time, even if it isn't a selfrole. The bot will automatically remove the old role if a new role from the same group is added. Also lists name of role group in list command to make it clearer.


### Roleplay
Assorted roleplay commands. Uses ASCII art.
**Features:**
- Improved hug, don't need to @ a user nor use quotes if their name has spaces.
- Slap users, with customizable slaps.
- IQ test, with customizable messages.
- Army (for [Champions of Equestria use only](http://discord.championsofequestria.town))
- Boop.
- Bap.
- Improved Flip don't need to @ a user nor use quotes if their name has spaces.


### ServerWatch
Track TF2 / Source-engine game servers over the A2S protocol and ping roles when a server fills up.
**Features:**
- Track multiple servers per guild by host and query port.
- Threshold rules that ping a role when the player count is crossed, with per-rule messages and placeholders like `{current_players}`, `{max_players}`, and `{map}`.
- Hysteresis on the pings: a rule fires once on a crossing and re-arms only after the count drops and stays down, so a busy server or a map change does not spam the ping.
- Live status as an auto-refreshed embed/message, or as a renamed voice/text channel.
- Custom connect line (for example a `steam://connect` join link).
- Configure by command or the interactive `[p]serverwatch panel`.


### Smart React
Auto react to messages based on keywords. Based off of [FlapJack's](https://github.com/flapjax/FlapJack-Cogs/) cog. Minor bug fixes and planned features, like using regex to parse messages.


### Starboard
Create a starboard channel to save your community's top-voted posts. Once a message reaches the reaction threshold, the bot reposts it to the starboard.


### Subscriber
Manage role subscriptions for your guild, useful for donator or other type of roles.
**Features**:
- Automatic reminders when a user's role is about to expire
- Easily add, remove, modify user's subscribed roles
- User's can view their current subscribed roles and when they expire


### Suggestion
Modified from @saurichable. Adds a few features we needed.
**Added Features**
- Listing the final vote count when a suggestion is approved or denied
- Added reasons for approved suggestions, since sometimes we accept a suggestion but we may modify it
- Approved reasons are marked green, denied are marked red
- Optionally create threads for each suggestion for easier discussion


### Thread Manager
A simple thread manager that allows guild staff to set certain roles to create a customizable number of threads per channel. Manual archive by users is not supported right now.


### Time Helper
Time helper makes it easy to format specific dates, times, and relative times into discord timestamps, or convert them into multiple other timezones. You can also set your own timezone so that you don't need to specify your timezone when using the cog!


### Warnings Custom
Adds a few features that are needed for my server, modified from the built in warning cog.
**Added Features**
- Add context to warnings, if enabled. This allows adding some extra information after giving a warning. We had issues where warnings without context were hard to look back upon. Can send attachments too, included in modlog entry.
- Shows dates for warnings for both users and mods, and also case number for mods when looking at a user's warnings.
- Warning points can be set as expired after a time. Warnings are still on record but a user's recorded points for actions will be based on non-expired warnings


### Watchlist
Keep track of persons of interest inside and outside your guild. Staff get notified when a watched user joins or leaves.


### Welcome
Modified from [tmerc](https://github.com/tmercswims/tmerc-cogs), adding a nicely formatted role list as an option for messages. Feature submitted to tmerc.
- Also adds integration with my activitylog cog, allowing posting of user stats in welcome messages. (Such as leaving and wanting to know how active a person was when they leave.)
