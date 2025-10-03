#!/usr/bin/env python3
"""
Calendar Health Monitoring Utility

This script provides functions to monitor calendar processing health and can be
imported by other modules or run standalone to check current status.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from events import get_metrics_summary, get_circuit_breaker_status, log_metrics_summary
from log import logger

def print_health_status():
    """Print detailed health status to console."""
    print("=" * 60)
    print("Calendar System Health Status")
    print("=" * 60)
    
    # Get metrics
    metrics = get_metrics_summary()
    print(f"\n📊 Processing Metrics (last {metrics['duration_minutes']:.1f} minutes):")
    print(f"   Total requests: {metrics['requests_total']}")
    print(f"   Successful: {metrics['requests_successful']}")
    print(f"   Failed: {metrics['requests_failed']}")
    print(f"   Success rate: {metrics['success_rate_percent']}%")
    print(f"   Events processed: {metrics['events_processed']}")
    
    print(f"\n⚠️  Error Breakdown:")
    print(f"   Parsing errors: {metrics['parsing_errors']}")
    print(f"   Network errors: {metrics['network_errors']}")
    print(f"   Auth errors: {metrics['auth_errors']}")
    
    # Get circuit breaker status
    breakers = get_circuit_breaker_status()
    print(f"\n🚫 Circuit Breakers ({len(breakers)} active):")
    if not breakers:
        print("   ✅ No circuit breakers active - all calendars operational")
    else:
        for calendar_id, status in breakers.items():
            backoff_min = status['backoff_remaining_seconds'] / 60
            print(f"   🔴 {calendar_id[:50]}...")
            print(f"      Failures: {status['failure_count']}")
            print(f"      Last failure: {status['last_failure']}")
            print(f"      Retry in: {backoff_min:.1f} minutes")
    
    print("\n" + "=" * 60)

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
        from events import GROUPED_CALENDARS, _failed_calendars, _calendar_metadata_cache
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
                if cal_id in _failed_calendars:
                    is_failed = True
                    failure_info = _failed_calendars[cal_id]
                    backoff_remaining = 0
                    if failure_info.get("backoff_until", datetime.min) > datetime.now():
                        backoff_remaining = (failure_info["backoff_until"] - datetime.now()).total_seconds()
                    
                    error_info = {
                        "type": "circuit_breaker",
                        "failure_count": failure_info["count"],
                        "last_failure": failure_info["last_failure"].isoformat(),
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

if __name__ == "__main__":
    """Run standalone health check."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Calendar Health Monitor")
    parser.add_argument("--json", action="store_true", help="Output health data as JSON")
    parser.add_argument("--watch", action="store_true", help="Continuously monitor health (every 60s)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only log to system logs, no console output")
    
    args = parser.parse_args()
    
    try:
        if args.watch:
            print("Starting continuous health monitoring (press Ctrl+C to stop)...")
            import time
            while True:
                if not args.quiet:
                    from datetime import datetime
                    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                    if args.json:
                        import json
                        health = get_health_summary()
                        print(json.dumps(health, indent=2, default=str))
                    else:
                        print_health_status()
                
                log_health_status()
                time.sleep(60)
        
        elif args.json:
            import json
            health = get_health_summary()
            print(json.dumps(health, indent=2, default=str))
        
        elif not args.quiet:
            print_health_status()
        
        # Always log to system logs unless specifically requested not to
        if not args.quiet:
            log_health_status()
        
    except KeyboardInterrupt:
        if args.watch:
            print("\nHealth monitoring stopped.")
        sys.exit(0)
    except Exception as e:
        print(f"Error checking health: {e}")
        sys.exit(1)