# openai_wrapper.py
import os
import asyncio
from openai import OpenAI
from openai import (
    OpenAIError,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
    BadRequestError,
    AuthenticationError,
)
from agents import Agent, Runner, FileSearchTool, WebSearchTool
import base64
from datetime import datetime


class OpenAIWrapper:
    def __init__(
        self,
        api_key: str,
        api_mode: str = "responses",
        reasoning_effort: str | None = None,
        search_enabled: bool = False,
        web_search_enabled: bool = False,
        whisper_model: str | None = None,
        tts_model: str | None = None,
    ):
        self.client = OpenAI(api_key=api_key)
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort
        self.search_enabled = search_enabled
        self.web_search_enabled = web_search_enabled
        self.chat_vector_stores: dict[int, str] = {}
        self.whisper_model = whisper_model
        self.tts_model = tts_model

    @staticmethod
    def _messages_to_input(messages):
        items = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, str):
                items.append({"role": role, "content": [{"type": "input_text", "text": content}]})
            elif isinstance(content, list):
                items.append({"role": role, "content": content})
            else:
                items.append({"role": role, "content": [{"type": "input_text", "text": str(content)}]})
        return items

    def restore_vector_stores(self, name_prefix="tg-chat-"):
        restored = 0
        cursor = None
        while True:
            page = self.client.vector_stores.list(after=cursor) if cursor else self.client.vector_stores.list()
            for store in page.data:
                name = getattr(store, "name", "") or ""
                if name.startswith(name_prefix):
                    try:
                        chat_id = int(name[len(name_prefix):])
                        self.chat_vector_stores[chat_id] = store.id
                        restored += 1
                    except ValueError:
                        pass
            if not getattr(page, "has_more", False):
                break
            cursor = getattr(page, "last_id", None)
            if not cursor:
                break
        return restored

    def ensure_vector_store(self, chat_id):
        vs_id = self.chat_vector_stores.get(chat_id)
        if vs_id:
            return vs_id
        vs = self.client.vector_stores.create(name=f"tg-chat-{chat_id}")
        self.chat_vector_stores[chat_id] = vs.id
        return vs.id

    def upload_file_to_chat(self, chat_id, file_path):
        vs_id = self.ensure_vector_store(chat_id)
        try:
            with open(file_path, "rb") as fh:
                f = self.client.files.create(file=fh, purpose="assistants")
            self.client.vector_stores.files.create(vector_store_id=vs_id, file_id=f.id)
            return f.id, vs_id
        except (OpenAIError, OSError, BadRequestError, AuthenticationError):
            return None, vs_id

    async def generate(self, model, messages, max_tokens, chat_id=None, extra_overrides=None):
        vector_store_id = self.chat_vector_stores.get(chat_id) if chat_id is not None else None

        if self.api_mode == "agents":
            include_results = bool(extra_overrides.get("citations", {}).get("enabled")) if extra_overrides else False
            tools = []
            if self.search_enabled and vector_store_id:
                tools.append(
                    FileSearchTool(
                        vector_store_ids=[vector_store_id],
                        include_search_results=include_results
                    )
                )
            if self.web_search_enabled:
                tools.append(WebSearchTool())

            system_text = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
            user_messages = [m for m in messages if m.get("role") != "system"]
            return await Runner.run(
                Agent(name="TG Assistant", instructions=system_text, tools=tools, model=model),
                user_messages,
            )

        payload = {
            "model": model,
            "input": self._messages_to_input(messages),
            "max_output_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        try:
            return await asyncio.to_thread(self.client.responses.create, **payload)
        except (APIConnectionError, APIStatusError, RateLimitError, BadRequestError, AuthenticationError, OpenAIError):
            return None

    @staticmethod
    def _get_text_from_final_output(resp):
        fo = getattr(resp, "final_output", None)
        return "" if fo is None else str(fo)

    def _walk_nodes(self, node, depth=0):
        if depth > 6 or node is None:
            return
        yield node
        if isinstance(node, (list, tuple, set)):
            for it in node:
                yield from self._walk_nodes(it, depth + 1)
        elif isinstance(node, dict):
            for v in node.values():
                yield from self._walk_nodes(v, depth + 1)
        else:
            d = getattr(node, "__dict__", None)
            if d:
                for v in d.values():
                    yield from self._walk_nodes(v, depth + 1)

    @staticmethod
    def used_file_search(resp):
        ni = getattr(resp, "new_items", None)
        if ni and hasattr(ni, "__iter__"):
            for it in ni:
                raw = getattr(it, "raw_item", None)
                if getattr(raw, "type", None) == "file_search_call":
                    return True
        rr = getattr(resp, "raw_responses", None)
        if rr and hasattr(rr, "__iter__"):
            try:
                out = rr[0].output
                if out and hasattr(out, "__iter__"):
                    for part in out:
                        if getattr(part, "type", None) == "file_search_call":
                            return True
            except (AttributeError, IndexError, TypeError):
                pass
        return False

    @staticmethod
    def used_web_search(resp):
        ni = getattr(resp, "new_items", None)
        if ni and hasattr(ni, "__iter__"):
            for it in ni:
                raw = getattr(it, "raw_item", None)
                if getattr(raw, "type", None) == "web_search_call":
                    return True
        rr = getattr(resp, "raw_responses", None)
        if rr and hasattr(rr, "__iter__"):
            try:
                out = rr[0].output
                if out and hasattr(out, "__iter__"):
                    for part in out:
                        if getattr(part, "type", None) in {"web_search_call", "tool_call"} and \
                                getattr(part, "name", None) in {"web_search_preview", "web_search"}:
                            return True
            except Exception:
                pass
        return False

    @staticmethod
    def extract_text(response):
        if response is None:
            return ""
        if hasattr(response, "final_output"):
            return "" if getattr(response, "final_output", None) is None else str(response.final_output)
        if getattr(response, "output_text", None):
            return response.output_text
        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            return ""

    @staticmethod
    def extract_usage(response):
        def to_int(x):
            try:
                return int(x)
            except Exception:
                return 0

        if response is None:
            return 0, 0

        cw = getattr(response, "context_wrapper", None)
        u = getattr(cw, "usage", None) if cw else None
        if u:
            return to_int(getattr(u, "input_tokens", 0)), to_int(getattr(u, "output_tokens", 0))

        rr = getattr(response, "raw_responses", None)
        if rr and hasattr(rr, "__iter__"):
            try:
                ti = sum(to_int(getattr(getattr(r, "usage", None), "input_tokens", 0)) for r in rr)
                to = sum(to_int(getattr(getattr(r, "usage", None), "output_tokens", 0)) for r in rr)
                if ti or to:
                    return ti, to
            except (AttributeError, TypeError):
                pass

        u = getattr(response, "usage", None)
        if u:
            ti = to_int(getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0))
            to = to_int(getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0))
            return ti, to

        ti = to_int(getattr(getattr(response, "usage", None), "input_tokens", 0))
        to = to_int(getattr(getattr(response, "usage", None), "output_tokens", 0))
        return ti, to

    def remove_file_from_chat(self, chat_id, file_id):
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return False
        try:
            self.client.vector_stores.files.delete(vector_store_id=vs_id, file_id=file_id)
        except (APIConnectionError, APIStatusError, RateLimitError, OpenAIError):
            return False
        try:
            self.client.files.delete(file_id)
        except (APIConnectionError, APIStatusError, RateLimitError, OpenAIError):
            pass
        return True

    def clear_files_in_chat(self, chat_id):
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return False
        try:
            self.client.vector_stores.delete(vs_id)
            self.chat_vector_stores.pop(chat_id, None)
            return True
        except (APIConnectionError, APIStatusError, RateLimitError, OpenAIError, OSError):
            return False

    def list_files_in_chat(self, chat_id):
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return []
        try:
            items = self.client.vector_stores.files.list(vector_store_id=vs_id).data
            out = []
            for it in items:
                f = self.client.files.retrieve(it.id)
                name = getattr(f, "filename", None) or getattr(f, "display_name", None) or getattr(f, "name",
                                                                                                   None) or "?"
                out.append({"id": it.id, "filename": name})
            return out
        except (APIConnectionError, APIStatusError, RateLimitError, OpenAIError):
            return []

    async def analyze_image(self, image_path, prompt="What's in this image?", model="gpt-4o-mini", max_tokens=300):
        with open(image_path, "rb") as fh:
            base64_image = base64.b64encode(fh.read()).decode("utf-8")
        payload = {
            "model": model,
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{base64_image}"}
                ]
            }],
            "max_output_tokens": max_tokens
        }
        try:
            resp = await asyncio.to_thread(self.client.responses.create, **payload)
        except (APIConnectionError, APIStatusError, RateLimitError, BadRequestError, AuthenticationError, OpenAIError):
            return ""
        return self.extract_text(resp)

    def transcribe_voice_message(self, voice_message_path):
        with open(voice_message_path, "rb") as audio_file:
            r = self.client.audio.transcriptions.create(model=self.whisper_model, file=audio_file)
        return r.text

    def generate_voice_response_and_save_file(self, text, voice, folder_path):
        if not folder_path or not os.path.isdir(folder_path):
            folder_path = os.getcwd()
        r = self.client.audio.speech.create(model=self.tts_model, voice=voice, input=text)
        file_name = os.path.join(folder_path, f"response_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3")
        with open(file_name, "wb") as f:
            f.write(r.read())
        return file_name