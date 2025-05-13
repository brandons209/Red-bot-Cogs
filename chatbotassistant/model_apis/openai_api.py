from openai import OpenAI
from .api import GeneralAPI
from typing import Optional, List, Dict, Union
import time


class OpenAIModel(GeneralAPI):
    def __init__(self, base_url: str, model: str, api_key: str, **model_options):
        super().__init__(model, **model_options)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _format_options(self):
        options = self.options
        # delete unneeded keys
        del options["type"]
        del options["keep_alive"]
        del options["repeat_penalty"]
        del options["presence_penalty"]
        del options["num_ctx"]
        del options["min_p"]
        del options["top_k"]

        # rename and format keys
        options["max_output_tokens"] = options["num_predict"]
        if options["max_output_tokens"] < 0:
            options["max_output_tokens"] = None
        del options["num_predict"]

        # TODO: need to check this param based on model, or in config menu have this set to None
        options["reasoning"] = None  # {"effort": options["reasoning_effort"]}
        del options["reasoning_effort"]

        self.options = options

    async def get_model_response(
        self,
        prompt: str,
        user_query: str,
        stop: Optional[List[str]] = None,
        stats: Optional[Dict[str, Union[int, float]]] = None,
    ):
        start = time.time()
        response = self.client.responses.create(model=self.model, instructions=prompt, input=user_query, **self.options)
        end = time.time() - start
        if stats is not None:
            stats["num_responses"] += 1
            stats["total_response_time"] += end

        output = response.output
        return output[0].content[0].text
