# Calendar Health Monitoring

The Discord calendar bot now includes comprehensive health monitoring and error handling features to prevent silent crashes and provide visibility into system status.

## Discord Commands

### `/health` 
Shows current calendar system health status in Discord.

**Usage:**
```
/health                    # Basic health overview
/health detailed:True      # Detailed view with circuit breaker info
```

**Output:**
- System status (Healthy/Degraded/Unhealthy/Unknown)
- Request statistics (success/failure rates)
- Processing stats (events processed, duration)
- Error breakdown (parsing/network/auth errors)
- Active alerts and circuit breaker status

### `/reset_health`
Resets health metrics and circuit breakers (admin command).

**Usage:**
```
/reset_health component:all       # Reset everything
/reset_health component:metrics   # Reset only metrics counters
/reset_health component:circuits  # Reset only circuit breakers
```

### `/log_health`
Manually triggers health status logging to system logs.

**Usage:**
```
/log_health
```

## Command Line Health Checker

The `calendar_health.py` script can be run standalone for monitoring:

**Basic usage:**
```bash
python calendar_health.py                    # Show current health status
python calendar_health.py --json            # Output as JSON
python calendar_health.py --watch           # Continuous monitoring
python calendar_health.py --quiet           # Only log to system, no console
```

**Examples:**
```bash
# Check health once
python calendar_health.py

# Get machine-readable output
python calendar_health.py --json

# Monitor continuously 
python calendar_health.py --watch

# Run in background, only log to system
python calendar_health.py --quiet
```

## Automatic Health Monitoring

The bot automatically:

1. **Tracks Metrics** - Monitors request success rates, error counts, processing times
2. **Circuit Breakers** - Temporarily skips failing calendar sources with exponential backoff
3. **Periodic Logging** - Logs health status every 30 minutes
4. **Alert Generation** - Creates alerts for critical issues

## Health Status Levels

- **Healthy** (✅) - Success rate ≥ 90%
- **Degraded** (⚠️) - Success rate 70-89%
- **Unhealthy** (❌) - Success rate < 70%
- **Unknown** (❓) - No recent activity

## Error Types Tracked

- **Network Errors** - Connection timeouts, SSL issues, DNS failures
- **Authentication Errors** - 401/403 HTTP responses, invalid credentials
- **Parsing Errors** - Malformed calendar data, DTSTART/DTEND issues
- **Server Errors** - 5xx HTTP responses from calendar providers

## Circuit Breaker Behavior

When a calendar source fails repeatedly:

1. **Failure Detection** - Tracks consecutive failures per source
2. **Exponential Backoff** - Delays retry attempts: 1min → 2min → 4min → ... → 1hr max
3. **Automatic Recovery** - Resets on successful operation
4. **Graceful Degradation** - Continues processing other sources

**Backoff Schedule:**
- 1st failure: Retry in 1 minute
- 2nd failure: Retry in 2 minutes  
- 3rd failure: Retry in 4 minutes
- 4th failure: Retry in 8 minutes
- 5th+ failures: Retry in 1 hour (max)

## Monitoring Integration

Health metrics can be integrated with external monitoring systems:

```python
from calendar_health import get_health_summary

health = get_health_summary()
print(f"Status: {health['status']}")
print(f"Success Rate: {health['metrics']['success_rate_percent']}%")
print(f"Active Alerts: {len(health['alerts'])}")
```

## Troubleshooting

### Common Issues and Solutions

**High Authentication Errors:**
- Check calendar URL credentials
- Verify API permissions
- Use `/reset_health component:circuits` to retry failed sources

**High Parsing Errors:**
- Calendar sources may have malformed data
- The bot automatically preprocesses and repairs common issues
- Check logs for specific parsing error details

**Network Errors:**
- May indicate connectivity issues
- Temporary server problems at calendar providers
- Circuit breakers will automatically retry with backoff

**Low Success Rate:**
- Check individual calendar source status with `/health detailed:True`
- Review recent log entries for specific error patterns
- Consider removing problematic calendar sources temporarily

### Log Analysis

Health events are logged with structured information:

```
[INFO] Calendar metrics (last 30.0min): 15/18 requests successful (83.3%), 42 events processed, 2 parse errors, 1 network errors, 0 auth errors, 1 circuits open
[WARNING] Circuit breakers active for 1 calendar sources
[INFO] Circuit breaker: https://example.com/calendar.ics - 3 failures, retry in 120s
```

Use log aggregation tools to track trends and set up alerts for critical issues.