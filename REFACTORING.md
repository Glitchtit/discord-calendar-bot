# Discord Calendar Bot - Refactored Architecture

## 🏗️ New Project Structure

The codebase has been completely refactored into a modular, maintainable architecture:

```
discord-calendar-bot/
├── src/                          # Main source code package
│   ├── core/                     # Core functionality
│   │   ├── __init__.py          # Core package exports
│   │   ├── environment.py        # Environment variable management
│   │   └── logger.py            # Centralized logging system
│   ├── calendar/                 # Calendar integration
│   │   ├── __init__.py          # Calendar package exports
│   │   ├── sources.py           # Google Calendar & ICS sources
│   │   ├── events.py            # Event fetching & processing
│   │   └── storage.py           # Event persistence & caching
│   ├── ai/                      # AI-powered features
│   │   ├── __init__.py          # AI package exports
│   │   ├── title_parser.py      # OpenAI event title simplification
│   │   └── generator.py         # Greeting & image generation
│   ├── discord_bot/             # Discord integration
│   │   ├── __init__.py          # Discord package exports
│   │   ├── commands.py          # Slash command handlers
│   │   └── embeds.py            # Rich embed creation
│   ├── scheduling/              # Task scheduling
│   │   └── __init__.py          # Task scheduler implementation
│   └── utils/                   # Utility functions
│       └── __init__.py          # Common helper functions
├── bot.py                       # Main bot implementation (refactored)
├── main.py                      # Application entry point (refactored)
└── [legacy files]               # Original files for reference
```

## 🎯 Key Improvements

### **Modular Architecture**
- **Separation of Concerns**: Each module has a single, well-defined responsibility
- **Clean Imports**: Clear dependency structure with proper package organization
- **Reusable Components**: Functions can be easily imported and reused across modules

### **Enhanced Maintainability**
- **Smaller Files**: Large files split into focused, manageable modules
- **Better Organization**: Related functionality grouped into logical packages
- **Cleaner Code**: Reduced complexity and improved readability

### **Improved Error Handling**
- **Centralized Logging**: Consistent logging across all modules
- **Circuit Breaker Pattern**: Prevents API hammering with intelligent retry logic
- **Graceful Degradation**: Fallback mechanisms when external services fail

### **Modern Python Practices**
- **Type Hints**: Better code documentation and IDE support
- **Package Structure**: Proper `__init__.py` files with clean exports
- **Async/Await**: Modern asynchronous programming patterns

## 📦 Module Overview

### `src.core`
**Purpose**: Foundation and configuration
- `environment.py`: Environment variable management
- `logger.py`: Advanced logging with rotation and colors
- Centralized configuration access

### `src.calendar`
**Purpose**: Calendar data management
- `sources.py`: Google Calendar & ICS feed integration
- `events.py`: Event fetching, processing, and deduplication
- `storage.py`: Event persistence and change detection

### `src.ai`
**Purpose**: AI-powered features
- `title_parser.py`: OpenAI-based event title simplification
- `generator.py`: Medieval greeting and image generation
- Circuit breaker pattern for API reliability

### `src.discord_bot`
**Purpose**: Discord integration
- `commands.py`: Slash command handlers with permission checking
- `embeds.py`: Rich embed creation for calendar displays
- User interaction and permission management

### `src.scheduling`
**Purpose**: Task automation
- Background task scheduling with cron-like functionality
- Debug mode for faster testing
- Graceful shutdown handling

### `src.utils`
**Purpose**: Common utilities
- File operations, date handling, text processing
- Error-safe helper functions
- Cleanup and maintenance utilities

## 🚀 Benefits of the New Structure

1. **Easier Development**: Developers can focus on specific modules without understanding the entire codebase
2. **Faster Bug Fixes**: Issues are isolated to specific modules, making debugging more efficient
3. **Better Testing**: Each module can be tested independently
4. **Scalability**: New features can be added without affecting existing functionality
5. **Code Reuse**: Common functionality is centralized and easily accessible

## 🔧 Migration Notes

- **Imports**: Update any custom scripts to use the new import paths
- **Configuration**: Environment variables remain the same
- **Functionality**: All original features are preserved with improved reliability
- **Performance**: Better error handling and caching improve overall performance

## 📝 Development Guidelines

When adding new features:
1. Choose the appropriate package based on functionality
2. Follow the established error handling patterns
3. Use the centralized logger for all logging needs
4. Add proper type hints and documentation
5. Consider creating new packages for major feature additions

The refactored architecture provides a solid foundation for future development while maintaining all existing functionality.