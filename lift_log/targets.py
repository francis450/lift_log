"""Daily targets (docs/01, "Targets"). Pure functions plus the LL Profile hook that applies them."""

import math

from frappe.utils import cint, flt

DEFAULT_KCAL = 2200


def _round_to(value: float, step: int) -> int:
	# Half up, not Python's banker's rounding.
	return int(math.floor(value / step + 0.5)) * step


def protein_target(weight_kg: float | None) -> int | None:
	"""round(1.8 x weight / 5) x 5 grams. 130 g at 72 kg."""
	if not flt(weight_kg):
		return None
	return _round_to(1.8 * flt(weight_kg), 5)


def kcal_target(weight_kg: float | None, height_cm: int | None, age: int | None) -> int:
	"""Mifflin-St Jeor (men) x 1.55 - 500, to the nearest 50. 2,200 without weight, height or age."""
	weight, height, age = flt(weight_kg), cint(height_cm), cint(age)
	if not (weight and height and age):
		return DEFAULT_KCAL
	bmr = 10 * weight + 6.25 * height - 5 * age + 5
	return _round_to(bmr * 1.55 - 500, 50)


_INPUTS = (("height_cm", "height"), ("weight_kg", "weight"), ("age", "age"))


def _reasons(before, profile) -> list[str]:
	reasons = []
	for field, label in _INPUTS:
		old, new = flt(before.get(field)), flt(profile.get(field))
		if old == new:
			continue
		if not old:
			reasons.append(f"{label} added")
		elif not new:
			reasons.append(f"{label} removed")
		else:
			reasons.append(f"{label} updated")
	if before.kcal_target_manual and not profile.kcal_target_manual:
		reasons.append("calories back to automatic")
	if before.protein_target_manual and not profile.protein_target_manual:
		reasons.append("protein back to automatic")
	return reasons


def apply_automatic_targets(profile) -> None:
	"""Recalculate every target not set by hand. Write `targets_note` when an existing profile's
	targets change, e.g. "Targets updated: 2,150 kcal, 130 g protein (height added)."
	"""
	before = profile.get_doc_before_save()

	if not profile.kcal_target_manual:
		profile.kcal_target = kcal_target(profile.weight_kg, profile.height_cm, profile.age)
	if not profile.protein_target_manual:
		profile.protein_target_g = protein_target(profile.weight_kg) or 0

	if before is None:
		return
	changed = cint(before.kcal_target) != cint(profile.kcal_target) or cint(before.protein_target_g) != cint(
		profile.protein_target_g
	)
	reasons = _reasons(before, profile)
	if changed and reasons:
		profile.targets_note = (
			f"Targets updated: {cint(profile.kcal_target):,} kcal, "
			f"{cint(profile.protein_target_g)} g protein ({', '.join(reasons)})."
		)
