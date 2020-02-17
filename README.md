# Brandons209's Cogs
## Cogs for discord's [Red-Bot](https://github.com/Cog-Creators/Red-DiscordBot)
![black-checker](https://github.com/brandons209/Red-bot-Cogs/workflows/black-checker/badge.svg)


Thank you for taking a look at my cogs, most of these are rewrites of other cogs, with a few of my own.


##### Activitylog
Full V2 port with most of the cog rewritten from [calebj](https://github.com/calebj/calebj-cogs). This is an all in one logger for all sorts of discord messages and events.    
**Features:**
- Track messages, attachments (url or download), voice channel states, audit log entries, DMs, and also who deletes messages and performs other audit log actions.
- Customizable log file rotation.
- Global/per guild/per channel logging preferences
- Pull logs for a channel or audit logs, with customizeable time ranges either in specifying exact dates or an interval from the current time.
- Track user statistics (how many messages sent, how many bot commands, how long in voice chats) per guild.
- Track username changes globally.
- Upgraded userinfo command that includes user stats and number of bans, mutes, and kicks.


#### Cost Manager
Allows dynamically setting costs for any commands registered to Red. Supports setting costs on a hierarchy that follows user > role > guild. Also can set guild wide roles that can use commands for free, and overriding these for certain commands. It also sends receipts to users and edits that message as they run commands so they can track their spending.    
**Features:**
- DM receipts will only notify the user once if it fails to send the message.
- Follows hierarchy, checks user cost first, then role cost, then guild wide cost and guild wide free roles.


#### Disable
Disable all bot commands except for admins in a guild. Customizable error message.


#### Economy Trickle
Currently rewriting parts from [Sinbad](https://github.com/mikeshardmind/SinbadCogs). Nothing changed yet.


#### Events
Made for a friend, pretty messy. Send custom events and log time since that event. Unsupported and won't be updated for much else.


#### MoreAdmin
More admin commands that provide various functionality.    
**Features**:
- Purge(kick) inactive users with a specific role. Can purge by last message or account age. DM's user with a notice of removal and an invite link to rejoin the guild. ~~Logs purges to modlog.~~(removed logging for now)
- Set channel to display online/total users for guild.
- Log "suspicious" users who join. Suspicious users are new accounts, threshold to determine an account as new can be set.
- Give and remove roles based on user's currents roles. This allows setting a role to be giveable by users who have a specific set role.
- Set a role to be pingable for a specific amount of time.
- Hidden say and selfdm commands for setting helpful aliases with these commands.
- Send, send attachment, edit, and get commands for bot's messages. Useful for sending rules by the bot so that anyone can edit those.
- List all users with a role/roles quickly and easily.


#### Nitro Emoji
Allows nitro boosters to add one emoji to your server. Log's additions and removal of custom emojis to a channel. Can turn this off to stop more people from adding, but those who added can remove their emoji.


#### Pony
Search derpibooru for pony images. Ported from [Alzarath](https://github.com/Alzarath/Booru-Cogs).    
**Features:**   
- Filter by tags.
- Verbose mode.
- Get random and latest image results.


#### Punish
Port from [calebj](https://github.com/calebj/calebj-cogs) punish cog. Functionality mostly retained. Allows adding a custom Punished role to a user to lock them out of all channels in your server except a designated one.    
**Features:**
- Set roles to remove when punishing to bypass per channel overrides on some roles.
- Customize channel overrides for the punish role.
- Creates modlog cases for punishments.
- Log cases created/updated when manually adding or removing role without the command.


#### ReactPoll
Modified from [flapjax](https://github.com/flapjax/FlapJack-Cogs). Uses base of v2 version ported to v3, with the added functionality of watching reactions on polls to enforce one vote per user and no custom reactions adding. Also supports saving polls to disk in case bot shutdowns during poll and resumes them on boot.


#### Role Management
Modified from [Sinbad](https://github.com/mikeshardmind/SinbadCogs).    
**Features:***
- Adds in subscription based roles which renew every customized interval.
- Allows settings messages through DM to users who obtain a specific role (such as role info).
- Renames srole to selfrole and removes Red's default selfrole.
- Makes listing roles a bit prettier.
- Allow setting roles to automatically add on guild join.
- Enhance exclusive roles, allow setting custom role groups where the bot enforces only one role to be on a user at a time, even if it isn't a selfrole. The bot will automatically remove the old role if a new role from the same group is added. Also lists name of role group in list command to make it clearer.


#### Roleplay
Assorted roleplay commands. Uses ASCII art.    
**Features:**
- Improved hug, don't need to @ a user nor use quotes if their name has spaces.
- Slap users, with customizeable slaps.
- IQ test, with customizeable messages.
- Army (for [Champions of Equestria use only](http://discord.championsofequestria.town))
- Boop.
- Bap.
- Improved Flip don't need to @ a user nor use quotes if their name has spaces.


#### Welcome
Modified from [tmerc](https://github.com/tmercswims/tmerc-cogs), adding a nicely formatted role list as an option for messages. Feature submitted to tmerc.
- Also adds integration with my activitylog cog, allowing posting of user stats in welcome messages. (Such as leaving and wanting to know how active a person was when they leave.)
