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

    def used_file_search(self, resp) -> bool:
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
            except Exception:
                pass

        return False

    def extract_text(self, response):
        if hasattr(response, "final_output"):
            return "" if getattr(response, "final_output") is None else str(response.final_output)
        return getattr(response, "output_text", None) or response.choices[0].message.content

    @staticmethod
    def extract_usage(response):
        def to_int(x):
            try:
                return int(x)
            except Exception:
                return 0

        cw = getattr(response, "context_wrapper", None)
        u = getattr(cw, "usage", None) if cw else None
        if u:
            return to_int(getattr(u, "input_tokens", 0)), to_int(getattr(u, "output_tokens", 0))

        rr = getattr(response, "raw_responses", None)
        if rr and hasattr(rr, "__iter__"):
            ti = sum(to_int(getattr(getattr(r, "usage", None), "input_tokens", 0)) for r in rr)
            to = sum(to_int(getattr(getattr(r, "usage", None), "output_tokens", 0)) for r in rr)
            if ti or to:
                return ti, to

        u = getattr(response, "usage", None)
        if u:
            ti = to_int(getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0))
            to = to_int(getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0))
            return ti, to

        return 0, 0

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

    def list_files_in_chat(self, chat_id: int) -> list[dict]:
        vs_id = self.chat_vector_stores.get(chat_id)
        if not vs_id:
            return []
        files = self.client.vector_stores.files.list(vector_store_id=vs_id).data
        return [{"id": f.id, "filename": getattr(f, "filename", "?")} for f in files]
