# Behavioral Table Lookup v1

For table-cell lookup tests, answer the requested row and column value using only the screen-reader-style table serialization.
Treat header association, row identity, and cell value preservation as required for correctness.
Return JSON with `row_key`, `column_key`, `expected_value`, `candidate_value`, `correct`, and `reason`.
Do not use surrounding prose or visual assumptions to fill in a value missing from the serialized table.
