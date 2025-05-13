from transformers import AutoTokenizer
from huggingface_hub import HfApi
import tiktoken

import re
from typing import Optional, List, Dict, Union


class GeneralAPI:
    def __init__(self, model: str, **model_options):
        self.model = model
        self.options = model_options
        self.reasoning_tags = [
            "think",
            "thinking",
            "analysis",
            "reasoning",
            "output",
            "premise",
            "inference",
            "evidence",
            "evaluation",
            "conclusion",
            "chain_of_thought",
        ]
        self.prefix_markers = [
            r"Thought:",
            r"Analysis:",
            r"Final Answer:",
        ]
        self.tokenizer = self._get_tokenizer()
        self._format_options()

    def _format_options(self):
        raise NotImplementedError

    def _get_tokenizer(self) -> Union[AutoTokenizer, None]:
        model = self.model.split(":")[0]
        # try to find huggingface model to get tokenizer
        api = HfApi()
        hits = list(api.list_models(filter=model, limit=10))
        for h in hits:
            model = h.modelId
            try:
                tok = AutoTokenizer.from_pretrained(model, use_fast=True)
                if tok.pad_token_id is None:
                    tok.pad_token_id = tok.eos_token_id
                # print(f"found tokenizer for {self.model}: {model}")
                return tok
            except Exception as e:
                pass
            # print(f"Error getting tokenizer: {e}")
            # try chatgpt tokenizer if a chatgpt model (will support in future)
        if re.match(r"^(gpt-|text-)", model):
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                # fallback if the model isn't known yet
                enc = tiktoken.get_encoding("cl100k_base")
            # print(f"found tokenizer for {self.model}: {model}")
            return enc
        return None

    def get_token_count(self, message: str) -> int:
        """
        Returns the number of tokens a message is, falling back to an estimation if the model's tokenizer can't be found.

        Args:
            message (str): The message to count tokens for

        Returns:
            int: Number of tokens in the message
        """
        if self.tokenizer:
            # hf model
            try:
                return len(self.tokenizer.encode(message, add_special_tokens=True))
            except:
                return len(self.tokenizer.encode(message))

        # estimate tokens if no tokenizer loaded
        # collapse whitespace
        s = re.sub(r"\s+", " ", message).strip()
        if not s:
            return 0

        # Rule 1: characters → tokens
        char_tokens = len(s) / 4.0

        # Rule 2: words → tokens
        word_count = len(s.split(" "))
        word_tokens = word_count / 0.75

        # Return the higher estimate, rounded up
        return int(max(char_tokens, word_tokens) + 0.5)

    async def get_model_response(
        self,
        prompt: str,
        user_query: str,
        stop: Optional[List[str]] = None,
        stats: Optional[Dict[str, Union[int, float]]] = None,
    ):
        raise NotImplementedError
