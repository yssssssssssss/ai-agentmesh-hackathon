from datetime import UTC, datetime

import pytest

from agentmesh.automation.time_policy import CronSchedule, ScheduleTimeError


def test_next_occurrence_is_a_utc_instant_with_a_stable_local_slot():
    schedule = CronSchedule("30 9 * * *", "Asia/Shanghai")
    slot = schedule.next_slot(datetime(2026, 10, 4, 0, 0, tzinfo=UTC))
    assert slot.scheduled_at == datetime(2026, 10, 4, 1, 30, tzinfo=UTC)
    assert slot.local_slot == "Asia/Shanghai:2026-10-04T09:30"


def test_day_of_month_and_weekday_use_or_semantics():
    schedule = CronSchedule("0 9 1 * MON", "Asia/Shanghai")
    assert schedule.next_slot(datetime(2026, 10, 1, 2, tzinfo=UTC)).scheduled_at == datetime(2026, 10, 5, 1, tzinfo=UTC)


def test_nonexistent_spring_slot_is_skipped_instead_of_shifted():
    schedule = CronSchedule("30 2 * * *", "America/New_York")
    assert schedule.next_slot(datetime(2026, 3, 7, 8, tzinfo=UTC)).scheduled_at == datetime(
        2026, 3, 9, 6, 30, tzinfo=UTC
    )


def test_repeated_fall_slot_occurs_only_at_its_first_instant():
    schedule = CronSchedule("30 1 * * *", "America/New_York")
    first = schedule.next_slot(datetime(2026, 11, 1, 5, 15, tzinfo=UTC))
    assert first.scheduled_at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    after_first = schedule.next_slot(datetime(2026, 11, 1, 5, 45, tzinfo=UTC))
    assert after_first.scheduled_at == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    assert after_first.local_slot != first.local_slot


def test_naive_time_is_rejected():
    with pytest.raises(ValueError, match="schedule_timezone_required"):
        CronSchedule("*/5 * * * *").next_slot(datetime(2026, 10, 4))


@pytest.mark.parametrize("expression", ["* * * * *", "*/2 * * * *", "0,4 9 * * *", "59,0 23,0 * * *"])
def test_sub_five_minute_schedules_are_rejected(expression):
    with pytest.raises(ScheduleTimeError, match="schedule_frequency_too_high"):
        CronSchedule(expression)


@pytest.mark.parametrize("expression", ["@daily", "0 0 0 * * *", "0 0 * * * 2027", "61 9 * * *", "R 9 * * *"])
def test_invalid_or_nondeterministic_cron_is_rejected(expression):
    with pytest.raises(ScheduleTimeError, match="schedule_cron_invalid"):
        CronSchedule(expression)


def test_invalid_timezone_is_rejected():
    with pytest.raises(ScheduleTimeError, match="schedule_timezone_invalid"):
        CronSchedule("30 9 * * *", "not-a-timezone")


def test_latest_due_slot_coalesces_missed_days_and_includes_an_exact_slot():
    schedule = CronSchedule("30 9 * * *")
    now = datetime(2026, 10, 4, 1, 30, tzinfo=UTC)
    assert schedule.latest_slot(now).scheduled_at == now
    assert schedule.latest_slot(datetime(2026, 10, 4, 1, 29, tzinfo=UTC)).scheduled_at == datetime(
        2026, 10, 3, 1, 30, tzinfo=UTC
    )


def test_weekly_near_midnight_slots_do_not_invent_an_adjacent_day():
    schedule = CronSchedule("0,59 0,23 * * MON")
    assert schedule.next_slot(datetime(2026, 10, 5, 23, 59, tzinfo=UTC)).scheduled_at == datetime(
        2026, 10, 11, 16, tzinfo=UTC
    )


def test_latest_slot_during_the_second_fold_refers_to_the_first_fold():
    schedule = CronSchedule("30 1 * * *", "America/New_York")
    assert schedule.latest_slot(datetime(2026, 11, 1, 6, 45, tzinfo=UTC)).scheduled_at == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_latest_slot_does_not_shift_a_nonexistent_spring_time():
    schedule = CronSchedule("30 2 * * *", "America/New_York")
    assert schedule.latest_slot(datetime(2026, 3, 8, 8, tzinfo=UTC)).scheduled_at == datetime(
        2026, 3, 7, 7, 30, tzinfo=UTC
    )
