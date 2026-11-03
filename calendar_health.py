"""
Calendar health reporting, used by the /health, /log_health and /calendars
commands and the periodic health monitor task. Metrics live in the bot
process's memory, so there is no standalone mode.
"""

from events import get_metrics_summary, get_circuit_breaker_status, log_metrics_summary
from log import logger

def get_health_summary() -> dict:
    """Get a summary of system health for programmatic use."""
    metrics = get_metrics_summary()
    breakers = get_circuit_breaker_status()
    
    # Determine overall health status
    if metrics['requests_total'] == 0:
        health_status = "unknown"
    elif metrics['success_rate_percent'] >= 90:
        health_status = "healthy"
    elif metrics['success_rate_percent'] >= 70:
        health_status = "degraded"
    else:
        health_status = "unhealthy"
    
    return {
        "status": health_status,
        "metrics": metrics,
        "circuit_breakers": breakers,
        "alerts": generate_alerts(metrics, breakers)
    }

def generate_alerts(metrics: dict, breakers: dict) -> list:
    """Generate health alerts based on current state."""
    alerts = []
    
    # Check success rate
    if metrics['requests_total'] > 0:
        if metrics['success_rate_percent'] < 50:
            alerts.append({
                "level": "critical",
                "message": f"Very low success rate: {metrics['success_rate_percent']}%"
            })
        elif metrics['success_rate_percent'] < 80:
            alerts.append({
                "level": "warning", 
                "message": f"Low success rate: {metrics['success_rate_percent']}%"
            })
    
    # Check error rates
    if metrics['parsing_errors'] > 10:
        alerts.append({
            "level": "warning",
            "message": f"High parsing error rate: {metrics['parsing_errors']} errors"
        })
    
    if metrics['network_errors'] > 5:
        alerts.append({
            "level": "warning",
            "message": f"Network connectivity issues: {metrics['network_errors']} errors"
        })
    
    if metrics['auth_errors'] > 0:
        alerts.append({
            "level": "error",
            "message": f"Authentication failures: {metrics['auth_errors']} calendars"
        })
    
    # Check circuit breaker status
    if len(breakers) > 2:
        alerts.append({
            "level": "warning",
            "message": f"Multiple calendar sources failing: {len(breakers)} circuit breakers active"
        })
    
    return alerts

def log_health_status():
    """Log health status using the logging system."""
    try:
        log_metrics_summary()
        
        # Log circuit breaker status if any are active
        breakers = get_circuit_breaker_status()
        if breakers:
            logger.warning(f"Circuit breakers active for {len(breakers)} calendar sources")
            for calendar_id, status in breakers.items():
                logger.info(f"Circuit breaker: {calendar_id[:30]}... - "
                          f"{status['failure_count']} failures, "
                          f"retry in {status['backoff_remaining_seconds']}s")
        
        # Log any critical alerts
        health = get_health_summary()
        critical_alerts = [a for a in health['alerts'] if a['level'] == 'critical']
        for alert in critical_alerts:
            logger.error(f"Calendar health alert: {alert['message']}")
            
    except Exception as e:
        logger.exception(f"Error logging health status: {e}")

def get_calendar_summary() -> dict:
    """Get a summary of all configured calendars and their status."""
    try:
        from events import GROUPED_CALENDARS, _calendar_breakers, _calendar_metadata_cache
        from datetime import datetime
        
        summary = {
            "total_calendars": 0,
            "healthy_calendars": 0,
            "failed_calendars": 0,
            "calendars_by_tag": {},
            "error_details": {}
        }
        
        for tag, calendars in GROUPED_CALENDARS.items():
            tag_summary = {
                "total": len(calendars),
                "healthy": 0,
                "failed": 0,
                "calendars": []
            }
            
            for cal in calendars:
                summary["total_calendars"] += 1
                cal_id = cal.get("id", "unknown")
                cal_name = cal.get("name", "Unknown")
                
                is_failed = False
                error_info = None
                
                # Check if calendar has validation errors
                if cal.get("error"):
                    is_failed = True
                    error_info = {
                        "type": cal.get("error_type", "unknown"),
                        "cached_at": cal.get("cached_at")
                    }
                
                # Check if calendar has circuit breaker active
                if cal_id in _calendar_breakers:
                    is_failed = True
                    failure_info = _calendar_breakers.get_failure_info(cal_id)
                    backoff_remaining = 0
                    if failure_info and failure_info.get("backoff_until", datetime.min) > datetime.now():
                        backoff_remaining = (failure_info["backoff_until"] - datetime.now()).total_seconds()
                    
                    error_info = {
                        "type": "circuit_breaker",
                        "failure_count": failure_info["count"] if failure_info else 0,
                        "last_failure": failure_info["last_failure"].isoformat() if failure_info else "",
                        "backoff_remaining": max(0, int(backoff_remaining))
                    }
                
                if is_failed:
                    summary["failed_calendars"] += 1
                    tag_summary["failed"] += 1
                    if error_info:
                        summary["error_details"][cal_id] = error_info
                else:
                    summary["healthy_calendars"] += 1
                    tag_summary["healthy"] += 1
                
                tag_summary["calendars"].append({
                    "id": cal_id[:50] + "..." if len(cal_id) > 50 else cal_id,
                    "name": cal_name,
                    "type": cal.get("type", "unknown"),
                    "status": "failed" if is_failed else "healthy",
                    "error": error_info
                })
            
            summary["calendars_by_tag"][tag] = tag_summary
        
        return summary
        
    except Exception as e:
        logger.exception(f"Error getting calendar summary: {e}")
        return {"error": str(e)}
