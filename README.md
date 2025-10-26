# CalendarBot

CalendarBot is a Discord assistant that turns shared calendars into rich announcements. It gathers events from Google Calendar and raw ICS feeds, groups them by tag, and publishes daily summaries, weekly recaps, and change alerts into a single Discord channel. Optional OpenAI integrations provide medieval-flavoured greetings and AI-generated artwork to keep recurring updates fresh.

---

## Overview

* Written in Python with `discord.py` and long-running background tasks for scheduling and monitoring.
* Supports multiple calendar sources per tag, mixing Google Calendar (via service account) and arbitrary ICS feeds.
* Produces richly formatted embeds, attaches art when available, and automatically colours posts based on resolved Discord member roles.
* Runs under Docker or directly with Python 3.10+, persisting logs, event snapshots, and generated art under `/data`.

---

## Key Capabilities

| Capability | Details |
| --- | --- |
| Daily & weekly digests | Posts a weekly roundup every Monday at 08:00 and a daily summary (with greeting) at 08:01 in the bot's local timezone. |
| Change detection | Watches calendars every five minutes, fingerprints events, and verifies changes after a delay before announcing additions, removals, or edits. |
| Slash commands | Ships with `/agenda`, `/herald`, `/greet`, `/reload`, `/who`, `/verify_status`, `/clear_pending`, `/health`, `/reset_health`, `/log_health`, `/calendars`, and `/debug_calendar`. |
| Health monitoring | Tracks calendar fetch metrics, circuit breakers, and task health; exposes summaries through embeds and logs. |
| AI enhancements | When `AI_TOGGLE` is true and `OPENAI_API_KEY` is present, generates persona-driven greetings and optional artwork. |
| Robust logging | Writes colourised console logs and rotates persistent log files; falls back gracefully when `/data/logs` is unavailable. |

---

## Architecture at a Glance

* **`main.py`** – Entry point that validates environment configuration, sets up signal handling, starts watchdogs, and launches the Discord bot.【F:main.py†L12-L120】【F:main.py†L160-L227】
* **`bot.py`** – Discord client definition, slash command handlers, and runtime bootstrap logic (including reconnect resilience).【F:bot.py†L1-L575】
* **`events.py`** – Calendar ingestion layer with Google API access, ICS parsing, caching, metrics, and circuit breaker logic.【F:events.py†L1-L200】
* **`tasks.py`** – Background loops for scheduling daily posts, monitoring change queues, verifying diffs, and reporting task health.【F:tasks.py†L1-L360】
* **`commands.py`** – Embed generation, Discord posting helpers, autocomplete providers, and agenda formatting utilities.【F:commands.py†L1-L160】
* **`ai.py`** – Optional OpenAI greeting/art generation with built-in circuit breaker and fallbacks.【F:ai.py†L1-L160】
* **`calendar_health.py`** – Consolidated health reporting utilities reused by slash commands and CLI checks.【F:calendar_health.py†L1-L140】
* **`log.py`** – Central logging configuration with queue-based handlers and persistent rotation under `/data/logs`.【F:log.py†L1-L160】

---

## Prerequisites

* Python 3.10 or newer (for local execution).
* Discord application with a bot token and the `applications.commands` scope.
* Google service account JSON file with Calendar API access (only required for Google sources).
* ICS feed URLs (optional) for non-Google calendars.
* OpenAI API key (optional) to enable greetings and artwork.

---

## Configuration

Copy `.env.example` to `.env` and supply the required values. These environment variables are read via `environ.py`.

| Variable | Purpose |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Discord bot token used for authentication.【F:environ.py†L11-L18】 |
| `ANNOUNCEMENT_CHANNEL_ID` | Numeric ID of the channel where embeds are posted.【F:environ.py†L11-L18】 |
| `CALENDAR_SOURCES` | Comma-separated list of sources in the form `google:<calendar_id>:<TAG>` or `ics:<url>:<TAG>`. Multiple sources can share the same tag.【F:environ.py†L23-L27】【F:events.py†L13-L24】 |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the Google service account file. Defaults to `/app/service_account.json` inside Docker.【F:environ.py†L19-L27】 |
| `USER_TAG_MAPPING` | Comma-separated list of `discord_user_id:TAG` entries used to map members to tags and colours.【F:environ.py†L23-L31】【F:bot.py†L452-L520】 |
| `OPENAI_API_KEY` | Enables AI greetings and artwork when present.【F:environ.py†L15-L22】【F:ai.py†L1-L60】 |
| `AI_TOGGLE` | Set to `false` to disable AI features without removing the key.【F:environ.py†L31-L33】【F:bot.py†L205-L223】 |
| `DEBUG` | Optional; set to `true` for verbose logging.【F:environ.py†L7-L12】【F:log.py†L1-L100】 |

Example `.env` snippet:

```env
DISCORD_BOT_TOKEN=xxxxx
ANNOUNCEMENT_CHANNEL_ID=123456789012345678
CALENDAR_SOURCES=google:primary:T,ics:https://example.com/family.ics:F
USER_TAG_MAPPING=111111111111111111:T,222222222222222222:F
GOOGLE_APPLICATION_CREDENTIALS=/app/service_account.json
OPENAI_API_KEY=
AI_TOGGLE=true
DEBUG=false
```

---

## Running the Bot

### Local Python environment

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Ensure `GOOGLE_APPLICATION_CREDENTIALS` points to your service account file.
4. Start the bot: `python main.py`.

`main.py` validates configuration, registers signal handlers, and then calls `bot.run(...)` with reconnect logic, so the process can be supervised directly or via a process manager.【F:main.py†L60-L227】

### Docker Compose

1. Place your `.env` file and `service_account.json` in the project root.
2. Mount the `/data` volume (already defined in `docker-compose.yml`).【F:docker-compose.yml†L1-L24】
3. Build and run: `docker compose up --build -d`.

The container writes logs, event caches, and artwork to the mounted `./data` directory so they survive restarts.【F:log.py†L13-L60】【F:events.py†L19-L28】【F:ai.py†L262-L282】

---

## Slash Command Reference

| Command | Description |
| --- | --- |
| `/agenda <input> [target]` | Post events for a natural-language date or range, optionally filtered by tag or mapped display name. Autocompletes dates and tags.【F:bot.py†L123-L204】 |
| `/herald` | Publish both weekly and daily summaries for every configured tag.【F:bot.py†L90-L140】 |
| `/greet` | Trigger the morning greeting and image (honours `AI_TOGGLE`).【F:bot.py†L205-L223】 |
| `/reload` | Reload calendar sources and Discord member/tag mappings.【F:bot.py†L227-L241】 |
| `/who` | List current tags and resolved display names.【F:bot.py†L243-L254】 |
| `/verify_status` | Show pending change verifications awaiting confirmation.【F:bot.py†L258-L304】 |
| `/clear_pending` | Manually clear queued change verifications (admin/debug).【F:bot.py†L285-L304】 |
| `/health [detailed]` | Display calendar processing metrics, alerts, and circuit breaker information.【F:bot.py†L305-L405】 |
| `/reset_health [component]` | Reset health metrics and/or circuit breakers (admin).【F:bot.py†L426-L460】 |
| `/log_health` | Force a health snapshot to be written to the logs.【F:bot.py†L466-L492】 |
| `/calendars` | Summarise configured calendar sources per tag, including failure states.【F:bot.py†L498-L552】 |
| `/debug_calendar <query>` | Inspect a specific calendar, download ICS content, and surface parse issues (admin).【F:bot.py†L560-L640】 |

All commands use Discord's interaction API, and the bot automatically syncs them on startup with retry/backoff handling.【F:bot.py†L37-L89】

---

## Scheduled Automation & Change Verification

* `schedule_daily_posts` runs every minute, posting the Monday morning weekly recap and the daily agenda/greeting at their scheduled times.【F:tasks.py†L240-L312】
* `watch_for_event_changes` scans up to three tags every five minutes, fingerprints events, and queues detected differences for verification before posting embeds.【F:tasks.py†L312-L420】
* `_pending_changes` and `verification_watchdog` enforce a six-minute verification delay with up to three retries to avoid false positives from transient calendar edits.【F:tasks.py†L48-L120】【F:tasks.py†L360-L520】
* Health watchers track task success timestamps and restart stuck loops when needed.【F:tasks.py†L1-L220】

---

## Monitoring & Debugging

* Logs are written to `/data/logs/bot.log` with daily rotation; if the directory is unavailable the logger falls back to a local `logs/` folder or console output.【F:log.py†L13-L120】
* `/health`, `/calendars`, `/log_health`, and `/reset_health` provide real-time insights into calendar fetch performance and circuit breakers.【F:bot.py†L305-L552】
* `calendar_health.py` can be executed directly (`python calendar_health.py`) to print metrics and breaker states to the console.【F:calendar_health.py†L1-L80】
* `data/events.json` stores the previous event snapshots used for diffing; removing the file forces a fresh baseline.【F:events.py†L19-L28】【F:tasks.py†L312-L420】

---

## Data & Persistence

| Path | Contents |
| --- | --- |
| `/data/logs/` | Rotating bot logs (mounted via Docker volume).【F:log.py†L13-L100】 |
| `/data/events.json` | Latest stored event fingerprints for change detection.【F:events.py†L19-L28】 |
| `/data/art/` | AI-generated images saved by the greeting workflow (created on demand).【F:ai.py†L262-L282】 |

Ensure these directories are writable when running outside Docker, or adjust the paths to suit your environment.

---

## Development Notes

* Enable debug logging by setting `DEBUG=true` before launching the bot.【F:environ.py†L7-L12】【F:log.py†L1-L120】
* New slash commands belong in `bot.py`; shared embed logic and autocomplete lives in `commands.py`.
* Utility functions for date parsing, timezone handling, and event formatting are in `utils.py` and already guard against malformed input.【F:utils.py†L1-L200】
* The AI layer gracefully falls back to handcrafted greetings whenever OpenAI credentials are missing or the circuit breaker trips.【F:ai.py†L1-L160】

With the environment configured and a Discord bot invited to your server, run `python main.py` (or the Docker stack) and CalendarBot will keep your channel up to date with timely, verified calendar announcements.
