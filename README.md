# The Son of the Machine God

## Architecture

The project is organised following Hexagonal Architecture (Ports & Adapters).

- `src/domain` – pure domain models like `ChatMessage`.
- `src/ports` – interfaces (ports) for interacting with the outside world.
- `src/store` – in-memory implementations of domain repositories (`ChatHistoryManager`).
- `src/openai` – adapters talking to OpenAI services (`OpenAIWrapper`, `VoiceProcessor`).
- `src/adapters` – other adapters such as configuration and Telegram message wrappers.
- `src/app` – application services that orchestrate the domain and ports (see `CustomMessageHandler`).

The entry point `main.py` wires all dependencies together.
