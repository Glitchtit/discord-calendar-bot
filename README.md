# 🗓️ CalendarBot — Discord Herald of Happenings

**CalendarBot** is a medieval-themed calendar assistant for Discord. It fetches events from shared Google or ICS calendars, assigns them to tagged groups (like family members or teams), and posts engaging, image-enhanced announcements to a channel — complete with Bardic poems, Alchemist prophecies, and Royal Decrees.

> ⚔️ Powered by `discord.py`, OpenAI, and Google Calendar API. Runs in Docker with persistent logging, rich embeds, and real-time event monitoring.

---

## ✨ Features

- 🗕️ **Daily & Weekly Summaries** — Automatically posts daily and weekly calendar overviews per user/group.
- 🤹‍♂️ **Themed Morning Greetings** — Uses GPT to generate a whimsical medieval message.
- 🎨 **AI-Generated Art** — DALL·E illustrations styled like the Bayeux Tapestry.
- 🧠 **Natural Language Parsing** — `/agenda tomorrow` or `/agenda next friday <user>`.
- 🔀 **Live Event Monitoring** — Posts alerts for added/removed events.
- 🧩 **User–Tag Mapping** — Assign Discord users to calendar tags via server configuration.
- ⚒️ **Slash Commands with Autocomplete**.
- 📊 **Resource Monitoring** — System resource tracking for stability.

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
| `/admins`         | Manage server admins (Admin only). |
| `/status`         | Check bot status and configuration. |
| `/weekly`         | Post this week's events for all users. |
| `/daily`          | Post today's events for all users. |

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
│   ├── 📁 events/        # Calendar integration (Google & ICS)
│   │   ├── google_api.py        # Google Calendar API setup & service initialization
│   │   ├── calendar_loading.py  # Load and group calendars from server configs
│   │   ├── event_fetching.py    # Fetch events from Google & ICS sources
│   │   ├── metadata.py          # Fetch and cache calendar metadata
│   │   ├── snapshot.py          # Persist and track event snapshots
│   │   ├── fingerprint.py       # Compute fingerprints for deduplication
│   │   └── reload.py            # Event reload & concurrency control
│   ├── core.py           # Discord bot & event handlers
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

## 🖥️ System Requirements

- **Python**: 3.10 or higher
- **RAM**: 512MB minimum (1GB+ recommended)
- **Disk**: 500MB for bot + logs (more for image storage)
- **Network**: Stable internet connection for API calls
- **Docker**: Optional but recommended for deployment

---

## 🔑 API Credentials Setup

### Discord Bot Token
1. Visit [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a new application.
3. Navigate to Bot section and create a bot.
4. Copy the token to your `.env` file.
5. Enable necessary intents (Message Content, Server Members, etc.).
6. Use OAuth2 URL Generator to invite bot to your server.

### OpenAI API Key
1. Create an account at [OpenAI](https://platform.openai.com/).
2. Navigate to API keys section.
3. Generate and copy your API key to `.env`.

### Google Service Account
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project or select an existing one.
3. Enable Google Calendar API.
4. Create a Service Account.
5. Generate JSON key and save as `service_account.json`.
6. Share your calendar with the service account email.

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

1. Use the `/setup add` command to add calendars (requires Admin permission).
2. Each server maintains its own set of calendars and user mappings.
3. Configurations are stored in `/data/servers/{server_id}.json`.

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

## 🔍 Monitoring & Performance

The bot includes built-in resource monitoring using `psutil` to track:
- Memory usage
- CPU utilization
- Disk space
- API rate limiting

You can use the `/status` command to view current resource usage and bot health.

Log files in `/data/logs/` include performance metrics and rotate daily to prevent excessive disk usage. By default, 7 days of logs are preserved.

---

## ❓ Troubleshooting

### Common Issues

1. **Bot not responding**: Check if your bot token is valid and has the correct permissions.
2. **Calendar events missing**: Ensure the service account has read access to your calendar.
3. **Image generation fails**: Verify OpenAI API key and rate limits.
4. **Log directory errors**: Ensure the `/data` directory is writable.

### Debug Mode

Enable debug mode in `.env` for verbose logging:
```env
DEBUG=true
```

### Log Analysis

For detailed troubleshooting, examine the bot logs:
```bash
grep ERROR ./data/logs/bot.log
```

---

## 🧪 Development Tips

- Python 3.10+
- Uses `discord.py`, `openai`, `google-api-python-client`, `ics`, `colorlog`, `dateparser`, etc.
- Add new commands in the `bot/commands/` directory.
- Customize greeting styles in `utils/ai_helpers.py`.
- Run locally by setting `GOOGLE_APPLICATION_CREDENTIALS` to the path of your service account file.
- Use a virtual environment for development:
  ```bash
  python -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  pip install -r requirements.txt
  ```

---
