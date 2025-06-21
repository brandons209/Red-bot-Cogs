import re
from typing import Dict, Optional, Any

import discord


class CampaignView(discord.ui.View):
    """Discord View for campaign interaction with question buttons."""

    def __init__(self, campaign, cog):
        super().__init__(timeout=None)  # Persistent view
        self.campaign = campaign
        self.cog = cog

        # Add buttons for each question (max 25 buttons per view)
        for i, question in enumerate(campaign.questions[:25]):
            button = QuestionButton(
                question=question,
                campaign=campaign,
                cog=cog,
                label=f"Q{i+1}",
                style=discord.ButtonStyle.primary,
                row=i // 5,  # 5 buttons per row
            )
            self.add_item(button)

        # Add submit button
        if campaign.questions:
            submit_button = SubmitResponseButton(
                campaign=campaign, cog=cog, label="Submit Response", style=discord.ButtonStyle.success, row=4
            )
            self.add_item(submit_button)


class QuestionButton(discord.ui.Button):
    """Button for individual questions."""

    def __init__(self, question: Dict[str, Any], campaign, cog, **kwargs):
        super().__init__(**kwargs)
        self.question = question
        self.campaign = campaign
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle question button click."""
        # Check if campaign is still active
        if not self.campaign.active or self.campaign.is_expired():
            await interaction.response.send_message(
                "This campaign is no longer active.", ephemeral=True, delete_after=10
            )
            return

        # Get user's current response data
        user_response = await self.cog.get_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
        )

        current_answers = user_response.get("answers", {}) if user_response else {}
        current_answer = current_answers.get(self.question["question_id"], "")

        if self.question["type"] in ["short_text", "number"]:
            view = TextQuestionView(
                question=self.question,
                campaign=self.campaign,
                cog=self.cog,
                current_answer=current_answer,
                short=True,
            )
            await interaction.response.send_message(content=self.question["text"], view=view, ephemeral=True)

        elif self.question["type"] == "long_text":
            view = TextQuestionView(
                question=self.question,
                campaign=self.campaign,
                cog=self.cog,
                current_answer=current_answer,
                short=False,
            )
            await interaction.response.send_message(content=self.question["text"], view=view, ephemeral=True)
        elif self.question["type"] in ["multiple_choice", "single_choice"]:
            # For choice questions, we'll use a select menu in the modal
            modal = ChoiceView(
                question=self.question,
                campaign=self.campaign,
                cog=self.cog,
                current_answer=current_answer,
            )
            await interaction.response.send_message(content=self.question["text"], view=modal, ephemeral=True)
        else:
            await interaction.response.send_message("Unsupported question type.", ephemeral=True, delete_after=10)
            return


class SubmitResponseButton(discord.ui.Button):
    """Button to submit the complete response."""

    def __init__(self, campaign, cog, **kwargs):
        super().__init__(**kwargs)
        self.campaign = campaign
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle submit button click."""
        # Check if campaign is still active
        if not self.campaign.active or self.campaign.is_expired():
            await interaction.response.send_message(
                "This campaign is no longer active.", ephemeral=True, delete_after=10
            )
            return

        # Get user's current response data
        user_response = await self.cog.get_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
        )

        if not user_response:
            await interaction.response.send_message(
                "You haven't answered any questions yet. Please answer at least one question before submitting.",
                ephemeral=True,
                delete_after=10,
            )
            return

        current_answers = user_response.get("answers", {})

        # Check which questions are answered
        answered_questions = []
        unanswered_questions = []

        for question in self.campaign.questions:
            if question["question_id"] in current_answers:
                answered_questions.append(question)
            else:
                unanswered_questions.append(question)

        # Create confirmation embed
        embed = discord.Embed(
            title="Confirm Submission", description=f"Campaign: **{self.campaign.name}**", color=discord.Color.blue()
        )

        embed.add_field(
            name="Answered Questions", value=f"{len(answered_questions)}/{len(self.campaign.questions)}", inline=True
        )

        if unanswered_questions:
            unanswered_list = "\n".join(
                [
                    f"• {q['text'][:50]}..." if len(q["text"]) > 50 else f"• {q['text']}"
                    for q in unanswered_questions[:5]
                ]
            )
            if len(unanswered_questions) > 5:
                unanswered_list += f"\n... and {len(unanswered_questions) - 5} more"

            embed.add_field(name="Unanswered Questions", value=unanswered_list, inline=False)
            embed.add_field(
                name="Note",
                value="You can submit with unanswered questions, and can resubmit if you want to change your answers before the campaign ends.",
                inline=False,
            )

        # Create confirmation view
        confirm_view = SubmitConfirmationView(campaign=self.campaign, cog=self.cog, user_id=interaction.user.id)

        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)


class SubmitConfirmationView(discord.ui.View):
    """View for confirming response submission."""

    def __init__(self, campaign, cog, user_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.campaign = campaign
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="Confirm Submission", style=discord.ButtonStyle.success)
    async def confirm_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm and finalize the submission."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your submission.", ephemeral=True, delete_after=10)
            return

        # Get current answers
        user_response = await self.cog.get_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
        )

        if not user_response:
            await interaction.response.send_message("No response data found.", ephemeral=True, delete_after=10)
            return

        # Mark as submitted (we can add a submitted flag to the response data)
        current_answers = user_response.get("answers", {})

        # Save the final submission
        await self.cog.save_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
            current_answers,
        )

        embed = discord.Embed(
            title="Response Submitted!",
            description=f"Your response to '{self.campaign.name}' has been successfully submitted.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Questions Answered", value=f"{len(current_answers)}/{len(self.campaign.questions)}", inline=True
        )

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the submission."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your submission.", ephemeral=True, delete_after=10)
            return

        embed = discord.Embed(
            title="Submission Cancelled",
            description="You can continue editing your answers and submit later.",
            color=discord.Color.orange(),
        )

        await interaction.response.edit_message(embed=embed, view=None)


class TextQuestionView(discord.ui.View):
    """Sends the question as a message and provides a single ‘Answer’ button."""

    def __init__(
        self,
        question: Dict[str, Any],
        campaign: Any,
        cog: Any,
        current_answer: str = "",
        short: bool = True,
    ):
        super().__init__(timeout=None)
        self.question = question
        self.campaign = campaign
        self.cog = cog
        self.current_answer = current_answer
        self.short = short  # True=short/number, False=long

    @discord.ui.button(label="Answer", style=discord.ButtonStyle.primary)
    async def answer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Build and show a generic‐titled modal
        if self.short:
            modal = GenericTextModal(
                question=self.question,
                campaign=self.campaign,
                cog=self.cog,
                current_answer=self.current_answer,
                short=True,
            )
        else:
            modal = GenericTextModal(
                question=self.question,
                campaign=self.campaign,
                cog=self.cog,
                current_answer=self.current_answer,
                short=False,
            )

        await interaction.response.send_modal(modal)
        self.stop()


class GenericTextModal(discord.ui.Modal):
    """Modal with a generic title—question shown outside in the message."""

    def __init__(
        self,
        question: Dict[str, Any],
        campaign: Any,
        cog: Any,
        current_answer: str = "",
        short: bool = True,
    ):
        super().__init__(title="Your Answer")  # generic, no length issues
        self.question = question
        self.campaign = campaign
        self.cog = cog

        # decide placeholder, length, style
        if short and question["type"] == "number":
            placeholder = "Enter a number..."
            max_length = 20
            style = discord.TextStyle.short
        elif short:
            placeholder = "Enter your answer..."
            max_length = 100
            style = discord.TextStyle.short
        else:
            placeholder = "Enter your detailed answer..."
            max_length = 1000
            style = discord.TextStyle.long

        # label is generic too
        self.answer_input = discord.ui.TextInput(
            label="Answer",
            placeholder=placeholder,
            default=current_answer,
            max_length=max_length,
            style=style,
        )
        self.add_item(self.answer_input)

    async def on_submit(self, interaction: discord.Interaction):
        answer = self.answer_input.value.strip()

        # validate
        error = self._validate(answer)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True, delete_after=20)
            return

        # save
        await self._save(interaction, answer)

        # confirm
        await interaction.response.send_message(
            f"✅ Answer saved for:\n{self.question['text']}", ephemeral=True, delete_after=10
        )

    def _validate(self, answer: str) -> Optional[str]:
        if not answer:
            return "Answer cannot be empty."

        # number?
        if self.question["type"] == "number":
            try:
                float(answer)
            except ValueError:
                return "Please enter a valid number."

        # any regex
        if self.question.get("validation_regex"):
            try:
                if not re.match(self.question["validation_regex"], answer):
                    return self.question.get("validation_error_message", "Input format is invalid.")
            except re.error:
                return "Validation pattern error; contact an admin."
        return None

    async def _save(self, interaction: discord.Interaction, answer: str):
        user_response = await self.cog.get_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
        )
        current = user_response.get("answers", {}) if user_response else {}
        current[self.question["question_id"]] = answer

        await self.cog.save_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
            current,
        )


class ChoiceView(discord.ui.View):
    """View for single- or multiple-choice questions via a dropdown."""

    def __init__(
        self,
        question: Dict[str, Any],
        campaign: Any,
        cog: Any,
        current_answer: Optional[str] = None,
    ):
        super().__init__(timeout=None)
        self.question = question
        self.campaign = campaign
        self.cog = cog

        # Build SelectOption list
        options = [
            discord.SelectOption(label=option, description=None, value=str(i + 1))
            for i, option in enumerate(question["options"])
        ]

        # Configure select for single vs multiple choice
        if question["type"] == "multiple_choice":
            min_vals, max_vals = 1, len(options)
            placeholder = "Choose one or more options..."
        else:
            min_vals, max_vals = 1, 1
            placeholder = "Choose an option..."

        select = discord.ui.Select(
            placeholder=placeholder,
            min_values=min_vals,
            max_values=max_vals,
            options=options,
            custom_id="choice_select",
        )
        select.callback = self.on_select
        self.add_item(select)

        # Optionally pre-select existing answer
        if current_answer:
            # current_answer is the readable text; map back to indices
            selected = []
            for idx, opt in enumerate(question["options"], start=1):
                if str(opt) in current_answer:
                    selected.append(str(idx))
            select.default_values = selected

    async def on_select(self, interaction: discord.Interaction):
        # interaction.data["values"] is a list of the selected .value strings
        chosen_indices = [int(v) for v in interaction.data["values"]]
        # Convert to the option labels
        selected_labels = [self.question["options"][i - 1] for i in chosen_indices]
        readable_answer = "; ".join(selected_labels)

        # Save it
        await self._save_answer(interaction, readable_answer)

        await interaction.response.send_message(f"✅ Answer saved: {readable_answer}", ephemeral=True, delete_after=10)
        # Disable further input
        self.stop()

    async def _save_answer(self, interaction: discord.Interaction, answer: str):
        """Fetches or creates the user response and updates it."""
        user_response = await self.cog.get_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
        )

        current_answers = (user_response or {}).get("answers", {})
        current_answers[self.question["question_id"]] = answer

        await self.cog.save_user_response(
            self.campaign.guild_id,
            self.campaign.campaign_id,
            interaction.user.id,
            current_answers,
        )
