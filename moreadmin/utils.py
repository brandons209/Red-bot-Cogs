def parse_seconds(seconds: int) -> str:
    """
    Take seconds and converts it to larger units
    Returns parsed message string
    """
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    weeks, days = divmod(days, 7)
    months, weeks = divmod(weeks, 4)
    msg = []

    if months:
        msg.append(f"{int(months)} {'months' if months > 1 else 'month'}")
    if weeks:
        msg.append(f"{int(weeks)} {'weeks' if weeks > 1 else 'week'}")
    if days:
        msg.append(f"{int(days)} {'days' if days > 1 else 'day'}")
    if hours:
        msg.append(f"{int(hours)} {'hours' if hours > 1 else 'hour'}")
    if minutes:
        msg.append(f"{int(minutes)} {'minutes' if minutes > 1 else 'minute'}")
    if seconds:
        msg.append(f"{int(seconds)} {'seconds' if seconds > 1 else 'second'}")

    return ", ".join(msg)
