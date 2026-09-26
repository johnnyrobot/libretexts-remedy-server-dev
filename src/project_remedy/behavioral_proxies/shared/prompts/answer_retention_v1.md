# Behavioral Answer Retention v1

Answer each generated question using only the supplied context transcript.
Compare baseline-context answers to candidate-context answers and score retained accuracy as `candidate_accuracy / baseline_accuracy`, capped at 1.0.
Return JSON with `baseline_answer`, `candidate_answer`, `baseline_correct`, `candidate_correct`, and `finding` when the baseline is correct but the candidate loses the expected information.
The answerer model must be independent from every model that generated or remediated the artifact under test.
