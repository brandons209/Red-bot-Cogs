# Campaign Cog Documentation

## Overview

The Campaign Cog is a comprehensive Red-Discordbot extension designed to facilitate user feedback collection through customizable campaigns. This cog enables server administrators to create structured surveys with up to 20 questions, distribute them to users, and export the collected data for analysis.

## Features

### Core Functionality
- **Campaign Creation**: Create named campaigns with descriptions and custom questions
- **Question Types**: Support for multiple question types including short text, long text, numbers, multiple choice, and single choice
- **Input Validation**: Custom regex validation with error messages for enhanced data quality
- **Timer System**: Automatic campaign expiration with configurable durations
- **Interactive UI**: Discord Views with buttons and modals for seamless user interaction
- **Distribution Options**: Send campaigns to channels or DM users directly
- **Data Export**: Export responses to CSV format for external analysis
- **Statistics**: View campaign statistics and response rates

### Question Types Supported
1. **Short Text**: Brief text responses (up to 100 characters)
2. **Long Text**: Detailed text responses (up to 1000 characters)
3. **Number**: Numeric input with validation
4. **Multiple Choice**: Users can select multiple options from a list
5. **Single Choice**: Users select one option from a list

### Administrative Controls
- **Permission-based**: Requires `manage_guild` permission for campaign management
- **Campaign Lifecycle**: Create, start, stop, and delete campaigns
- **Response Management**: View individual responses and campaign statistics
- **Data Export**: Generate CSV files with all response data

## Installation

1. Place the `campaign_cog` folder in your Red-Discordbot's cogs directory
2. Use the command `[p]load campaign_cog` to load the cog
3. The cog will automatically register its configuration and be ready for use

## Command Reference

### Campaign Management

#### `[p]campaign create <name> <description>`
Creates a new feedback campaign.
- **name**: Campaign name (max 100 characters)
- **description**: Campaign description (max 500 characters)
- **Returns**: Campaign ID for future reference

#### `[p]campaign add_question <campaign_id> <type> <question_text>`
Adds a question to an existing campaign.
- **campaign_id**: The ID of the campaign
- **type**: Question type (short_text, long_text, number)
- **question_text**: The question to ask users

#### `[p]campaign add_choice_question <campaign_id> <type> <question_text> <options...>`
Adds a multiple choice or single choice question.
- **type**: multiple_choice or single_choice
- **options**: List of choices (2-10 options)

#### `[p]campaign add_validation <campaign_id> <question_id> <regex_pattern> [error_message]`
Adds input validation to a question using regex patterns.

#### `[p]campaign remove_question <campaign_id> <question_id>`
Removes a question from a campaign.

#### `[p]campaign list`
Lists all campaigns in the current server.

#### `[p]campaign view <campaign_id>`
Displays detailed information about a specific campaign.

#### `[p]campaign start <campaign_id> [duration]`
Starts a campaign with optional duration (e.g., 1d2h30m).

#### `[p]campaign stop <campaign_id>`
Stops an active campaign.

#### `[p]campaign delete <campaign_id>`
Permanently deletes a campaign and all associated data.

### Campaign Distribution

#### `[p]campaign send <campaign_id> [#channel]`
Sends the campaign message to a specified channel (or current channel if not specified).

#### `[p]campaign dm_all <campaign_id>`
Sends the campaign via DM to all server members (requires confirmation).

#### `[p]campaign dm_role <campaign_id> @role`
Sends the campaign via DM to all users with a specific role.

### User Interaction

#### `[p]campaign submit <campaign_id>`
Allows users to submit responses to an active campaign.

### Data Management

#### `[p]campaign export <campaign_id>`
Exports all campaign responses to a CSV file.

#### `[p]campaign stats <campaign_id>`
Displays campaign statistics including response rates and completion data.

#### `[p]campaign responses <campaign_id> [@user]`
Views responses for a campaign or a specific user.

## Usage Examples

### Creating a Simple Feedback Campaign

```
[p]campaign create "Server Feedback" "Help us improve our Discord server!"
# Returns: Campaign created with ID: abc12345

[p]campaign add_question abc12345 short_text "What do you like most about our server?"
[p]campaign add_question abc12345 long_text "What improvements would you suggest?"
[p]campaign add_choice_question abc12345 single_choice "How often do you visit our server?" "Daily" "Weekly" "Monthly" "Rarely"

[p]campaign start abc12345 7d
# Starts campaign for 7 days

[p]campaign send abc12345 #general
# Sends campaign to #general channel
```

### Adding Input Validation

```
[p]campaign add_question abc12345 short_text "What's your Discord username?"
[p]campaign add_validation abc12345 def67890 "^[a-zA-Z0-9_]{2,32}$" "Please enter a valid Discord username (2-32 characters, letters, numbers, and underscores only)"
```

### Exporting Data

```
[p]campaign export abc12345
# Generates and uploads a CSV file with all responses
```

## Technical Implementation

### Data Storage
The cog uses Red-Discordbot's built-in `config` system for persistent data storage. Data is organized as follows:

- **Campaigns**: Stored per guild with campaign configurations
- **Responses**: User responses linked to campaigns and users
- **Timers**: Active campaign timers for automatic expiration

### Discord UI Components
The cog leverages Discord's UI framework for interactive elements:

- **Views**: Persistent views with question buttons and submit functionality
- **Modals**: Pop-up forms for question responses
- **Buttons**: Interactive elements for question selection and submission

### Rate Limiting
The cog implements rate limiting for DM distribution to comply with Discord's API limits:
- 1-second delay between DMs
- Progress tracking for large distributions
- Error handling for failed DM attempts

## Configuration

### Permissions Required
- **Bot Permissions**: Send Messages, Use Slash Commands, Embed Links, Attach Files
- **User Permissions**: Manage Guild (for campaign management commands)

### Limitations
- Maximum 20 questions per campaign
- Maximum 25 buttons per Discord View (automatically handled)
- Maximum 10 options per choice question
- Text input limits: 100 characters (short), 1000 characters (long)

## Error Handling

The cog includes comprehensive error handling for:
- Invalid campaign IDs
- Permission errors
- Discord API rate limits
- Invalid input validation
- Campaign state conflicts (e.g., modifying active campaigns)

## Data Privacy and Security

- All data is stored locally using Red-Discordbot's config system
- User responses are linked to Discord user IDs
- Campaign creators can export and delete data as needed
- No external data transmission or storage

## Troubleshooting

### Common Issues

1. **Campaign not found**: Ensure the campaign ID is correct and the campaign exists in the current server
2. **Permission denied**: Verify the user has `manage_guild` permission
3. **DM failures**: Users may have DMs disabled or have blocked the bot
4. **View timeouts**: Discord Views may timeout; users can use the submit command directly

### Support

For technical support or bug reports, refer to the Red-Discordbot community resources or the cog's source code for debugging information.

## Version Information

- **Minimum Red Version**: 3.5.0
- **Minimum Python Version**: 3.8.0
- **Dependencies**: None (uses only Red-Discordbot built-in modules)

This documentation provides a comprehensive guide to using the Campaign Cog effectively for collecting user feedback in Discord servers.

