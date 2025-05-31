from discord import ui, TextStyle, Interaction, ButtonStyle, Message
from typing import Optional
import asyncio


async def set_config(cog, model_type: str, new_config: dict):
    if model_type == "chatbot":
        await cog.config.chatbot_model_config.set(new_config)
    elif model_type == "summarize":
        await cog.config.summarize_model_config.set(new_config)
    elif model_type == "general":
        await cog.config.general_model_config.set(new_config)


async def get_config(cog, model_type: str):
    if model_type == "chatbot":
        return await cog.config.chatbot_model_config()
    elif model_type == "summarize":
        return await cog.config.summarize_model_config()
    elif model_type == "general":
        return await cog.config.general_model_config()


class EndChatVote(ui.View):
    def __init__(self, timeout: int, message: Optional[Message] = None):
        super().__init__(timeout=timeout)
        self.message = message
        self.yes = []
        self.no = []
        self.winner = "no"

    def end(self):
        if len(self.yes) > len(self.no):
            self.winner = "yes"
        elif len(self.yes) < len(self.no):
            self.winner = "no"
        else:
            self.winner = "no"

        self.stop()

    @ui.button(label="Yes", style=ButtonStyle.primary)
    async def yes_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id in self.yes:
            await interaction.response.send_message("You already voted for this!", ephemeral=True, delete_after=10)
        else:
            self.yes.append(interaction.user.id)
            await interaction.response.send_message(
                "You have voted to remove the bot from the conversation.",
                ephemeral=True,
                delete_after=10,
            )
            if interaction.user.id in self.no:
                self.no.remove(interaction.user.id)

    @ui.button(label="No", style=ButtonStyle.secondary)
    async def no_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id in self.no:
            await interaction.response.send_message("You already voted for this!", ephemeral=True, delete_after=10)
        else:
            self.no.append(interaction.user.id)
            await interaction.response.send_message(
                "You have voted to keep the bot from the conversation.",
                ephemeral=True,
                delete_after=10,
            )
            if interaction.user.id in self.yes:
                self.yes.remove(interaction.user.id)


class OllamaConfigModal1(ui.Modal, title="Configure Ollama Model -- Page 1"):
    def __init__(self, cog, model_type: str, config: dict, message: Message):
        super().__init__()  # finish Modal setup
        # Build each TextInput with default from config (or placeholder)
        self.base_url = ui.TextInput(
            label="Base URL",
            placeholder="https://localhost:11434",
            default=config.get("base_url", "https://localhost:11434"),
            required=True,
        )
        self.model = ui.TextInput(
            label="Model Name",
            placeholder="llama2",
            default=config.get("model", "llama2"),
            required=True,
        )
        self.temperature = ui.TextInput(
            label="Temperature",
            placeholder="0.7",
            default=str(config.get("temperature", "0.7")),
            required=True,
        )
        self.top_p = ui.TextInput(
            label="Top P",
            placeholder="0.9",
            default=str(config.get("top_p", "0.9")),
            required=True,
        )
        self.min_p = ui.TextInput(
            label="Min P",
            placeholder="0.0",
            default=str(config.get("min_p", "0.0")),
            required=True,
        )

        self.add_item(self.base_url)
        self.add_item(self.model)
        self.add_item(self.temperature)
        self.add_item(self.top_p)
        self.add_item(self.min_p)

        self.config = config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    async def on_submit(self, interaction: Interaction):
        try:
            self.config = {
                "type": "ollama",
                "base_url": self.base_url.value,
                "model": self.model.value,
                "temperature": float(self.temperature.value),
                "top_p": float(self.top_p.value),
                "min_p": float(self.min_p.value),
                "top_k": self.config["top_k"],
                "num_ctx": self.config["num_ctx"],
                "num_predict": self.config["num_predict"],
                "repeat_penalty": self.config["repeat_penalty"],
                "presence_penalty": self.config["presence_penalty"],
                "reasoning_effort": self.config["reasoning_effort"],
                "keep_alive": self.config["keep_alive"],
            }
            await set_config(self.cog, self.model_type, self.config)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}",
                ephemeral=True,
                delete_after=60,
            )
            return
        await interaction.response.defer()


class OllamaConfigModal2(ui.Modal, title="Configure Ollama Model -- Page 2"):
    def __init__(self, cog, model_type: str, config: dict, message: Message):
        super().__init__()  # finish Modal setup
        # Build each TextInput with default from config (or placeholder)
        self.top_k = ui.TextInput(
            label="Top K", placeholder="40", default=str(config.get("top_k", "40")), required=True
        )
        self.num_ctx = ui.TextInput(
            label="Num Context",
            placeholder="512",
            default=str(config.get("num_ctx", "512")),
            required=True,
        )
        self.num_predict = ui.TextInput(
            label="Num Predict",
            placeholder="-1",
            default=str(config.get("num_predict", "-1")),
            required=True,
        )
        self.repeat_penalty = ui.TextInput(
            label="Repeat Penalty",
            placeholder="1.0",
            default=str(config.get("repeat_penalty", "1.0")),
            required=True,
        )
        self.presence_penalty = ui.TextInput(
            label="Presence Penalty",
            placeholder="1.0",
            default=str(config.get("presence_penalty", "1.0")),
            required=True,
        )

        self.add_item(self.top_k)
        self.add_item(self.num_ctx)
        self.add_item(self.num_predict)
        self.add_item(self.repeat_penalty)
        self.add_item(self.presence_penalty)

        self.config = config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    async def on_submit(self, interaction: Interaction):
        try:
            self.config = {
                "type": "ollama",
                "base_url": self.config["base_url"],
                "model": self.config["model"],
                "temperature": self.config["temperature"],
                "top_p": self.config["top_p"],
                "min_p": self.config["min_p"],
                "top_k": int(self.top_k.value),
                "num_ctx": int(self.num_ctx.value),
                "num_predict": int(self.num_predict.value),
                "repeat_penalty": float(self.repeat_penalty.value),
                "presence_penalty": float(self.presence_penalty.value),
                "reasoning_effort": self.config["reasoning_effort"],
                "keep_alive": self.config["keep_alive"],
            }
            await set_config(self.cog, self.model_type, self.config)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}",
                ephemeral=True,
                delete_after=60,
            )
            return
        await interaction.response.defer()


class OllamaConfigModal3(ui.Modal, title="Configure Ollama Model -- Page 3"):
    def __init__(self, cog, model_type: str, config: dict, message: Message):
        super().__init__()  # finish Modal setup
        # Build each TextInput with default from config (or placeholder)
        self.reasoning_effort = ui.TextInput(
            label="Reasoning Effort (low/medium/high)",
            placeholder="medium",
            default=config.get("reasoning_effort", "medium"),
            required=True,
        )
        self.keep_alive = ui.TextInput(
            label="Keep Alive (str or -1)",
            placeholder="-1",
            default=str(config.get("keep_alive", "-1")),
            required=True,
        )

        self.add_item(self.reasoning_effort)
        self.add_item(self.keep_alive)

        self.config = config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    async def on_submit(self, interaction: Interaction):
        try:
            self.config = {
                "type": "ollama",
                "base_url": self.config["base_url"],
                "model": self.config["model"],
                "temperature": self.config["temperature"],
                "top_p": self.config["top_p"],
                "min_p": self.config["min_p"],
                "top_k": self.config["top_k"],
                "num_ctx": self.config["num_ctx"],
                "num_predict": self.config["num_predict"],
                "repeat_penalty": self.config["repeat_penalty"],
                "presence_penalty": self.config["presence_penalty"],
                "reasoning_effort": self.reasoning_effort.value.lower(),
                "keep_alive": (
                    int(self.keep_alive.value) if self.keep_alive.value.isdigit() else self.keep_alive.value
                ),
            }
            await set_config(self.cog, self.model_type, self.config)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}",
                ephemeral=True,
                delete_after=60,
            )
            return
        await interaction.response.defer()


class OpenAIConfigModal1(ui.Modal, title="Configure OpenAI Model"):

    def __init__(self, cog, model_type: str, config: dict, message: Message):
        super().__init__()  # finish Modal setup
        self.base_url = ui.TextInput(
            label="Base URL (must end with /v1)",
            placeholder="https://api.openai.com/v1",
            default=config.get("base_url", "https://api.openai.com/v1"),
            required=True,
        )
        self.api_key = ui.TextInput(
            label="API Key",
            placeholder="sk-...",
            default=config.get("api_key", "sk-...."),
            required=True,
            style=TextStyle.short,
        )
        self.model = ui.TextInput(
            label="Model Name",
            placeholder="gpt-3.5-turbo",
            default=config.get("model", "gpt-3.5-turbo"),
            required=True,
        )
        self.temperature = ui.TextInput(
            label="Temperature",
            placeholder="0.7",
            default=str(config.get("temperature", "0.7")),
            required=True,
        )
        self.top_p = ui.TextInput(
            label="Top P", placeholder="0.9", default=str(config.get("top_p", "0.99")), required=True
        )

        self.add_item(self.base_url)
        self.add_item(self.api_key)
        self.add_item(self.model)
        self.add_item(self.temperature)
        self.add_item(self.top_p)

        self.config = config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    async def on_submit(self, interaction: Interaction):
        url = self.base_url.value
        if not url.endswith("/v1"):
            await interaction.response.send_message("Base URL must end with `/v1`.", ephemeral=True)
            return
        try:
            self.config = {
                "type": "openai",
                "base_url": url,
                "api_key": self.api_key.value,
                "model": self.model.value,
                "temperature": float(self.temperature.value),
                "top_p": float(self.top_p.value),
                "num_predict": self.config["num_predict"],
                "num_ctx": self.config["num_ctx"],
                "min_p": 0.0,
                "top_k": 64,
                "repeat_penalty": 1.0,
                "presence_penalty": 1.1,
                "reasoning_effort": "medium",
                "keep_alive": "5m",
            }
            await set_config(self.cog, self.model_type, self.config)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}",
                ephemeral=True,
                delete_after=60,
            )
            return
        await interaction.response.defer()


class OpenAIConfigModal2(ui.Modal, title="Configure OpenAI Model"):

    def __init__(self, cog, model_type: str, config: dict, message: Message):
        super().__init__()  # finish Modal setup
        self.num_predict = ui.TextInput(
            label="Num Predict",
            placeholder="256",
            default=str(config.get("num_predict", "256")),
            required=True,
        )
        self.num_ctx = ui.TextInput(
            label="Num Context",
            placeholder="4096",
            default=str(config.get("num_ctx", "4096")),
            required=True,
        )

        self.add_item(self.num_predict)
        self.add_item(self.num_ctx)

        self.config = config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    async def on_submit(self, interaction: Interaction):
        try:
            self.config = {
                "type": "openai",
                "base_url": self.config["base_url"],
                "api_key": self.config["api_key"],
                "model": self.config["model"],
                "temperature": self.config["temperature"],
                "top_p": self.config["top_p"],
                "num_predict": int(self.num_predict.value),
                "num_ctx": int(self.num_ctx.value),
                "min_p": 0.0,
                "top_k": 64,
                "repeat_penalty": 1.0,
                "presence_penalty": 1.1,
                "reasoning_effort": "medium",
                "keep_alive": "5m",
            }
            await set_config(self.cog, self.model_type, self.config)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid input: {e}",
                ephemeral=True,
                delete_after=60,
            )
            return

        await interaction.response.defer()


class ConfigMenuView(ui.View):

    def __init__(self, api_type: str, model_type: str, existing_config: dict, cog, message: Optional[Message] = None):
        super().__init__(timeout=240)
        self.existing_config = existing_config
        self.cog = cog
        self.model_type = model_type
        self.message = message

        ollama = [self.ollama_button1, self.ollama_button2, self.ollama_button3]
        openai = [self.openai_button1, self.openai_button2]

        if api_type == "ollama":
            for button in openai:
                self.remove_item(button)
            for button in ollama:
                button.row = 0
            self.done_button.row = 0
        else:
            for button in ollama:
                self.remove_item(button)
            for button in openai:
                button.row = 0
            self.done_button.row = 0

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    @ui.button(label="Page 1", style=ButtonStyle.primary, custom_id="config_ollama1")
    async def ollama_button1(self, interaction: Interaction, button: ui.Button):
        self.existing_config = await get_config(self.cog, self.model_type)
        await interaction.response.send_modal(
            OllamaConfigModal1(
                self.cog,
                self.model_type,
                self.existing_config,
                self.message,
            )
        )

    @ui.button(label="Page 2", style=ButtonStyle.primary, custom_id="config_ollama2")
    async def ollama_button2(self, interaction: Interaction, button: ui.Button):
        self.existing_config = await get_config(self.cog, self.model_type)
        await interaction.response.send_modal(
            OllamaConfigModal2(
                self.cog,
                self.model_type,
                self.existing_config,
                self.message,
            )
        )

    @ui.button(label="Page 3", style=ButtonStyle.primary, custom_id="config_ollama3")
    async def ollama_button3(self, interaction: Interaction, button: ui.Button):
        self.existing_config = await get_config(self.cog, self.model_type)
        await interaction.response.send_modal(
            OllamaConfigModal3(
                self.cog,
                self.model_type,
                self.existing_config,
                self.message,
            )
        )

    @ui.button(label="Page 1", style=ButtonStyle.primary, custom_id="config_openai1")
    async def openai_button1(self, interaction: Interaction, button: ui.Button):
        self.existing_config = await get_config(self.cog, self.model_type)
        await interaction.response.send_modal(
            OpenAIConfigModal1(
                self.cog,
                self.model_type,
                self.existing_config,
                self.message,
            )
        )

    @ui.button(label="Page 2", style=ButtonStyle.primary, custom_id="config_openai2")
    async def openai_button2(self, interaction: Interaction, button: ui.Button):
        self.existing_config = await get_config(self.cog, self.model_type)
        await interaction.response.send_modal(
            OpenAIConfigModal2(
                self.cog,
                self.model_type,
                self.existing_config,
                self.message,
            )
        )

    @ui.button(label="Done", style=ButtonStyle.primary, custom_id="done")
    async def done_button(self, interaction: Interaction, button: ui.Button):
        try:
            await self.message.delete()
        except:
            pass
        await interaction.response.send_message(
            "✅ Configuration saved.",
            ephemeral=True,
            delete_after=60,
        )
        await asyncio.sleep(60)
        await interaction.delete_original_response()
        self.stop()


class ConfirmSwitchView(ui.View):
    def __init__(self, current_type: str, target: str, existing_config: dict, cog, model_type: str, message: Message):
        super().__init__(timeout=30)
        self.current = current_type
        self.target = target
        self.existing_config = existing_config
        self.cog = cog
        self.model_type = model_type
        self.message = message

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    @ui.button(label="Yes, switch", style=ButtonStyle.danger)
    async def yes(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message(
            view=ConfigMenuView(
                self.target,
                self.model_type,
                self.existing_config,
                self.cog,
                self.message,
            )
        )

    @ui.button(label="No, keep current", style=ButtonStyle.secondary)
    async def no(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message(
            f"👍 Keeping your current `{self.current}` configuration.",
            ephemeral=True,
            delete_after=60,
        )
        self.stop()


class ConfigSelectView(ui.View):
    def __init__(self, cog, model_type: str, existing_config: dict):
        super().__init__(timeout=60)
        self.existing_config = existing_config
        self.cog = cog
        self.model_type = model_type
        self.message: Message = None

    async def on_timeout(self) -> None:
        try:
            await self.message.delete()
        except:
            pass
        finally:
            await super().on_timeout()

    @ui.button(label="Configure Ollama", style=ButtonStyle.primary, custom_id="config_ollama")
    async def ollama_button(self, interaction: Interaction, button: ui.Button):
        curr = self.existing_config.get("type")
        # If switching from OpenAI → Ollama
        if curr and curr != "ollama":
            return await interaction.response.send_message(
                f"❓ You currently have `{curr}` configured. Switch to `ollama`?",
                view=ConfirmSwitchView(curr, "ollama", self.existing_config, self.cog, self.model_type, self.message),
                ephemeral=True,
                delete_after=60,
            )
        # Otherwise just open the Ollama modal
        await interaction.response.send_message(
            view=ConfigMenuView(
                curr,
                self.model_type,
                self.existing_config,
                self.cog,
                self.message,
            )
        )

    @ui.button(label="Configure OpenAI", style=ButtonStyle.primary, custom_id="config_openai")
    async def openai_button(self, interaction: Interaction, button: ui.Button):
        curr = self.existing_config.get("type")
        # If switching from Ollama → OpenAI
        if curr and curr != "openai":
            return await interaction.response.send_message(
                f"❓ You currently have `{curr}` configured. Switch to `openai`?",
                view=ConfirmSwitchView(
                    curr,
                    "openai",
                    self.existing_config,
                    self.cog,
                    self.model_type,
                    self.message,
                ),
                ephemeral=True,
            )
        await interaction.response.send_message(
            view=ConfigMenuView(
                curr,
                self.model_type,
                self.existing_config,
                self.cog,
                self.message,
            )
        )
