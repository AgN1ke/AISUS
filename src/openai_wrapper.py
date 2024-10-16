# openai_wrapper.py
from openai import OpenAI


class OpenAIWrapper:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat_completion(self, model: str, messages: list, max_tokens: int):
        client = OpenAI(api_key=self.api_key)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens)
