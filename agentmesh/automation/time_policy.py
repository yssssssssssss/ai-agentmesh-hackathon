from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, CroniterBadDateError, croniter


class ScheduleTimeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    scheduled_at: datetime
    local_slot: str


class CronSchedule:
    """Five-field wall-clock schedule; persisted slot identity is timezone/local minute."""

    def __init__(self, expression: str, timezone: str = "Asia/Shanghai"):
        self.expression = " ".join(expression.split())
        fields = self.expression.upper().split()
        names = {
            3: {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"},
            4: {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"},
        }
        if (
            len(fields) != 5
            or any(not re.fullmatch(r"[A-Z0-9*/,\-]+", field) for field in fields)
            or any(set(re.findall(r"[A-Z]+", field)) - names.get(index, set()) for index, field in enumerate(fields))
            or not croniter.is_valid(self.expression)
        ):
            raise ScheduleTimeError("schedule_cron_invalid")
        try:
            self.timezone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ScheduleTimeError("schedule_timezone_invalid") from None
        self._validate_frequency()

    def next_slot(self, after: datetime) -> ScheduleSlot:
        return self._find_slot(after, previous=False)

    def latest_slot(self, at: datetime) -> ScheduleSlot:
        return self._find_slot(at, previous=True)

    def _find_slot(self, boundary: datetime, *, previous: bool) -> ScheduleSlot:
        if boundary.utcoffset() is None:
            raise ScheduleTimeError("schedule_timezone_required")
        bound = boundary.astimezone(UTC)
        try:
            base = bound + timedelta(microseconds=1) if previous else bound
            iterator = croniter(self.expression, base.astimezone(self.timezone), day_or=True)
            for _ in range(4096):
                candidate = iterator.get_prev(datetime) if previous else iterator.get_next(datetime)
                local = candidate.replace(fold=0)
                instant = local.astimezone(UTC)
                # croniter shifts nonexistent times and emits both folds. Only
                # an actual matching wall minute's first instant is eligible.
                if (
                    (instant > bound if previous else instant <= bound)
                    or instant.astimezone(self.timezone).replace(tzinfo=None) != local.replace(tzinfo=None)
                    # Matching an aware time lets croniter treat a shifted DST
                    # candidate as a match. Check its exact wall fields instead.
                    or not croniter.match(self.expression, local.replace(tzinfo=None), day_or=True)
                ):
                    continue
                return ScheduleSlot(
                    scheduled_at=instant,
                    local_slot=f"{self.timezone.key}:{local.strftime('%Y-%m-%dT%H:%M')}",
                )
        except (CroniterBadCronError, CroniterBadDateError):
            raise ScheduleTimeError("schedule_cron_unreachable") from None
        raise ScheduleTimeError("schedule_slot_search_limit")

    def _validate_frequency(self) -> None:
        expanded, _ = croniter.expand(self.expression)
        minutes = range(60) if expanded[0] == ["*"] else expanded[0]
        hours = range(24) if expanded[1] == ["*"] else expanded[1]
        daily_slots = sorted(hour * 60 + minute for hour in hours for minute in minutes)
        if any(right - left < 5 for left, right in zip(daily_slots, daily_slots[1:], strict=False)):
            raise ScheduleTimeError("schedule_frequency_too_high")
        if 1440 - daily_slots[-1] + daily_slots[0] >= 5:
            return
        # A short midnight gap matters only when both adjacent dates are valid.
        # Numeric cron calendars repeat over the 400-year Gregorian cycle.
        days = None if expanded[2] == ["*"] else set(expanded[2])
        months = None if expanded[3] == ["*"] else set(expanded[3])
        weekdays = None if expanded[4] == ["*"] else set(expanded[4])
        current = date(2000, 1, 1)
        prior_allowed = False
        for _ in range(146098):
            weekday_match = weekdays is None or (current.weekday() + 1) % 7 in weekdays
            day_match = days is None or current.day in days
            day_allowed = (
                weekday_match if days is None else day_match if weekdays is None else day_match or weekday_match
            )
            allowed = (months is None or current.month in months) and day_allowed
            if allowed and prior_allowed:
                raise ScheduleTimeError("schedule_frequency_too_high")
            prior_allowed = allowed
            current += timedelta(days=1)
