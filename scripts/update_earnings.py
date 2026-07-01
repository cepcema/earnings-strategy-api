import datetime as dt
import json
import logging
import os
import time
import traceback

import yfinance as yf


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

OUTPUT_DIR = "docs/data"
HISTORY_DIR = "docs/data/history"

SLEEP_SECONDS_BETWEEN_TICKERS = 0.4

TICKERS = [
    {"label": "AAPL", "symbol": "AAPL", "country": "United States"},
    {"label": "MSFT", "symbol": "MSFT", "country": "United States"},
    {"label": "NVDA", "symbol": "NVDA", "country": "United States"},
    {"label": "TSLA", "symbol": "TSLA", "country": "United States"},
    {"label": "JPM", "symbol": "JPM", "country": "United States"},

    {"label": "BHP", "symbol": "BHP.AX", "country": "Australia"},
    {"label": "WES", "symbol": "WES.AX", "country": "Australia"},
    {"label": "NAB", "symbol": "NAB.AX", "country": "Australia"},
    {"label": "CBA", "symbol": "CBA.AX", "country": "Australia"},

    {"label": "NOKIA", "symbol": "NOKIA.HE", "country": "Finland"},
    {"label": "NESTE", "symbol": "NESTE.HE", "country": "Finland"},

    {"label": "LVMH", "symbol": "MC.PA", "country": "France"},
    {"label": "OREP", "symbol": "OR.PA", "country": "France"},
    {"label": "HRMS", "symbol": "RMS.PA", "country": "France"},
    {"label": "BNPP", "symbol": "BNP.PA", "country": "France"},

    {"label": "UCG", "symbol": "UCG.MI", "country": "Italy"},
    {"label": "STLA", "symbol": "STLA.MI", "country": "Italy"},
    {"label": "AIR", "symbol": "AIR.PA", "country": "France"},
]


def utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def previous_trading_day(day: dt.date) -> dt.date:
    d = day - dt.timedelta(days=1)

    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)

    return d


def next_trading_day(day: dt.date) -> dt.date:
    d = day + dt.timedelta(days=1)

    while d.weekday() >= 5:
        d += dt.timedelta(days=1)

    return d


def normalize_date(value):
    if value is None:
        return None

    if isinstance(value, dt.datetime):
        return value.date()

    if isinstance(value, dt.date):
        return value

    if isinstance(value, str):
        raw = value.strip()

        if not raw:
            return None

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return dt.datetime.strptime(raw[:19], fmt).date()
            except Exception:
                pass

        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except Exception:
            return None

    return None


def extract_earnings_date_from_calendar(calendar_value, previous_day: dt.date):
    if not calendar_value:
        return None

    earnings_value = None

    if isinstance(calendar_value, dict):
        earnings_value = (
            calendar_value.get("Earnings Date")
            or calendar_value.get("Earnings Dates")
            or calendar_value.get("earningsDate")
            or calendar_value.get("earnings_date")
        )

    if earnings_value is None:
        return None

    if isinstance(earnings_value, (list, tuple, set)):
        dates = [normalize_date(x) for x in earnings_value]
    else:
        dates = [normalize_date(earnings_value)]

    dates = [x for x in dates if x is not None]

    if not dates:
        return None

    relevant_dates = [x for x in dates if x >= previous_day]

    if relevant_dates:
        return min(relevant_dates)

    return max(dates)


def get_earnings_date(label: str, symbol: str, previous_day: dt.date):
    try:
        ticker = yf.Ticker(symbol)
        calendar = ticker.calendar

        earnings_date = extract_earnings_date_from_calendar(
            calendar_value=calendar,
            previous_day=previous_day,
        )

        if earnings_date:
            return earnings_date, "yfinance_calendar", "ok"

        return None, "yfinance_calendar_no_date", "no_earnings_date"

    except Exception as e:
        logging.error("Error getting earnings date for %s %s: %s", label, symbol, str(e))
        logging.error(traceback.format_exc())
        return None, "yfinance_calendar_error", str(e)[:300]


def build_signal(
    earnings_date,
    previous_day: dt.date,
    run_date: dt.date,
    next_day: dt.date,
):
    if earnings_date is None:
        return "NO_ACTION", False, False, False, "no_earnings_date"

    if earnings_date == previous_day:
        return "OPEN_TRADE", True, False, False, "earnings_previous_trading_day"

    if earnings_date == run_date:
        return "KEEP_CLOSED", False, True, False, "earnings_today"

    if earnings_date == next_day:
        return "CLOSE_ONLY", False, False, True, "earnings_next_trading_day"

    return "NO_ACTION", False, False, False, "earnings_not_in_signal_window"


def build_row(
    item,
    run_date: dt.date,
    previous_day: dt.date,
    next_day: dt.date,
    run_datetime: str,
    created_at: str,
):
    label = item["label"]
    symbol = item["symbol"]
    country = item.get("country", "")

    earnings_date, source, note = get_earnings_date(
        label=label,
        symbol=symbol,
        previous_day=previous_day,
    )

    signal, is_open_trade, is_keep_closed, is_close_only, signal_note = build_signal(
        earnings_date=earnings_date,
        previous_day=previous_day,
        run_date=run_date,
        next_day=next_day,
    )

    final_note = signal_note if note == "ok" else note

    return {
        "run_date": run_date.isoformat(),
        "run_datetime": run_datetime,
        "label": label,
        "symbol": symbol,
        "country": country,
        "earnings_date": earnings_date.isoformat() if earnings_date else None,
        "earnings_date_source": source,
        "signal": signal,
        "is_open_trade": is_open_trade,
        "is_keep_closed": is_keep_closed,
        "is_close_only": is_close_only,
        "previous_trading_day": previous_day.isoformat(),
        "today_trading_day": run_date.isoformat(),
        "next_trading_day": next_day.isoformat(),
        "note": final_note,
        "created_at": created_at,
    }


def write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run():
    run_date = dt.datetime.utcnow().date()
    previous_day = previous_trading_day(run_date)
    next_day = next_trading_day(run_date)

    run_datetime = utc_now_iso()
    created_at = run_datetime

    logging.info("EARNINGS CALENDAR GITHUB RUN")
    logging.info("yfinance version: %s", yf.__version__)
    logging.info("Run date: %s", run_date.isoformat())
    logging.info("Previous trading day: %s", previous_day.isoformat())
    logging.info("Next trading day: %s", next_day.isoformat())
    logging.info("Tickers to process: %s", len(TICKERS))

    rows = []

    for index, item in enumerate(TICKERS, start=1):
        logging.info(
            "Processing %s/%s: %s %s",
            index,
            len(TICKERS),
            item["label"],
            item["symbol"],
        )

        row = build_row(
            item=item,
            run_date=run_date,
            previous_day=previous_day,
            next_day=next_day,
            run_datetime=run_datetime,
            created_at=created_at,
        )

        logging.info("Row: %s", row)
        rows.append(row)

        if SLEEP_SECONDS_BETWEEN_TICKERS > 0:
            time.sleep(SLEEP_SECONDS_BETWEEN_TICKERS)

    signal_counts = {}

    for row in rows:
        signal_counts[row["signal"]] = signal_counts.get(row["signal"], 0) + 1

    output = {
        "ok": True,
        "run_date": run_date.isoformat(),
        "run_datetime": run_datetime,
        "previous_trading_day": previous_day.isoformat(),
        "today_trading_day": run_date.isoformat(),
        "next_trading_day": next_day.isoformat(),
        "yfinance_version": yf.__version__,
        "rows_count": len(rows),
        "signal_counts": signal_counts,
        "rows": rows,
    }

    write_json(f"{OUTPUT_DIR}/current.json", output)
    write_json(f"{HISTORY_DIR}/{run_date.isoformat()}.json", output)

    logging.info("Signal counts: %s", signal_counts)
    logging.info("Wrote %s/current.json", OUTPUT_DIR)
    logging.info("Wrote %s/%s.json", HISTORY_DIR, run_date.isoformat())
    logging.info("DONE")


if __name__ == "__main__":
    run()
