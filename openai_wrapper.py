# openai_wrapper.py
import openai


class OpenAIWrapper:
    def __init__(self, api_key: str):
        openai.api_key = api_key

    @staticmethod
    def chat_completion(model: str, messages: list, max_tokens: int):
        return openai.ChatCompletion.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens)
