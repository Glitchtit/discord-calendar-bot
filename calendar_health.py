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

if __name__ == "__main__":
    """Run standalone health check."""
    try:
        print_health_status()
        
        # Also log to system logs
        log_health_status()
        
    except Exception as e:
        print(f"Error checking health: {e}")
        sys.exit(1)