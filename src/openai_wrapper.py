# src/openai_wrapper.py

import websocket
import threading
import json

class OpenAIRealtimeClient:
    def __init__(self, api_key, model='gpt-4o-realtime-preview-2024-10-01'):
        self.api_key = api_key
        self.model = model
        self.ws = None
        self.url = f"wss://api.openai.com/v1/realtime?model={self.model}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        self.session_id = None
        self.response_text = ""
        self.is_connected = False

    def on_open(self, ws):
        print("Підключено до OpenAI Realtime API")
        self.is_connected = True

    def on_message(self, ws, message):
        event = json.loads(message)
        if event['type'] == 'session.created':
            self.session_id = event['session']['id']
            print(f"ID сесії: {self.session_id}")
        elif event['type'] == 'response.text.delta':
            delta_text = event['content']['text']
            self.response_text += delta_text
        elif event['type'] == 'response.text.done':
            ws.close()

    def on_error(self, ws, error):
        print(f"Помилка WebSocket: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("З'єднання з OpenAI Realtime API закрито")
        self.is_connected = False

    def connect(self):
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.url,
            header=[f"{key}: {value}" for key, value in self.headers.items()],
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        wst = threading.Thread(target=self.ws.run_forever)
        wst.start()
        while not self.is_connected:
            pass  # Очікуємо підключення

    def send_message(self, text):
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
        self.ws.send(json.dumps(event))

        response_event = {
            "type": "response.create",
            "response": {
                "modalities": ["text"],
                "instructions": "Please assist the user."
            }
        }
        self.ws.send(json.dumps(response_event))

    def get_response(self):
        while self.is_connected:
            pass  # Очікуємо завершення отримання відповіді
        return self.response_text

    def close(self):
        if self.ws:
            self.ws.close()
