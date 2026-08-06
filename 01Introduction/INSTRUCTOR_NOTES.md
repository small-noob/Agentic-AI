# Instructor notes — remove before distributing if desired

## Why this is a multi-round ReAct task

The second action is not fixed until the first calculator Observation reveals
whether the seed is even or odd. The exercise therefore demonstrates an actual
`Action → Observation → branch → Action` dependency, using only one tool type
and two tool calls.

## Reference answer

1. `pow(20250807, 123457, 1000000) = 730807`.
2. `730807` is odd, so select the odd branch.
3. `(730807 * 2025 + 271828) % 1000000 = 156003`.

Expected JSON:

```json
{"answer": "156003"}
```

The grader requires both calculator Observations, so a lucky guess or an early
Finish cannot receive the full ReAct process score.

## Suggested classroom timing (25–30 minutes)

- 4 minutes: explain the task and ask students to predict the branch.
- 4 minutes: run Direct and inspect its exact-match failure.
- 12–15 minutes: complete the three TODO blocks in `react_starter.py`.
- 4 minutes: run ReAct and inspect the three-turn trace.
- 4 minutes: debrief on why Observation changes the next Action.

Useful discussion question: if both branch calculations were performed before
observing S, would the system still be acting agentically, or merely executing a
fixed workflow?
