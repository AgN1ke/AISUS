# openai_wrapper.py
from openai import OpenAI


class OpenAIWrapper:
    def __init__(self, api_key: str, api_mode: str = "responses", reasoning_effort: str | None = None):
        self.client = OpenAI(api_key=api_key)
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort

    def generate(self, model: str, messages: list, max_tokens: int):
        if self.api_mode == "responses":
            if self.reasoning_effort:
                kwargs = {
                    "model": model,
                    "input": messages,
                    "max_output_tokens": max_tokens,
                    "reasoning": {"effort": self.reasoning_effort}
                }
            else:
                kwargs = {
                    "model": model,
                    "input": messages,
                    "max_output_tokens": max_tokens
                }
            return self.client.responses.create(**kwargs)

        return self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens)

    @staticmethod
    def extract_text(response):
        return getattr(response, "output_text", None) or response.choices[0].message.content
