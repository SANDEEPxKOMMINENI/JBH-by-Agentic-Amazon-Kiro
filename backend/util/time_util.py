from datetime import datetime, timedelta

from dateutil import parser, tz
from dateutil.tz import gettz

tzinfos = {
    "EDT": tz.gettz("America/New_York"),
    "EST": tz.gettz("America/New_York"),
    "PDT": tz.gettz("America/Los_Angeles"),
    "PST": tz.gettz("America/Los_Angeles"),
    # Add more as needed
}


def get_current_time_str_by_local_tz(
    format: str = "%m-%d %H:%M:%S %Z",
):
    return datetime.now().strftime(format)


def get_current_time_str(
    format: str = "%Y-%m-%d %H:%M:%S %Z", tz: str = "America/New_York"
):
    return datetime.now(gettz(tz)).strftime(format)


def turn_time_str_to_ts(time_str: str, tz: str = "America/New_York"):
    dt = parser.parse(time_str, tzinfos=tzinfos)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=gettz(tz))
    return dt.astimezone(gettz(tz)).timestamp()


def turn_ts_to_time_str(
    ts: float, format: str = "%Y-%m-%d %H:%M:%S %Z", tz: str = "America/New_York"
):
    return datetime.fromtimestamp(ts, gettz(tz)).strftime(format)


def get_current_timestamp(tz: str = "America/New_York"):
    return datetime.now(gettz(tz)).timestamp()


def get_future_timestamp_by_delta_minutes(minutes: int, tz: str = "America/New_York"):
    return int(datetime.now(gettz(tz)).timestamp() + minutes * 60)


def get_refresh_time_by_delta_minutes(
    hr=8, min=0, format="%Y-%m-%d %H:%M:%S %Z", tz: str = "America/New_York"
):
    now = datetime.now(gettz(tz))
    next_hr_min = now.replace(hour=hr, minute=min, second=0, microsecond=0)
    if next_hr_min < now:
        next_hr_min += timedelta(days=1)
    return next_hr_min.strftime(format)


def turn_time_period_s_to_str(s: int):
    if s < 60:
        return f"{s:.1f}s"
    elif s < 3600:
        return f"{s / 60:.1f}m"
    else:
        return f"{s / 3600:.1f}h"
