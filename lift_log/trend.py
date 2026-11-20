"""Body-weight trend from daily weigh-ins. Pure functions, no Frappe, so they're easy to test.

Day-to-day weight swings by 0.5-1 kg with water, food and salt, so single weigh-ins are noise. A 7-day
average over at least MIN_WEIGH_INS weigh-ins is the number to watch, and the change between two
consecutive 7-day averages is the weekly rate.
"""

from datetime import date, timedelta

WINDOW_DAYS = 7
MIN_WEIGH_INS = 4


def _round(n: float, places: int = 2) -> float:
	return round(n + 0.0, places)


def window_average(
	weights: dict[date, float], end: date, days: int = WINDOW_DAYS
) -> tuple[float | None, int]:
	"""Mean of the weigh-ins in the `days` days ending on `end`, and how many there were.
	None when there are fewer than MIN_WEIGH_INS."""
	values = [weights[d] for d in (end - timedelta(days=i) for i in range(days)) if weights.get(d)]
	if len(values) < MIN_WEIGH_INS:
		return None, len(values)
	return _round(sum(values) / len(values)), len(values)


def summary(weights: dict[date, float], today: date) -> dict:
	"""The current 7-day average, the one before it, the weekly change in kg and in % of body weight."""
	current, count = window_average(weights, today)
	previous, _ = window_average(weights, today - timedelta(days=WINDOW_DAYS))
	change = _round(current - previous) if current is not None and previous is not None else None
	return {
		"avg_7d_kg": current,
		"weigh_ins_7d": count,
		"previous_avg_7d_kg": previous,
		"change_kg_per_week": change,
		"change_pct_per_week": _round(change / previous * 100, 2)
		if change is not None and previous
		else None,
	}


def rolling(weights: dict[date, float], start: date, end: date) -> list[dict]:
	"""One point per day from start to end: that day's weigh-in and the 7-day average ending on it."""
	out, day = [], start
	while day <= end:
		avg, _count = window_average(weights, day)
		out.append({"date": str(day), "weight_kg": weights.get(day), "avg_7d_kg": avg})
		day += timedelta(days=1)
	return out
