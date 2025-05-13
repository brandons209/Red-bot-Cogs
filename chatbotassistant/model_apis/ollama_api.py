from ollama import ChatResponse, Client
from .api import GeneralAPI

from typing import Optional, List, Dict, Union
import asyncio, re, time


class OllamaModel(GeneralAPI):
    def __init__(self, ollama_ip: str, model: str, keep_alive: int = 300, **model_options):
        super().__init__(model, **model_options)
        self.client = Client(ollama_ip)
        self.options = model_options
        self.keep_alive = keep_alive

    def _format_options(self):
        options = self.options
        # delete unneeded keys
        del options["type"]
        del options["api_key"]
        self.options = options

    async def get_model_response(
        self,
        prompt: str,
        user_query: str,
        stop: Optional[List[str]] = None,
        stats: Optional[Dict[str, Union[int, float]]] = None,
    ):
        input = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_query},
        ]
        if stop:
            options = self.options.copy()
            options["stop"] = stop
        else:
            options = self.options

        start = time.time()
        response: ChatResponse = await asyncio.to_thread(
            self.client.chat,
            self.model,
            messages=input,
            options=options,
            stream=False,
            keep_alive=self.keep_alive,
        )
        # print("raw_response", response)
        end = time.time() - start
        # update stats if provided
        if stats is not None:
            stats["num_responses"] += 1
            stats["total_response_time"] += end
            stats["prompt_eval_count"] += response["prompt_eval_count"]
            stats["prompt_eval_duration"] += response["prompt_eval_duration"] * 1e-9
        text = response.message.content or ""

        # Extract all XML‐style reasoning blocks
        tag_pattern = re.compile(rf"<({'|'.join(self.reasoning_tags)})>(.*?)</\1>", flags=re.DOTALL | re.IGNORECASE)
        tagged_matches = tag_pattern.findall(text)
        # dict[tag] = [list of blocks]
        tagged: Dict[str, List[str]] = {}
        for tag, block in tagged_matches:
            tagged.setdefault(tag.lower(), []).append(block.strip())

        # remove them from the text
        without_tags = tag_pattern.sub("", text)

        # 2) Extract any prefix‐based reasoning
        prefix_blocks: List[str] = []
        for marker in self.prefix_markers:
            # capture marker up to either next marker or end
            p = re.compile(
                rf"{marker}\s*(.*?)(?=(?:\n(?:{'|'.join(self.prefix_markers)})|$))", flags=re.DOTALL | re.IGNORECASE
            )
            for m in p.finditer(without_tags):
                prefix_blocks.append(m.group(1).strip())
            without_tags = p.sub("", without_tags)

        # 3) Whatever remains is the final answer
        answer = without_tags.strip()

        return answer
