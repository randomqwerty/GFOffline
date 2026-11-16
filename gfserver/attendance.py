"""Daily sign-in (Index/attendance).

Reply (HomeEventController$$RequestAttendanceInfoHandle):
  {"user_record_up": {"seven_type", "seven_start_time", "seven_spend_point", "seven_attendance_days",
                      "attendance_type1_day", "attendance_type1_time"},
   "attendance_type1": [this month's calendar: {"day", "start_time", "end_time", "attendance_type", "prize_id"}],
   "attendant1": {"attendance_type1_day", "attendance_type1_time"} when today's sign-in was granted, else []}
The client reads the new day and next due time from attendant1 itself (a list there throws, so the
next due time never reached the client and the sign-in window opened on every home visit).
The client asks again on every home visit while its calendar list is empty
(HomeEventController$$CheckAttendanceInfoList), so the calendar is always sent; the
reward is granted only once per server day. attendance_type1_time is when the next
sign-in is due (the start of the next server day): the client copies it to
UserRecord.nextAttendanceType1Time, and Data$$NeedsAttendance opens the sign-in window at
login while that time has passed. (Saves written before 2026-10-30 kept the start of the
sign-in day instead; they are moved on one day once, flagged by user_record._attendance_next.)
"""
import datetime
import logging
import time

from . import stc

log = logging.getLogger("gfserver.attendance")

# Same day boundary as handlers._server_clock: the EN server rolls over at 00:00 UTC-8.
SERVER_DAY_TZ = datetime.timezone(datetime.timedelta(hours=-8))


def _calendar(local, kind="1"):
    stamp = local.strftime("%Y-%m-%d %H:%M:%S")
    rows = [r for r in stc.catch("attendance_info")
            if r["attendance_type"] == kind and r["start_time"] <= stamp <= r["end_time"]]
    return sorted(rows, key=lambda r: int(r["day"]))


def _reward(r):
    """A day's reward: its prize package when it names one, else the row's own fields."""
    from . import quests
    if int(r.get("prize_id") or 0):
        return quests._reward(quests.prizes().get(int(r["prize_id"]), {}))
    return quests._reward(r)


def _client_row(r):
    """A calendar day. With prize_id 0 the client reads the reward from the row itself
    (AttendanceInfo$$.ctor: Package$$.ctor on the row; else the prize table by prize_id), so the
    row carries its fields (player report: the monthly sign-in showed no rewards without them)."""
    out = {"day": int(r["day"]), "start_time": r["start_time"], "end_time": r["end_time"],
           "attendance_type": int(r["attendance_type"]), "prize_id": int(r["prize_id"] or 0)}
    if not out["prize_id"]:
        out.update(_reward(r))
    return out


def _migrate(rec):
    """Older saves stored the start of the sign-in day; the client wants the next due time."""
    if not rec.get("_attendance_next"):
        if int(rec.get("attendance_type1_time") or 0):
            rec["attendance_type1_time"] = int(rec["attendance_type1_time"]) + 86400
        rec["_attendance_next"] = 1


def attendance(state, body, now=None):
    now = now or int(time.time())
    local = datetime.datetime.fromtimestamp(now, SERVER_DAY_TZ)
    today = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    rec = state.setdefault("user_record", {})
    _migrate(rec)
    calendar = _calendar(local)
    due = int(rec.get("attendance_type1_time") or 0)
    day = int(rec.get("attendance_type1_day") or 0)
    got = []
    if due <= now and calendar:
        last_local = datetime.datetime.fromtimestamp(max(0, due - 86400), SERVER_DAY_TZ)
        day = day + 1 if (last_local.year, last_local.month) == (local.year, local.month) else 1
        row = next((r for r in calendar if int(r["day"]) == day), None)
        rec["attendance_type1_day"], rec["attendance_type1_time"] = day, today + 86400
        if row is not None:
            from . import quests
            quests.grant(state, _reward(row))
            got = {"attendance_type1_day": day, "attendance_type1_time": today + 86400}
    up = {
        "seven_type": int(rec.get("seven_type") or 0),
        "seven_start_time": int(rec.get("seven_start_time") or 0),
        "seven_spend_point": float(rec.get("seven_spend_point") or 0),
        "seven_attendance_days": str(rec.get("seven_attendance_days") or ""),
        "attendance_type1_day": int(rec.get("attendance_type1_day") or 0),
        "attendance_type1_time": int(rec.get("attendance_type1_time") or 0),
    }
    return {"user_record_up": up, "attendance_type1": [_client_row(r) for r in calendar], "attendant1": got}
