"""Prompt builders and JSON schemas (docs/05). The wording follows the spec; replies are JSON objects
(not bare arrays) so the structured-outputs schema can describe them."""

ITEM_SCHEMA = {
	"type": "object",
	"properties": {
		"food_name": {"type": "string"},
		"portion": {"type": "string"},
		"kcal": {"type": "number"},
		"protein_g": {"type": "number"},
	},
	"required": ["food_name", "portion", "kcal", "protein_g"],
	"additionalProperties": False,
}

ESTIMATE_SCHEMA = {
	"type": "object",
	"properties": {"items": {"type": "array", "items": ITEM_SCHEMA}},
	"required": ["items"],
	"additionalProperties": False,
}

SUGGEST_SCHEMA = {
	"type": "object",
	"properties": {
		"options": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"title": {"type": "string"},
					"why": {"type": "string"},
					"items": {"type": "array", "items": ITEM_SCHEMA},
				},
				"required": ["title", "why", "items"],
				"additionalProperties": False,
			},
		}
	},
	"required": ["options"],
	"additionalProperties": False,
}

TEXT_LIMIT = 1500


def estimate_prompt(text: str | None, has_image: bool) -> str:
	text = (text or "").strip()[:TEXT_LIMIT]
	lines = [
		"You estimate nutrition for food eaten in Kenya: Nairobi home cooking and local eateries.",
		"Stews and vegetables are cooked with oil. Split the meal into separate foods.",
		"For each food give a short name, the portion as eaten, and your estimate of kcal and grams",
		"of protein for that whole portion.",
	]
	if has_image:
		lines.append(
			"The attached photo shows one meal. Judge portions from what you see (plate size, piece counts)."
		)
		if text:
			lines.append(f"Extra details from the user: {text}")
	else:
		lines.append(f"What the user ate: {text}")
	lines.append("Reply with only a JSON object, for example")
	lines.append('{"items":[{"food_name":"Chapati","portion":"2 medium","kcal":360,"protein_g":8}]}')
	return "\n".join(lines)


def suggest_prompt(ctx: dict) -> str:
	meal = f"his {ctx['meal']}" if ctx.get("meal") else "the rest of today"
	budget = ctx.get("budget") or {}
	lines = [
		f"You suggest meals for a {ctx['weight']} kg man in Nairobi, Kenya, who lifts weights {ctx['days']} days a week",
		f"and wants to {ctx['goal']}. Suggest 3 different options for {meal}",
		"using cheap, easy-to-find Kenyan foods and home cooking.",
		f"Targets today: {ctx['kcal']:g} kcal and {ctx['protein']:g} g protein. Remaining: {ctx['kcal_left']:g} kcal and",
		f"{ctx['protein_left']:g} g protein. Eaten so far: {ctx['eaten']}. Training today: {ctx['training']}.",
		f"Foods he often eats: {ctx['usual']}.",
	]
	if budget.get("later"):
		lines += [
			f"Budget for {meal}: about {budget['kcal']} kcal and {budget['protein_g']} g protein. Keep each option",
			f"close to that budget and never more than 10% over it. The rest ({budget['later_kcal']} kcal,",
			f"{budget['later_protein_g']} g protein) is for {budget['later']}, so don't use it up.",
		]
	else:
		lines.append("Close the protein gap without going over the remaining calories.")
	lines += [
		"If calories are nearly used up, suggest lean, high-protein, low-calorie options. Keep portions realistic.",
		"Each option lists its foods with portion, kcal and grams of protein for that portion, and",
		"one short sentence on why it fits.",
	]
	if ctx.get("exclude"):
		lines.append(f"He has already seen these, so suggest different meals: {'; '.join(ctx['exclude'])}.")
	lines += [
		"Reply with only a JSON object:",
		'{"options":[{"title":"...","why":"...","items":[{"food_name":"...","portion":"...","kcal":0,"protein_g":0}]}]}',
	]
	return "\n".join(lines)
