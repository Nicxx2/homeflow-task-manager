def build_task_effort_prompt(title: str, description: str) -> str:
    clean_title = title.strip()
    clean_description = description.strip()
    return f"""
You are an assistant that classifies practical task effort for households/small teams.

Return JSON ONLY with this exact schema:
{{
  "suggested_level": "low|medium|high",
  "confidence": 0.0,
  "reason": "short explanation"
}}

Rules:
- Confidence must be between 0 and 1.
- Use realistic effort, not optimism.
- Do not include markdown or extra text.

Classify using these factors (most important first):
1) quantity/scale of work (few items vs many items)
2) repeated actions (single step vs many repeated steps)
3) physical effort (heavy lifting, moving, carrying, deep cleaning)
4) likely total duration
5) scope language ("whole", "entire", "everything")

Effort guidance:
- low: quick, small, limited scope, few items, likely under ~20 minutes
- medium: moderate effort, multiple steps, likely ~20-90 minutes
- high: large quantity, heavy physical effort, whole-area scope, likely 90+ minutes

Examples:
- "dust one shelf" -> low
- "clean one bedroom thoroughly" -> medium
- "unpack 30 heavy boxes" -> high
- "sort the whole storage room" -> high

Confidence guidance:
- 0.45-0.65 when details are sparse/ambiguous
- 0.66-0.82 when clear signals support the level
- avoid >0.85 unless evidence is very explicit and strong

Task title:
{clean_title}

Task description:
{clean_description}
""".strip()
