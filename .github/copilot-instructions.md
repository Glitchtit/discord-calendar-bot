# Copilot Instructions

## Build, Test, and Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py

# Run all tests
pytest -v

# Run a single test file
pytest test_ai_title_parser.py -v

# Run a single test
pytest test_ssl_error_handling.py::TestIsSSLError::test_direct_ssl_error -v

# Docker
docker compose up --build
```

## Architecture

This is a Discord bot (discord.py 2.3.2) that turns Google Calendar and ICS feeds into rich Discord announcements with optional AI-generated greetings and artwork.

### Module Responsibilities

- **main.py** — Entry point. Environment validation, graceful shutdown with signal handlers, watchdog thread, and startup retry logic with exponential backoff (max 3 attempts).
- **resilience.py** — Shared `CircuitBreaker` class and `CalendarCircuitBreakers` registry, plus `retry_with_backoff()` and `async_retry_with_backoff()` helpers using tenacity. Used by ai.py, events.py, and commands.py.
- **bot.py** — Bot instance creation and configuration.
- **commands.py** — Discord slash commands registered via `@bot.tree.command()`. ~12 commands including `/health`, `/calendars`, `/reset_health`.
- **events.py** — Calendar integration (largest module). Fetches from Google Calendar API (service account) and ICS feeds. Handles ICS preprocessing for malformed data, SSL error detection, and per-calendar circuit breakers.
- **tasks.py** — Background `@tasks.loop()` tasks: daily/weekly digests (Mon 08:00, daily 08:01 UTC), change detection every 5 minutes with verification queue (6-min delay, up to 3 verification attempts). Tracks task health via `_task_last_success` and `_task_error_counts`.
- **ai.py** — OpenAI integration (GPT-4o for greetings, DALL·E-3 for images). Has its own circuit breaker (opens after 3 errors, resets after 5 min). Falls back to `generate_fallback_greeting()` when unavailable.
- **ai_title_parser.py** — Simplifies event titles to ≤5 words using OpenAI with regex fallback. Handles Swedish/English course codes, room numbers, group IDs. Uses `@lru_cache`.
- **calendar_health.py** — Unified health reporting. Status levels: healthy (≥90%), degraded (70–89%), unhealthy (<70%).
- **log.py** — Queue-based thread-safe logging. `TimedRotatingFileHandler` (daily rotation, 7-day retention, 10MB limit). Falls back: `/data/logs/` → `./logs/` → temp dir → console only.
- **utils.py** — Date helpers, emoji assignment by event title pattern, event formatting for Discord embeds, tag resolution.
- **environ.py** — Centralized `os.getenv()` calls with defaults.

### Data Flow

1. `tasks.py` loops fetch events from calendar sources (configured via `CALENDAR_SOURCES` env var, format: `google:calendar_id:TAG` or `ics:url:TAG`)
2. `events.py` retrieves and normalizes events from Google Calendar API or ICS feeds
3. `ai_title_parser.py` optionally simplifies titles; `ai.py` optionally generates greetings/art
4. `utils.py` formats events into Discord embed strings
5. `commands.py` / `tasks.py` send embeds to the announcement channel

### Data Persistence

All persistent data lives under `/data/` (Docker volume-mounted):
- `/data/events.json` — Event fingerprints for change detection
- `/data/logs/` — Rotating log files
- `/data/art/` — Generated DALL·E images

## Key Patterns

### Circuit Breaker Pattern

Used in two places with different configurations:
- **OpenAI** (`ai.py`): Global state via module-level variables (`_circuit_open`, `_error_count`). Opens after 3 errors, auto-resets after 5 minutes.
- **Calendar sources** (`events.py`): Per-calendar tracking via `_failed_calendars` dict. Exponential backoff from 60s to 3600s max. `_MAX_FAILURE_COUNT = 5`.

When adding new external service integrations, follow this same circuit breaker pattern.

### Retry with Exponential Backoff and Jitter

Consistent pattern across all external calls:
```python
for attempt in range(max_retries):
    try:
        return operation()
    except RetryableError:
        backoff = (2 ** attempt) + random.uniform(0, 1)
        await asyncio.sleep(backoff)
```

Retryable: SSL errors, network timeouts, rate limits (429).
Non-retryable (fail immediately): invalid token, forbidden, malformed data.

### Graceful Degradation

Every layer has a fallback — AI unavailable → fallback greeting, calendar source fails → others continue, log dir inaccessible → next fallback dir. Never let one component's failure take down the bot.

### Discord Slash Command Pattern

```python
@bot.tree.command(name="...", description="...")
async def cmd_name(interaction: discord.Interaction, param: str):
    try:
        await interaction.response.defer()  # Acknowledge immediately
        # ... perform work ...
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.exception(f"Error in cmd_name: {e}")
        await interaction.followup.send(f"Error: {e}")
```

Always defer first to prevent Discord's 3-second interaction timeout.

### Event Change Verification

Changes detected every 5 minutes are queued with a 6-minute verification delay and up to 3 confirmation attempts before announcing — this prevents false positives from transient calendar edits.

### Logging

Import and use: `from log import logger`. Use standard levels — `debug` for operational detail, `info` for key events, `warning` for degraded conditions (fallback triggered, API down), `error`/`exception` for failures.

### Module Header Style

Modules use decorative box-style section headers:
```python
# ╔════════════════════════════════════════════════════════════╗
# ║ 🎯 Section Name                                            ║
# ╚════════════════════════════════════════════════════════════╝
```

### Naming

- Private/internal: leading underscore (`_failed_calendars`, `_circuit_open`)
- Constants: UPPER_SNAKE_CASE grouped with comments
- Python 3.10+ type hints: `str | None`, `list[dict]`
