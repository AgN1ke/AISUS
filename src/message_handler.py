#message_handler.py

import os
import requests
from telegram import Update
from telegram.ext import ContextTypes
from src.message_wrapper import MessageWrapper
from src.heroku_config_parser import ConfigReader
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager
from src.openai_wrapper import OpenAIWrapper
from db.hooks import track_chat_and_user_ptb
from memory import memory_manager
from knowledge.threads import handle_message_ptb
from knowledge.glossary import process_user_text
from agent.runner import _should_use_agent, run_agent, run_simple

from db.settings_repository import get_settings, upsert_settings
from media.router import handle_ptb_mention
import base64
import asyncio

def _is_mention_for_bot(msg, bot_username: str) -> bool:
    ents = (msg.entities or []) + (msg.caption_entities or [])
    for e in ents:
        if e.type in ("mention", "text_mention"):
            txt = msg.text or msg.caption or ""
            if f"@{bot_username}".lower() in txt.lower():
                return True
    t = (msg.text or msg.caption or "") or ""
    return f"@{bot_username}".lower() in t.lower()


import base64
import asyncio



class CustomMessageHandler:
    def __init__(
        self,
        config: ConfigReader,
        client,
        voice_processor: VoiceProcessor,
        chat_history_manager: ChatHistoryManager,
        openai_wrapper: OpenAIWrapper,
    ):
        self.config = config
        self.client = client
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await track_chat_and_user_ptb(update, context)
        await handle_message_ptb(update, context)

        msg = update.effective_message

        chat_id = update.effective_chat.id
        bot_username = context.bot.username

        full_text = (msg.text or msg.caption or "") or ""
        if full_text:
            suggestion = await process_user_text(chat_id, full_text)
            if suggestion:
                await msg.reply_text(suggestion)

        st = await get_settings(chat_id) or {}
        if not (st.get("auth_ok") or 0):
            t = (msg.text or msg.caption or "") or ""
            if _is_mention_for_bot(msg, bot_username):
                stripped = (t.replace(f"@{bot_username}", "", 1)).strip()
                pw = stripped.split()[0] if stripped else ""
                if pw and pw == os.getenv("CHAT_JOIN_PASSWORD", ""):
                    await upsert_settings(chat_id, auth_ok=True, mode=None)
                    await msg.reply_text("✅ Дякую, пароль прийнято. Я готова працювати в цьому чаті.")
                    return
                else:
                    await msg.reply_text("🔒 Вкажи коректний пароль у форматі: @" + bot_username + " <пароль>")
                    return
=======
        chat_id = update.effective_chat.id
        bot_username = context.bot.username

        full_text = (msg.text or msg.caption or "") or ""
        if full_text:
            suggestion = await process_user_text(chat_id, full_text)
            if suggestion:
                await msg.reply_text(suggestion)

        st = await get_settings(chat_id) or {}
        if not (st.get("auth_ok") or 0):
            t = (msg.text or msg.caption or "") or ""
            if _is_mention_for_bot(msg, bot_username):
                stripped = (t.replace(f"@{bot_username}", "", 1)).strip()
                pw = stripped.split()[0] if stripped else ""
                if pw and pw == os.getenv("CHAT_JOIN_PASSWORD", ""):
                    await upsert_settings(chat_id, auth_ok=True, mode=None)
                    await msg.reply_text("✅ Дякую, пароль прийнято. Я готова працювати в цьому чаті.")
                    return
                else:
                    await msg.reply_text("🔒 Вкажи коректний пароль у форматі: @" + bot_username + " <пароль>")
                    return

        await handle_message_ptb(update, context)

        msg = update.effective_message


        await handle_message_ptb(update, context)

        msg = update.effective_message

        chat_id = update.effective_chat.id
        message_text = msg.text if msg.text else ""

        full_text = (msg.text or msg.caption or "") or ""
        if full_text:
            suggestion = await process_user_text(chat_id, full_text)
            if suggestion:
                await msg.reply_text(suggestion)

        # Перевірка, чи бот має бути активований в публічному чаті (тільки через тег або відповідь)
        if not await self._should_process_message_async(context.bot, MessageWrapper(update)):
            print("Message not processed due to filter.")

            return

    
        user_text = None
        if _is_mention_for_bot(msg, bot_username):
            user_text = await handle_ptb_mention(update, context, bot_username)

        if user_text is None:
            user_text = (msg.text or msg.caption or "").strip()
            if not user_text:
                return
            await memory_manager.append_message(chat_id, "user", user_text)
            await memory_manager.ensure_budget(chat_id)

        if _should_use_agent(user_text):
            await msg.chat.send_action("typing")
            answer = await run_agent(chat_id, user_text)
        else:
            answer = await run_simple(chat_id, user_text)

        if answer:
            await msg.reply_text(answer)
            await memory_manager.append_message(chat_id, "assistant", answer)
            await memory_manager.ensure_budget(chat_id)

    def _handle_message(self, bot, message):
        if not self._should_process_message(bot, message):
            print("Message not processed due to filter.")
            return
        user_message, is_voice, is_image = asyncio.run(self._process_message_content(message))
        if not user_message:
            print("No user message found.")
            return
        first_name = getattr(message, "from_user_first_name", "")
        chat_id = message.chat_id
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)
        history = self.chat_history_manager.get_history(chat_id)
        bot_response = self._generate_bot_response(history)
        self.chat_history_manager.add_bot_message(chat_id, bot_response)
        self.chat_history_manager.prune_history(chat_id, 124000)



    def _handle_message(self, bot, message):
        if not self._should_process_message(bot, message):
            print("Message not processed due to filter.")
            return
        user_message, is_voice, is_image = asyncio.run(self._process_message_content(message))
        if not user_message:
            print("No user message found.")
            return
        first_name = getattr(message, "from_user_first_name", "")
        chat_id = message.chat_id
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)
        history = self.chat_history_manager.get_history(chat_id)
        bot_response = self._generate_bot_response(history)
        self.chat_history_manager.add_bot_message(chat_id, bot_response)
        self.chat_history_manager.prune_history(chat_id, 124000)


    async def _should_process_message_async(self, bot, message):
        """Determine if the message should be processed."""
        bot_me = bot.get_me()
        if asyncio.iscoroutine(bot_me):
            bot_me = await bot_me
        bot_username = getattr(bot_me, "username", "")
        chat_type = getattr(message, "chat_type", "private")
        if not isinstance(chat_type, str):
            chat_type = "private"
        text = getattr(message, "text", "")
        if not isinstance(text, str):
            text = ""
        reply_to = getattr(message, "reply_to_message", None)
        reply_username = getattr(message, "reply_to_message_from_user_username", None)
        if not isinstance(reply_username, str):
            reply_username = None
        return bool(
            chat_type == "private" or
            (text and f"@{bot_username}" in text) or
            (reply_to and reply_username == bot_username)
        )

    def _should_process_message(self, bot, message):
        return asyncio.run(self._should_process_message_async(bot, message))

    async def _handle_user_message(self, bot, message: MessageWrapper):
        """Handle incoming user messages (text, voice, image) and generate responses."""
        user_message, is_voice, is_image = await self._process_message_content(message)
        if not user_message:
            print("No user message found.")
            return

        first_name, last_name = message.from_user_first_name, message.from_user_last_name
        chat_id = message.chat_id
        print(f"Processing message from {first_name} {last_name} ({chat_id}): {user_message}")
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)

        user_text = (user_message or "").strip()
        if user_text:
            await memory_manager.append_message(chat_id, "user", user_text)
            await memory_manager.ensure_budget(chat_id)

        try:

            if _should_use_agent(user_text):
                bot_response = await run_agent(chat_id, user_text)
            else:
                bot_response = await run_simple(chat_id, user_text)



            SYSTEM_PROMPT = "Ти корисний асистент у цьому чаті. Відповідай чітко і по суті контексту."
            ctx_messages = await memory_manager.select_context(
                chat_id=chat_id,
                user_query=user_text or "",
                system_prompt=SYSTEM_PROMPT,
            )
            bot_response = self._generate_bot_response(ctx_messages)



            print(f"Generated response: {bot_response}")
            await self._send_response(message, bot_response, is_voice)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)

            assistant_reply = bot_response.strip()
            if assistant_reply:
                await memory_manager.append_message(chat_id, "assistant", assistant_reply)
                await memory_manager.ensure_budget(chat_id)
        except Exception as e:
            print(f"Error generating or sending response: {e}")
            await message.reply_text("Вибачте, але я не можу продовжити цю розмову.")

        self.chat_history_manager.prune_history(chat_id, 124000)

    async def _process_message_content(self, message):
        """Process the content of the message, whether it's text, voice, or image."""
        is_voice = False
        is_image = False

        voice_attr = getattr(message, "voice", None)
        photo_attr = getattr(message, "photo", None)

        if voice_attr and voice_attr.__class__.__name__ != "Mock":
            print("Voice file received")
            voice_message_path = await message.download_voice()
            transcribed_text = self.voice_processor.transcribe_voice_message(voice_message_path)
            return transcribed_text, True, False
        elif photo_attr and photo_attr.__class__.__name__ != "Mock":
            print("Image received")
            image_path = await message.download_image()
            image_caption = message.message.caption or " "
            analysis_result = await self._analyze_image_with_openai(image_path)
            full_image_message = (
                f"{self.config.get_system_messages()['image_message_affix']} "
                f"{self.config.get_system_messages()['image_caption_affix']} {image_caption} "
                f"{self.config.get_system_messages()['image_sence_affix']} {analysis_result}"
            )
            return full_image_message, False, True
        else:
            return getattr(message, "text", None), False, False

    async def _analyze_image_with_openai(self, image_path: str) -> str:
        """Send image to OpenAI for analysis and return the result."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.get_openai_settings()['api_key']}"
        }

        # Read the image and encode it in base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What's in this image?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 900
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        return response.json()["choices"][0]["message"]["content"]

    def _update_chat_history(self, chat_id, first_name, user_message, is_voice, is_image):
        """Update the chat history with the user's message."""
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()['welcome_message'])

        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
        elif is_image:
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
        else:
            voice_affix = self.config.get_system_messages()['voice_message_affix']
            if voice_affix:
                self.chat_history_manager.remove_system_voice_affix_if_exist(chat_id, voice_affix)
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, messages):
        """Generate the bot's response using OpenAI."""
        response = self.openai_wrapper.chat_completion(
            model=self.config.get_openai_settings()['gpt_model'],
            messages=messages,
            max_tokens=3000)  # Обеспечиваем лимит для ответа в 4000 токенов
        bot_response = response.choices[0].message.content
        return bot_response

    async def _send_response(self, message, bot_response, is_voice):
        """Send the response back to the user."""
        if is_voice:
            voice_response_file = self.voice_processor.generate_voice_response_and_save_file(
                bot_response,
                self.config.get_openai_settings()['vocalizer_voice'],
                self.config.get_file_paths_and_limits()['audio_folder_path'])
            await message.reply_voice(voice_response_file)
            if os.path.exists(voice_response_file):
                os.remove(voice_response_file)
        else:
            await message.reply_text(bot_response)


MessageHandler = CustomMessageHandler
