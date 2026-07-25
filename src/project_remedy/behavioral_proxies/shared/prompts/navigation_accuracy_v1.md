# Behavioral Navigation Accuracy v1

For heading, slide-title, or sheet navigation tests, answer where a user should go to find the requested content using only the supplied outline, title list, or sheet-purpose list.
Treat a response as correct only when it preserves the expected heading, slide title, or sheet identifier.
Return JSON with `question`, `expected_destination`, `candidate_destination`, `correct`, and a short `reason`.
Do not infer destinations from visual layout or source content that is not present in the candidate navigation context.
