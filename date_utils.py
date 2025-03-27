from datetime import datetime, timedelta
import dateparser


def extract_date_range_from_query(query: str) -> tuple[datetime, datetime] | None:
    """
    Tries to extract a natural-language date or range from the query.
    Returns (start_datetime, end_datetime) in local timezone if found.
    Otherwise returns None.
    """
    parsed = dateparser.search.search_dates(
        query,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True
        }
    )

    if not parsed:
        return None

    now = datetime.now().astimezone()
    future_dates = [dt for _, dt in parsed if dt > now]

    if not future_dates:
        return None

    first = future_dates[0]
    if "weekend" in query.lower():
        # Return Saturday–Sunday of the detected week
        weekday = first.weekday()
        saturday = first + timedelta(days=(5 - weekday))
        sunday = saturday + timedelta(days=1)
        return (saturday.replace(hour=0, minute=0), sunday.replace(hour=23, minute=59))

    if "month" in query.lower():
        start_of_month = first.replace(day=1, hour=0, minute=0)
        if start_of_month.month == 12:
            end_of_month = start_of_month.replace(year=start_of_month.year + 1, month=1, day=1) - timedelta(seconds=1)
        else:
            end_of_month = start_of_month.replace(month=start_of_month.month + 1, day=1) - timedelta(seconds=1)
        return (start_of_month, end_of_month)

    # Default range: +/- 12 hours for specific day/time
    return (first - timedelta(hours=12), first + timedelta(hours=12))
