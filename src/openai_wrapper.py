# src/openai_wrapper.py

import websockets
import json

class OpenAIRealtimeClient:
    def __init__(self, api_key, model='gpt-4o-realtime-preview-2024-10-01'):
        self.api_key = api_key
        self.model = model
        self.websocket = None
        self.url = f"wss://api.openai.com/v1/realtime?model={self.model}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

    async def connect(self):
        self.websocket = await websockets.connect(
            self.url,
            extra_headers=self.headers
        )
        print("Підключено до OpenAI Realtime API")
        # Очікуємо подію session.created
        message = await self.websocket.recv()
        event = json.loads(message)
        if event['type'] == 'session.created':
            self.session_id = event['session']['id']
            print(f"ID сесії: {self.session_id}")

    async def send_event(self, event):
        await self.websocket.send(json.dumps(event))

    async def receive_event(self):
        message = await self.websocket.recv()
        event = json.loads(message)
        return event

    async def send_message(self, text):
        # Відправляємо повідомлення користувача
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": text
                    }
                ]
            }
        }
        await self.send_event(event)

        # Стартуємо генерацію відповіді
        response_event = {
            "type": "response.create",
            "response": {
                "modalities": ["text"],
                "instructions": "Please assist the user."
            }
        }
        await self.send_event(response_event)

    async def send_audio(self, audio_data_base64):
        # Відправляємо аудіо користувача
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "audio": audio_data_base64
                    }
                ]
            }
        }
        await self.send_event(event)

        # Стартуємо генерацію відповіді
        response_event = {
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": "Please assist the user."
            }
        }
        await self.send_event(response_event)

    async def receive_responses(self):
        """Асинхронно отримуємо відповіді від сервера."""
        response_text = ""
        while True:
            event = await self.receive_event()
            # Обробляємо події відповідно
            if event['type'] == 'response.text.delta':
                delta_text = event['content']['text']
                response_text += delta_text
            elif event['type'] == 'response.text.done':
                break
            # Додайте обробку інших типів подій за потреби
        return response_text

    async def close(self):
        await self.websocket.close()
