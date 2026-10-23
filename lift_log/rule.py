"""The add-weight rule (docs/01), ported from the app's nextCall() for the weekly review's rule_call.

Both implementations run the same test table (lift_log/tests/rule_cases.json, a copy of the app's
src/lib/__tests__/nextCall.cases.json). Change them together.
"""

import math
import re

GYM_TYPES = ("load", "distance")


def parse_rep_range(reps: str):
	"""'6-8' -> (6, 8); '5' -> (5, 5); 'max' -> None."""
	match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*", str(reps or ""))
	if not match:
		return None
	a = float(match.group(1))
	return a, float(match.group(2)) if match.group(2) else a


def _r2(n: float) -> float:
	return round(n * 100) / 100


def _fmt(n: float) -> str:
	return str(int(n)) if float(n).is_integer() else str(_r2(n))


def _top(session) -> float:
	return max([0.0, *[(s.get("kg") or 0) for s in session["sets"]]])


def _work(session, kg) -> list:
	return [s for s in session["sets"] if (s.get("kg") or 0) == kg]


def _step_up(w: float, inc: float) -> float:
	"""The next weight the equipment has: the smallest multiple of inc above w."""
	if inc <= 0:
		return _r2(w)
	return _r2((math.floor(w / inc + 1e-9) + 1) * inc)


def _step_down(w: float, inc: float) -> float:
	"""The largest multiple of inc below w, not below 0."""
	if inc <= 0:
		return _r2(w)
	return max(_r2((math.ceil(w / inc - 1e-9) - 1) * inc), 0)


def _snap(kg: float, inc: float) -> float:
	"""The nearest multiple of inc (halves round up, like the app's Math.round)."""
	return _r2(math.floor(kg / inc + 0.5) * inc) if inc > 0 else _r2(kg)


def _big_step(w: float, inc: float) -> bool:
	"""A step of more than 10% of the weight (dumbbells 5 -> 7.5 kg is +50%)."""
	return w > 0 and inc > w * 0.1


_EFFORT_RANK = {"easy": 1, "right": 2, "hard": 3}


def weaker_side(sets: list) -> list:
	"""Per-side sets (side L and R sharing a set_no) become one set judged on the weaker side:
	the lower kg, the lower amount and the harder effort. Sets without a side pass through."""
	out, by_set_no = [], {}
	for s in sets:
		if s.get("side") not in ("L", "R"):
			out.append(s)
			continue
		pair = by_set_no.get(s.get("set_no"))
		if pair is None:
			pair = {"kg": s.get("kg"), "amount": s["amount"], "effort": s.get("effort")}
			by_set_no[s.get("set_no")] = pair
			out.append(pair)
			continue
		if s.get("kg") is not None:
			pair["kg"] = s["kg"] if pair["kg"] is None else min(pair["kg"], s["kg"])
		pair["amount"] = min(pair["amount"], s["amount"])
		efforts = [e for e in (pair["effort"], s.get("effort")) if e]
		pair["effort"] = max(efforts, key=_EFFORT_RANK.get) if efforts else None
	return out


def next_call(exercise: dict, target: dict, history: list, review_delta_kg: float = 0) -> dict:
	"""exercise: {type, increment_kg}; target: {sets, reps, test?, startingKg?};
	history: earlier sessions with this exercise, newest first: [{date, deload?, sets: [{kg, amount, effort, side?, set_no?}]}].
	Per-side sets are judged on the weaker side (weaker_side)."""
	is_gym = exercise["type"] in GYM_TYPES
	sessions = [
		{**s, "sets": weaker_side(s["sets"])} for s in history if s["sets"] and not (is_gym and s.get("deload"))
	]

	# 1. Test routine.
	if target.get("test"):
		best = max([0.0, *[_top(s) for s in sessions]])
		if best:
			return {"call": "test", "kg": best, "reason": f"Work up past {_fmt(best)} kg if it moves well"}
		return {"call": "test", "reason": "Work up to your heaviest clean 5"}

	# 2. Bodyweight, time, or a "max" target.
	rng = parse_rep_range(target["reps"])
	if not is_gym or rng is None:
		if sessions:
			amounts = ", ".join(_fmt(s["amount"]) for s in sessions[0]["sets"])
			return {"call": "bodyweight", "reason": f"Beat last time: {amounts}"}
		return {"call": "bodyweight", "reason": "Beat last time"}

	result = _weight_call(exercise, target, rng, sessions)
	if review_delta_kg and "kg" in result:
		kg = max(_snap(result["kg"] + review_delta_kg, exercise["increment_kg"]), 0)
		return {"call": result["call"], "kg": kg, "reason": "From your weekly review"}
	return result


def _weight_call(exercise, target, rng, sessions):
	a, b = rng
	# 3. No history.
	if not sessions:
		start = target.get("startingKg")
		if start:
			return {"call": "start", "kg": start, "reason": f"Start around {_fmt(start)} kg"}
		return {"call": "start", "reason": "Pick a weight you can do with clean form"}

	inc = exercise["increment_kg"]
	w = _top(sessions[0])
	work = _work(sessions[0], w)

	# 4. Every work set at the top of the range.
	if len(work) >= target["sets"] and all(s["amount"] >= b for s in work):
		return {"call": "up", "kg": _step_up(w, inc), "reason": "Hit the top of the range"}

	at_w = [s for s in sessions if _top(s) == w][:2]
	if len(at_w) == 2:
		# 5 is skipped on a big step: stay and build reps to the top of the range first.
		big = _big_step(w, inc)
		# 5. Felt easy two sessions running.
		def easy(s):
			sets = _work(s, w)
			easy_count = sum(1 for x in sets if x.get("effort") == "easy")
			return (
				bool(sets)
				and all(x["amount"] >= a for x in sets)
				and easy_count * 3 >= len(sets) * 2
				and not any(x.get("effort") == "hard" for x in sets)
			)

		if not big and all(easy(s) for s in at_w):
			return {"call": "up", "kg": _step_up(w, inc), "reason": "Felt easy two sessions running"}

		# 6. Struggling two sessions running.
		def hard(s):
			sets = _work(s, w)
			hard_count = sum(1 for x in sets if x.get("effort") == "hard")
			short_count = sum(1 for x in sets if x["amount"] < a)
			return bool(sets) and hard_count * 2 >= len(sets) and short_count * 2 >= len(sets)

		if all(hard(s) for s in at_w):
			return {"call": "down", "kg": _step_down(w, inc), "reason": "Two hard sessions: drop a step and rebuild"}

	# 7. Otherwise hold.
	return {"call": "hold", "kg": w, "reason": "Beat your reps"}
