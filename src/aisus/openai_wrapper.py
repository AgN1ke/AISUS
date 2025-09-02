# openai_wrapper.py
from openai import OpenAI


class OpenAIWrapper:
    def __init__(self, api_key: str, api_mode: str = "responses", reasoning_effort: str | None = None):
        self.client = OpenAI(api_key=api_key)
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort
        self.chat_vector_stores: dict[int, str] = {}

    def restore_vector_stores(self, name_prefix: str = "tg-chat-") -> int:
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

    def ensure_vector_store(self, chat_id: int) -> str:
        vs_id = self.chat_vector_stores.get(chat_id)
        if vs_id:
            return vs_id
        vs = self.client.vector_stores.create(name=f"tg-chat-{chat_id}")
        self.chat_vector_stores[chat_id] = vs.id
        return vs.id

    def upload_file_to_chat(self, chat_id: int, file_path: str) -> tuple[str, str]:
        vs_id = self.ensure_vector_store(chat_id)
        f = self.client.files.create(file=open(file_path, "rb"), purpose="assistants")
        self.client.vector_stores.files.create(vector_store_id=vs_id, file_id=f.id)
        return f.id, vs_id

    def generate(self, model: str, messages: list, max_tokens: int, chat_id: int | None = None,
                 extra_overrides: dict | None = None):
        vector_store_id = self.chat_vector_stores.get(chat_id) if chat_id is not None else None

        if self.api_mode == "responses":
            kwargs = {"model": model, "input": messages, "max_output_tokens": max_tokens}
            if self.reasoning_effort:
                kwargs["reasoning"] = {"effort": self.reasoning_effort}

            tools = [{"type": "file_search"}] if vector_store_id else []
            extra_body = {
                "tool_resources": {"file_search": {"vector_store_ids": [vector_store_id]}}} if vector_store_id else {}

            if extra_overrides:
                kwargs.update({k: v for k, v in extra_overrides.items() if k not in ("tool_resources", "resources")})
                if "tool_resources" in extra_overrides:
                    extra_body.setdefault("tool_resources", {}).update(extra_overrides["tool_resources"])
                if "resources" in extra_overrides:
                    extra_body.setdefault("tool_resources", {}).update(extra_overrides["resources"])

            if tools:
                kwargs["tools"] = tools
            if extra_body:
                kwargs["extra_body"] = extra_body

            return self.client.responses.create(**kwargs)

        return self.client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)

    @staticmethod
    def extract_text(response):
        return getattr(response, "output_text", None) or response.choices[0].message.content

    @staticmethod
    def extract_usage(response):
        u = getattr(response, "usage", None)
        if not u:
            return 0, 0
        tokens_in = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0) or 0
        tokens_out = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0) or 0
        return int(tokens_in), int(tokens_out)

    def list_files_in_chat(self, chat_id: int) -> list[dict]:
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return []
        files = self.client.vector_stores.files.list(vector_store_id=vs_id).data
        return [{"id": f.id, "filename": getattr(f, "filename", "?")} for f in files]

    def remove_file_from_chat(self, chat_id: int, file_id: str) -> bool:
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return False
        try:
            self.client.vector_stores.files.delete(vector_store_id=vs_id, file_id=file_id)
            return True
        except Exception:
            return False

    def clear_files_in_chat(self, chat_id: int) -> bool:
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return False
        try:
            self.client.vector_stores.delete(vs_id)
            self.chat_vector_stores.pop(chat_id, None)
            return True
        except Exception:
            return False
