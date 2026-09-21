# Opponent Scout

Локальная система статистического анализа PGN-базы конкретного соперника,
играющего чёрными. Не ищет "один лучший ход" — строит профиль повторяющихся
дебютных, тактических и позиционных проблем по большой выборке партий (500–1000).

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Укажите путь к исполняемому файлу Stockfish в `config.yaml` (`stockfish.path`).
Программа не скачивает и не устанавливает Stockfish самостоятельно.

## Использование

```bash
# Проверить корректность PGN без движка
python src/main.py validate --pgn data/input/opponent.pgn

# Быстрый прогон на 10 партиях без Stockfish
python src/main.py analyze --limit 10 --no-engine

# Полный цикл
python src/main.py all --player "Opponent Name"
```

CLI-команды: `validate`, `analyze`, `report`, `export`, `all`.

Опции: `--depth`, `--critical-depth`, `--threads`, `--hash`, `--player`, `--limit`, `--no-engine`.

## Архитектура

```
src/
├── config.py           типизированная конфигурация (dataclasses)
├── pgn/                загрузка, валидация, фильтрация по игроку/цвету
├── chess_analysis/      дебюты, фазы партии, паттерны позиций
├── engine/              UCI-обёртка Stockfish, кэш, оценка, классификация ходов
├── analysis/            анализ одной партии, batch-анализ, поиск ошибок/паттернов
├── aggregation/         статистика, кластеризация, профиль соперника
└── report/              генерация Markdown/JSON/PGN отчётов
```

Результаты Stockfish кэшируются в SQLite (`data/cache/engine_cache.sqlite`)
по ключу `FEN + depth + multipv`, что позволяет останавливать и продолжать
анализ (`analyze` резюмируется автоматически).

## Принцип

DATA → ENGINE → STATISTICS → PATTERNS → PRACTICAL PREPARATION.

Все статистические выводы сопровождаются размером выборки. Малые выборки
(< `min_sample_size` из config.yaml) помечаются как `LOW_SAMPLE` и не
используются для категоричных утверждений.
