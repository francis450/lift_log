"""The add-weight rule (docs/01), ported from the app's nextCall() for the weekly review's rule_call.

Both implementations run the same test table (lift_log/tests/rule_cases.json, a copy of the app's
src/lib/__tests__/nextCall.cases.json). Change them together.

The rule judges working sets only (warm-ups are skipped), reads effort as reps in reserve (RIR 0-4,
with the old easy/right/hard read as 3/1/0), and handles assisted exercises, where kg is the
machine's help and less help is progress.
"""

import math
import re

GYM_TYPES = ("load", "distance", "assisted")



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


_LEGACY_RIR = {"easy": 3, "right": 1, "hard": 0}


def rir_of(s: dict):
	"""Reps in reserve: the logged RIR, else the old effort read as easy 3, right 1, hard 0."""
	rir = s.get("rir")
	if rir not in (None, ""):
		return int(rir)
	return _LEGACY_RIR.get(s.get("effort") or "")


def working_kg(session, assisted: bool = False) -> float:
	"""The kg used for the most sets; a tie goes to the harder weight (heavier, or less help)."""
	counts: dict = {}
	for s in session["sets"]:
		kg = s.get("kg") or 0
		counts[kg] = counts.get(kg, 0) + 1
	best, best_count = 0, -1
	for kg, count in counts.items():
		harder = kg < best if assisted else kg > best
		if count > best_count or (count == best_count and harder):
			best, best_count = kg, count
	return best


def weaker_side(sets: list) -> list:
	"""Per-side sets (side L and R sharing a set_no) become one set judged on the weaker side:
	the lower kg, the lower amount and the fewer reps in reserve. Sets without a side pass through."""
	out, by_set_no = [], {}
	for s in sets:
		if s.get("side") not in ("L", "R"):
			out.append(s)
			continue
		pair = by_set_no.get(s.get("set_no"))
		if pair is None:
			pair = {"kg": s.get("kg"), "amount": s["amount"], "rir": rir_of(s)}
			by_set_no[s.get("set_no")] = pair
			out.append(pair)
			continue
		if s.get("kg") is not None:
			pair["kg"] = s["kg"] if pair["kg"] is None else min(pair["kg"], s["kg"])
		pair["amount"] = min(pair["amount"], s["amount"])
		rirs = [r for r in (pair["rir"], rir_of(s)) if r is not None]
		pair["rir"] = min(rirs) if rirs else None
	return out


def next_call(exercise: dict, target: dict, history: list, review_delta_kg: float = 0) -> dict:
	"""exercise: {type, increment_kg}; target: {sets, reps, test?, startingKg?};
	history: earlier sessions with this exercise, newest first:
	[{date, deload?, sets: [{kg, amount, effort?, rir?, warmup?, side?, set_no?}]}].
	Warm-up sets are dropped and per-side sets are judged on the weaker side (weaker_side)."""
	is_gym = exercise["type"] in GYM_TYPES
	sessions = []
	for s in history:
		if is_gym and s.get("deload"):
			continue
		sets = weaker_side([x for x in s["sets"] if not x.get("warmup")])
		if sets:
			sessions.append({**s, "sets": sets})

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
		return {**result, "kg": kg, "reason": "From your weekly review"}
	return result


def _zeros(sets) -> int:
	return sum(1 for x in sets if rir_of(x) == 0)


def _weight_call(exercise, target, rng, sessions):
	a, b = rng
	assisted = exercise["type"] == "assisted"

	def tag(call):
		return {**call, "assist": True} if assisted else call

	# 3. No history.
	if not sessions:
		start = target.get("startingKg")
		if start:
			return tag({"call": "start", "kg": start, "reason": f"Start around {_fmt(start)} kg"})
		reason = "Pick the help that lets you do clean reps" if assisted else "Pick a weight you can do with clean form"
		return tag({"call": "start", "reason": reason})

	inc = exercise["increment_kg"]
	w = working_kg(sessions[0], assisted)
	work = _work(sessions[0], w)

	def harder(kg):
		return _step_down(kg, inc) if assisted else _step_up(kg, inc)

	def easier(kg):
		return _step_up(kg, inc) if assisted else _step_down(kg, inc)

	# A jump of more than 10% needs reps to spare first (dumbbells 5 -> 7.5 kg, an empty bar 20 -> 25 kg).
	big = exercise["type"] == "load" and _big_step(w, _step_up(w, inc) - w)
	need = b + 2 if big else b

	# 4. Every working set at the top of the range (+2 reps before a big jump), at most one set to failure.
	if len(work) >= target["sets"] and all(s["amount"] >= need for s in work) and _zeros(work) <= 1:
		if assisted and w == 0:
			return tag({"call": "hold", "kg": 0, "reason": "No help needed: beat your reps"})
		if assisted and inc <= 0:
			return tag({"call": "up", "reason": "Hit the top of the range: take one step less help"})
		reason = "Hit the top of the range with reps to spare" if big else "Hit the top of the range"
		return tag({"call": "up", "kg": harder(w), "reason": reason})

	at_w = [s for s in sessions if working_kg(s, assisted) == w]
	if len(at_w) >= 2:
		last_two = at_w[:2]

		# 5. Felt easy (3+ reps in reserve) two sessions running. Skipped on a big step.
		def easy(s):
			sets = _work(s, w)
			easy_count = sum(1 for x in sets if (rir_of(x) if rir_of(x) is not None else -1) >= 3)
			return (
				bool(sets)
				and all(x["amount"] >= a for x in sets)
				and easy_count * 3 >= len(sets) * 2
				and _zeros(sets) == 0
			)

		if not big and all(easy(s) for s in last_two) and not (assisted and (w == 0 or inc <= 0)):
			return tag({"call": "up", "kg": harder(w), "reason": "Felt easy two sessions running"})

		# 6. Struggling two sessions running: half the sets to failure and half short of the range.
		def hard(s):
			sets = _work(s, w)
			short_count = sum(1 for x in sets if x["amount"] < a)
			return bool(sets) and _zeros(sets) * 2 >= len(sets) and short_count * 2 >= len(sets)

		if all(hard(s) for s in last_two) and not (assisted and inc <= 0):
			return tag({"call": "down", "kg": easier(w), "reason": "Two hard sessions: drop a step and rebuild"})

	# 7. Stalled: three sessions running at this weight without adding a rep.
	run_at_w = []
	for s in sessions:
		if working_kg(s, assisted) != w:
			break
		run_at_w.append(s)

	def full(s):
		return len(_work(s, w)) >= target["sets"]

	if len(run_at_w) >= 3 and full(run_at_w[0]) and full(run_at_w[2]):

		def reps(s):
			return sum(x["amount"] for x in _work(s, w)[: target["sets"]])

		if reps(run_at_w[0]) <= reps(run_at_w[2]):
			if big or (assisted and inc <= 0) or easier(w) == w:
				return tag({"call": "hold", "kg": w, "reason": "No progress in 3 sessions: rest 3 min and check sleep and food"})
			return tag({"call": "down", "kg": easier(w), "reason": "No progress in 3 sessions: drop a step and rebuild"})

	# 8. Otherwise hold.
	return tag({"call": "hold", "kg": w, "reason": f"Build to {_fmt(need)} reps before moving up" if big else "Beat your reps"})
