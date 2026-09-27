"""Pull daily fitness data from Garmin Connect into the fitness database
(data/fitness.db) - the same table trainer.fitness_data reads from.

Run: python scripts/garmin.py --days 30
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garminconnect import Garmin

from trainer.config import settings


def _fetch_day(client: Garmin, date_str: str) -> dict:
    row = {"date": date_str}

    try:
        stats = client.get_stats(date_str) or {}
        if stats.get("totalSteps") is not None:
            row["steps"] = stats["totalSteps"]
    except Exception as e:
        print(f"  steps: skipped ({e})")

    try:
        sleep = client.get_sleep_data(date_str) or {}
        sleep_seconds = (sleep.get("dailySleepDTO") or {}).get("sleepTimeSeconds")
        if sleep_seconds is not None:
            row["sleep_hours"] = round(sleep_seconds / 3600, 2)
    except Exception as e:
        print(f"  sleep: skipped ({e})")

    try:
        weigh_ins = (client.get_daily_weigh_ins(date_str) or {}).get("dateWeightList") or []
        if weigh_ins:
            row["weight_kg"] = round(weigh_ins[-1]["weight"] / 1000, 2)
    except Exception as e:
        print(f"  weight: skipped ({e})")

    try:
        activities = client.get_activities_by_date(date_str, date_str) or []
        row.update(_summarize_activities(activities))
    except Exception as e:
        print(f"  workouts: skipped ({e})")

    return row


def _summarize_activities(activities: list[dict]) -> dict:
    """Collapse a day's activities into one row - summed duration/calories/
    distance, average of the per-activity average heart rates, and the max
    of the per-activity max heart rates."""
    types, avg_hrs, max_hrs = [], [], []
    total_duration_s = total_calories = total_distance_m = 0.0

    for activity in activities:
        type_key = (activity.get("activityType") or {}).get("typeKey")
        if type_key and type_key not in types:
            types.append(type_key)
        total_duration_s += activity.get("duration") or 0
        total_calories += activity.get("calories") or 0
        total_distance_m += activity.get("distance") or 0
        if activity.get("averageHR") is not None:
            avg_hrs.append(activity["averageHR"])
        if activity.get("maxHR") is not None:
            max_hrs.append(activity["maxHR"])

    summary = {}
    if types:
        summary["activity_type"] = "+".join(types)
    if total_duration_s:
        summary["duration_min"] = round(total_duration_s / 60, 1)
    if total_calories:
        summary["calories"] = round(total_calories)
    if total_distance_m:
        summary["distance_km"] = round(total_distance_m / 1000, 2)
    if avg_hrs:
        summary["avg_hr"] = round(sum(avg_hrs) / len(avg_hrs))
    if max_hrs:
        summary["max_hr"] = max(max_hrs)
    return summary


def _upsert(conn: sqlite3.Connection, row: dict) -> None:
    columns = [c for c in row if c != "date"]
    if not columns:
        return
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in columns)
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO daily_log (date, {column_list}) VALUES (?, {placeholders}) "
        f"ON CONFLICT(date) DO UPDATE SET {update_clause}",
        (row["date"], *(row[c] for c in columns)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Garmin Connect data into the fitness database.")
    parser.add_argument("--days", type=int, default=1, help="How many days back to fetch (default: 1, today only).")
    args = parser.parse_args()

    if not settings.garmin_email or not settings.garmin_password:
        raise SystemExit("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")

    client = Garmin(settings.garmin_email, settings.garmin_password)
    client.login()

    settings.fitness_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.fitness_db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_log (
            date TEXT PRIMARY KEY,
            steps INTEGER,
            sleep_hours REAL,
            weight_kg REAL,
            activity_type TEXT,
            duration_min REAL,
            calories INTEGER,
            distance_km REAL,
            avg_hr INTEGER,
            max_hr INTEGER
        )"""
    )

    today = datetime.date.today()
    for i in range(args.days):
        date_str = (today - datetime.timedelta(days=i)).isoformat()
        print(date_str)
        row = _fetch_day(client, date_str)
        _upsert(conn, row)
        conn.commit()
        print(f"  saved: {row}")

    conn.close()


if __name__ == "__main__":
    main()
