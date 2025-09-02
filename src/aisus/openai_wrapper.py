# openai_wrapper.py
import os
import asyncio
from openai import OpenAI
from agents import Agent, Runner, FileSearchTool


class OpenAIWrapper:
    def __init__(self, api_key: str, api_mode: str = "responses", reasoning_effort: str | None = None):
        self.client = OpenAI(api_key=api_key)
        os.environ.setdefault("OPENAI_API_KEY", api_key)
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

    async def generate(self, model: str, messages: list, max_tokens: int, chat_id: int | None = None,
                       extra_overrides: dict | None = None):
        vector_store_id = self.chat_vector_stores.get(chat_id) if chat_id is not None else None
        if self.api_mode == "agents":
            include_results = bool(extra_overrides.get("citations", {}).get("enabled")) if extra_overrides else False
            tools = []
            if vector_store_id:
                tools.append(FileSearchTool(vector_store_ids=[vector_store_id], include_search_results=include_results))
            system_text = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
            user_messages = [m for m in messages if m.get("role") != "system"]
            agent = Agent(name="TG Assistant", instructions=system_text, tools=tools, model=model)
            return await Runner.run(agent, user_messages)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
        )

    @staticmethod
    def _get_text_from_final_output(resp) -> str:
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

    def _used_file_search(self, resp) -> bool:
        for it in self._walk_nodes(resp):
            name = getattr(it, "tool_name", None)
            if name == "file_search":
                return True
            tool = getattr(it, "tool", None)
            if getattr(tool, "name", None) == "file_search":
                return True
            if isinstance(it, dict):
                if it.get("tool_name") == "file_search":
                    return True
                tool = it.get("tool") or {}
                if isinstance(tool, dict) and tool.get("name") == "file_search":
                    return True
        return False

    def extract_text(self, response):
        if hasattr(response, "final_output"):
            text = "" if getattr(response, "final_output") is None else str(response.final_output)
            return ("[FS] " + text) if self._used_file_search(response) else text
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
