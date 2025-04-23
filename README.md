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
- 🧩 **User–Tag Mapping** — Assign Discord users to calendar tags via env variables.
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

---

## 📦 Project Structure

```
📁 calendarbot/
├── bot.py                # Discord bot & slash command logic
├── main.py               # Bot entrypoint
├── ai.py                 # OpenAI-based greeting and image generation
├── tasks.py              # Scheduled daily/weekly event posters
├── events.py             # Calendar integration (Google & ICS)
├── commands.py           # Embed formatting and command actions
├── utils.py              # Date utilities and formatting
├── log.py                # Rich, color-coded logging setup
├── environ.py            # Environment variable loading
├── requirements.txt      # Python dependencies
├── Dockerfile
└── docker-compose.yml
```

---

## ⚙️ Environment Setup

Copy `.env.example` → `.env` and fill in:

```env
DISCORD_BOT_TOKEN=your-bot-token
ANNOUNCEMENT_CHANNEL_ID=123456789012345678
OPENAI_API_KEY=your-openai-api-key
CALENDAR_SOURCES=google:your_calendar_id:T,ics:http://example.com/calendar.ics:B
USER_TAG_MAPPING=1234567890:T,0987654321:B
DEBUG=true
AI_TOGGLE=true
```

- `CALENDAR_SOURCES`: comma-separated list of `google:<id>:<tag>` or `ics:<url>:<tag>`
- `USER_TAG_MAPPING`: comma-separated Discord `userID:TAG` mappings.
- `AI_TOGGLE`: Set to `false` to disable OpenAI features (greetings, images). Defaults to `true`.

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

> _“Hark, noble kin! The morrow bringeth study, questing, and banquet at sundown.”_

---

## 🧪 Development Tips

- Python 3.10+
- Uses `discord.py`, `openai`, `google-api-python-client`, `ics`, `colorlog`, `dateparser`, etc.
- Add new commands in `bot.py` and `commands.py`
- Customize greeting styles in `ai.py`