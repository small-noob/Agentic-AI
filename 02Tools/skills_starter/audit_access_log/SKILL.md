---
name: audit_access_log
description: TODO 4 — one or two sentences that let the model decide whether this skill is relevant. Say what it does AND when to use it. Keep it under 400 characters; it sits in every system prompt.
---

TODO 4 — replace everything below with the actual procedure.

The body is loaded only after the model calls `load_skill`, so length is much
cheaper here than in the description above. Spend it on the things the model
gets wrong without help.

Write the procedure so that an agent which has never seen this workspace can
follow it end to end. A useful body usually answers:

- **Which files must be read, and why is each one necessary?**
  (Hint: run the agent once with `--mode noskill` and watch what it skips.)
- **What exactly counts as a violation?** Be precise about the boundary cases:
  which records are eligible at all, what the clearance comparison is, and how
  the allowed-hours window treats its endpoints.
- **Is the unit being counted a record or a reason?** A record that breaks three
  rules is still one record.
- **How is the report code computed, and with which tool?**
- **What must the final answer look like?**

## Checklist before you move on

- [ ] The description names both the capability and the trigger condition.
- [ ] The body lists concrete filenames and tool names, not vague advice.
- [ ] Every mistake you saw in the `noskill` run is addressed by a line here.
- [ ] Nothing in the body hard-codes the answer — a skill is a procedure, not a
      lookup table. `python3 main.py --mode skill --skills-dir skills_starter`
      must still work if the log file changes.
