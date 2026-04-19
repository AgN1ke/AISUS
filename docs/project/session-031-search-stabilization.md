# Сесія 031 — Стабілізація Search Runtime

Дата: `2026-04-03`

## Проблема

Після першого переходу на `openai_search` як grounded fallback пошук уже перестав повертати порожні результати для кириличних пошукових запитів, але виявились ще дві проблеми:

- `news`-сценарії могли зриватися в `retry/failure`, хоча вже мали достатньо добрі search hits;
- runtime зайво запускав page extraction навіть для тих профілів, де відповідь можна синтезувати зі search snippets, через що в логах з'являлися зайві `403` від `fetch_page`.

## Що Зроблено

- У [agent/search_task.py](/C:/Python_projects/Smartest/agent/search_task.py) змінено політику `evaluate_search_step(...)`:
  - якщо deterministic heuristic уже визнала evidence достатнім, LLM-evaluator більше не може понизити такий крок до `retry`;
  - це прибрало false negative для grounded/news flow без page text.
- У [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py) змінено `_collect_search_evidence(...)`:
  - page extraction тепер запускається лише тоді, коли це справді потрібно (`need_extract`, `need_primary_source`, `docs`, `research_paper`);
  - для звичайного `news/general` search runtime більше не лізе у зайвий `fetch_page`.
- Актуалізовано тести:
  - [tests/test_030_agent.py](/C:/Python_projects/Smartest/tests/test_030_agent.py)
  - [tests/test_038_search_evaluator.py](/C:/Python_projects/Smartest/tests/test_038_search_evaluator.py)

## Перевірка

- Локально:
  - `python -m py_compile agent/search_task.py agent/runner.py tests/test_030_agent.py tests/test_038_search_evaluator.py`
  - `pytest -q --noconftest tests/test_032_search_task.py tests/test_038_search_evaluator.py tests/test_034_web_search.py tests/test_035_search_provider.py tests/test_071_admin_ui.py`
- На staging `/opt/smartest-staging`:
  - таргетний `pytest` зелений;
  - повний `pytest -q` зелений.
- На live `/opt/smartest`:
- запит про висадку на Місяць повертає нормальну grounded-відповідь з джерелами;
  - `що нового в OpenAI сьогодні` повертає новинну відповідь з джерелами;
  - зайвий page-extract для news path більше не має спрацьовувати.

## Висновок

Search runtime у Smartest тепер працює значно ближче до цільової схеми:

- контекстний `search_task`;
- grounded retrieval;
- evaluator без шкідливого downgrade;
- синтез по search evidence без обов'язкового page extraction там, де це не потрібно.

Повністю проблема search stack ще не закрита стратегічно, бо в live досі немає `Perplexity/Tavily/Exa/Brave` ключів. Але поточний runtime вже дає робочий і передбачуваний baseline на наявних `OpenAI + Gemini`.
