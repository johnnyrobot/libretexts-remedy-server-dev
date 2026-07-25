# Behavioral Question Generation v1

Generate focused accessibility-quality questions whose answers are present in the baseline visual or source context.
Use the behavioral dimension to choose the question type: comprehension for reading order and alt text, location for heading/title navigation, row-column lookup for tables, sheet selection for XLSX navigation, and information equivalence for decorative skips.
Return JSON with `question`, `expected_answer`, `source_dimension`, and optional `source_locator`.
Do not ask about information absent from the baseline context, and do not reward structural compliance alone.
