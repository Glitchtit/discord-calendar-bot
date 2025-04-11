# 🗓️ CalendarBot — Discord Herald of Happenings

**CalendarBot** is a fully-featured, medieval-themed calendar assistant for Discord. It fetches events from shared Google or ICS calendars, assigns them to tagged groups (like family members or teams), and posts engaging, image-enhanced announcements to a channel — complete with Bardic poems, Alchemist prophecies, and Royal Decrees.

> ⚔️ Powered by `discord.py`, OpenAI, and Google Calendar API. Runs in Docker with persistent logging, rich embeds, and real-time event monitoring.

---

## ✨ Features

- 🗕️ **Daily & Weekly Summaries** — Automatically posts daily and weekly calendar overviews per user/group.
- 🤹‍♂️ **Themed Morning Greetings** — Uses GPT to generate a whimsical medieval message.
- 🎨 **AI-Generated Art** — DALL·E illustrations styled like the Bayeux Tapestry.
- 🧠 **Natural Language Parsing** — `/agenda tomorrow` or `/agenda next friday Anniina`
- 🔀 **Live Event Monitoring** — Posts alerts for added/removed events.
- 🧩 **User–Tag Mapping** — Assign Discord users to calendar tags via server configuration.
- ⚒️ **Slash Commands with Autocomplete**

---

## 🚀 Slash Commands

| Command           | Description |
|------------------|-------------|
| `/herald`         | Post **weekly and daily** events for all tags. |
| `/agenda [date] [tag]` | Show events for natural language date & optional group. |
| `/greet`          | Post the themed morning greeting with image. |
| `/reload`         | Reload calendars and tag mappings. |
| `/who`            | Show current calendar tags and assigned users. |
| `/setup`          | Configure calendars for the server (Admin only). |
| `/status`         | Check bot status and configuration. |

---

## 📦 Project Structure

```
📁 discord-calendar-bot/
├── main.py                # Bot entrypoint
├── ai.py                  # Re-exports for backward compatibility
├── utils.py               # Re-exports for backward compatibility
├── docker-compose.yml     # Docker deployment configuration
├── Dockerfile             # Container build definition
├── requirements.txt       # Python dependencies
├── 📁 bot/                # Discord bot module
│   ├── core.py           # Discord bot & event handlers
│   ├── events.py         # Calendar integration (Google & ICS)
│   ├── tasks.py          # Scheduled daily/weekly event posters
│   ├── commands.py       # Command registration system
│   ├── views.py          # Discord UI components
│   └── 📁 commands/      # Individual command implementations
│       ├── agenda.py     # Date-specific events query
│       ├── daily.py      # Daily calendar posting
│       ├── greet.py      # AI greeting generation
│       ├── herald.py     # Weekly calendar posting
│       ├── reload.py     # Config reloading command
│       ├── setup.py      # Server configuration
│       ├── status.py     # Bot status info
│       ├── utilities.py  # Shared command utilities
│       └── who.py        # User mapping info
├── 📁 config/            # Configuration handling
│   ├── calendar_config.py # Calendar data structure
│   └── server_config.py  # Server-specific settings
├── 📁 utils/             # Utility modules
│   ├── ai_helpers.py     # OpenAI integration
│   ├── cache.py          # Data caching
│   ├── calendar_sync.py  # Real-time calendar updates
│   ├── environ.py        # Environment configuration
│   ├── error_handling.py # Error management
│   ├── logging.py        # Log setup and management
│   ├── notifications.py  # Admin notifications
│   ├── rate_limiter.py   # API rate limiting
│   ├── server_utils.py   # Server configuration helpers
│   ├── timezone_utils.py # Time zone conversions
│   └── validators.py     # Input validation
```

---

## ⚙️ Environment Setup

Copy `.env.example` → `.env` and fill in:

```env
DISCORD_BOT_TOKEN=your-bot-token
OPENAI_API_KEY=your-openai-api-key
GOOGLE_APPLICATION_CREDENTIALS=./service_account.json
DEBUG=true
```

---

## ⚙️ Server-Specific Configuration

CalendarBot uses server-specific configuration files instead of environment variables:

1. Use the `/setup add` command to add calendars (requires Admin permission)
2. Each server maintains its own set of calendars and user mappings
3. Configurations are stored in `/data/servers/{server_id}.json`

Example:
```bash
/setup add calendar_url:your_calendar_id@group.calendar.google.com user:@username
```

---

## 🐋 Running with Docker

### 1. Build and Run

```bash
docker compose up --build -d
```

### 2. Files & Volumes

| Path                  | Purpose                           |
|-----------------------|-----------------------------------|
| `/data/`              | Persistent logs, art, event cache |
| `service_account.json`| Google service account creds      |

### 3. Logs

```bash
tail -f ./data/logs/bot.log
```

---

## 🖼️ Generated Example

<img src="example.png" width="400"/>

> _"Hark, noble kin! The morrow bringeth study, questing, and banquet at sundown."_

---

## 🧪 Development Tips

- Python 3.10+
- Uses `discord.py`, `openai`, `google-api-python-client`, `ics`, `colorlog`, `dateparser`, etc.
- Add new commands in the `bot/commands/` directory
- Customize greeting styles in `utils/ai_helpers.py`
- Run locally by setting `GOOGLE_APPLICATION_CREDENTIALS` to the path of your service account file