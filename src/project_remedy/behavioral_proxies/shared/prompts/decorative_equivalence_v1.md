# Behavioral Decorative Equivalence v1

Compare two transcripts: one including decorative-tagged objects and one excluding them.
Judge them information-equivalent only when removing the decorative objects does not remove task-relevant content, labels, data, instructions, or context needed by a screen-reader user.
Return JSON with `equivalent`, `missing_information`, `severity`, and `reason`.
Decorative status is not enough by itself; information preservation is the scoring criterion.
