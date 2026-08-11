"""Student starter: implement the four memory TODOs.

Do not open `memory_agent.py` until the debrief.

Part A (main.py) already showed you WHY these exist: the tools-only agent
could not answer because the incident file name and the fine were said in an
earlier session and written nowhere. Part B (pipeline.py) is WHERE you build
the machinery. Your four methods are driven directly over one long briefing
transcript plus a seed store:

    TODO 1  write_memory      transcript              -> candidate records     API
    TODO 2  validate_record   candidate record        -> allowed? why not?     no API
    TODO 3  reconcile         records + transcript    -> store changes         API
    TODO 4  build_context     store + history         -> budgeted messages     API

Most of the real work of TODO 1 and TODO 3 is the PROMPTS near the top of
this file - the method bodies are mostly plumbing. Two TODOs call the model
and two deliberately do not: extraction and reconciliation are language work,
but a gate whose verdict changes between runs is not a gate, and conflict
resolution you cannot unit test is a bug waiting to happen.

Work one TODO at a time; each step tests the one before it:

    python3 pipeline.py --implementation starter --step 1   # after TODO 1
    python3 pipeline.py --implementation starter --step 2   # after TODO 2
    python3 pipeline.py --implementation starter --step 3   # after TODO 3
    python3 pipeline.py --implementation starter --step 4   # after TODO 4
"""

from __future__ import annotations

import re

from react_loop import Assembled, ContextOverflow, extract_json_object
from tokens import count_messages, count_tokens

# --------------------------------------------------------------------------
# Provided constants. Tune them if you want - they are policy, not law.
# --------------------------------------------------------------------------

# A single message longer than this is a candidate for trimming at L1.
MAX_MESSAGE_TOKENS = 180

# How many recent turns stay verbatim when L2 compacts. The current turn must
# always survive: it is what the pipeline has to act on.
TAIL_KEEP = 4

# A starting point, not a complete list. Extend it in TODO 2.
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Zhipu style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),             # AWS access key id
    # TODO 2 (part of it): what else should never be written to a memory
    # store? GitHub tokens, Slack tokens, and the generic "password=..."
    # shape are the usual suspects. Add the patterns you think belong here.
]

# Ways a model crams two facts into one record. Used by TODO 2.
COMPOUND_MARKERS = [" and ", " & ", "; ", "、", "\n"]

# --------------------------------------------------------------------------
# YOUR PROMPTS - this is where most of the real work of TODO 1 and TODO 3
# lives. Each TODO's docstring lists exactly what its prompt must say.
# --------------------------------------------------------------------------

EXTRACT_PROMPT = """TODO 1: write your extraction prompt here.

write_memory's docstring lists what it must state: JSON only, in a shape you
specify; one fact per entry, never two; short generic snake_case keys; bare
verbatim values (no units); durable facts only; if a later statement corrects
an earlier value, return only the corrected one; never store a negation.
"""

RECONCILE_PROMPT = """TODO 3: write your verdict prompt here.

It must define the four verdicts (ADD / UPDATE / DELETE / NOOP), ask for JSON
only in a shape you specify, and tell the model to judge by meaning, not by
string equality.
"""

REVOKE_PROMPT = """TODO 3: write your revocation prompt here.

Explicit revocations only ("stop doing X", "X was retired"); a changed value
is an UPDATE, not a revocation; when in doubt return {"revoked": []}.
"""

# Provided - the compact() helper below uses it. Note how different its job
# is from TODO 1's: extraction keeps only durable facts as structured
# records, while this prompt writes prose and must preserve EVERY concrete
# value in the span. Same model, two uses.
COMPACT_PROMPT = """Summarise this slice of a conversation in at most 110 words.

Preserve every concrete value: file names, amounts, counts, dates, schedules,
and any instruction the user gave. Drop greetings, acknowledgements, and
restatements of intent. Write plain prose, no bullet points."""


class MemoryPolicy:
    """Your memory pipeline. Part B drives these four methods directly."""

    name = "memory(starter)"

    def __init__(self, model: str = "", tail_keep: int = TAIL_KEEP) -> None:
        self.model = model
        self.tail_keep = tail_keep
        self.compactions = 0
        self.max_ladder_rung = 0

    def _kwargs(self) -> dict:
        """Pass this to client.chat(**self._kwargs()) so --model is respected."""
        return {"model": self.model} if self.model else {}

    # ====================================================================
    # TODO 1 - the write path.
    # ====================================================================
    def write_memory(self, client, conversation: list[dict], session_no: int) -> list[dict]:
        """Turn one whole conversation into a list of candidate memory records.

        The briefing transcript is ~20 messages and contains four facts worth
        keeping, totalling about 40 tokens. Getting that ratio is the point.

        Return a list of dicts shaped like:

            {"key": "log_file", "value": "logs/access_2026-09.csv",
             "source": f"session{session_no}", "session": session_no}

        What to do:
          a. Flatten `conversation` into a transcript string - USER turns only.
             "Observation:" messages are tool output, and the assistant's own
             replies are derived from what the user said: extract them and you
             feed the assistant's mistakes back into the store. (The transcript
             plants exactly this trap: the assistant miscalculates "a ten-record
             incident would come to 2,000 yuan" - extract user turns only and
             that mistake never reaches you.)
          b. Fill in EXTRACT_PROMPT at the top of this file, then call the
             model ONCE:

                 reply = client.chat(
                     [{"role": "system", "content": EXTRACT_PROMPT},
                      {"role": "user",   "content": transcript}],
                     temperature=0.0, max_tokens=600,
                     purpose="extract", **self._kwargs())

          c. Parse it with extract_json_object(reply) - it tolerates fenced
             blocks and trailing prose. Never assume the reply is clean JSON.
          d. Normalise into the shape above and return the list.

        EXTRACT_PROMPT has to say at least the things its placeholder lists,
        or a weak model will not do them. One fact per entry, never two. A
        SHORT generic snake_case key a later session could look up by name -
        "fine_per_violation", not "badge_system_fine_amount": a key nobody
        reuses is a fact nobody can update. The value copied verbatim and kept
        atomic (a file name, a bare number), not computed or converted. Only
        things that stay true beyond this conversation. If a later turn
        corrects an earlier value, return only the corrected one. And: never
        store a negation ("stop sending X") as a fact - that is a revocation,
        TODO 3's subject.

        One practical trap: the transcript contains a ~40-line config paste.
        Feed it in raw and it can drown the four short facts (observed live).
        Run each user message through the provided trim_oversized() helper
        first - the head survives, and the spoken credential the gate must
        catch is short enough to survive any trim.

        Do not filter out anything unsafe here. Extraction reports what the
        conversation said; TODO 2 decides what is allowed in. Keeping those
        separate is what makes the gate testable.
        """
        raise NotImplementedError("TODO 1: write_memory")

    # ====================================================================
    # TODO 2 - the write gate.
    # ====================================================================
    def validate_record(self, record: dict, store) -> tuple[bool, str]:
        """Decide whether one candidate record may enter the store.

        Return (True, "ok") or (False, "<short reason>"). The reason is
        printed, so make it something a human can act on.

        No API call here, on purpose. The model produced this record; the
        model does not also get to approve it. A gate that answers differently
        on different runs cannot be reviewed, cannot be tested, and is not a
        control.

        Three checks, in this order:

          1. SECRETS - first, because it is the only failure that can never be
             undone. The user says a key out loud ("the key is
             ZAI_API_KEY=sk-proj-...") and the extractor will faithfully turn
             it into a record. Reject it. Check the key and the value
             together, and use SECRET_PATTERNS above (which you have
             extended - the starter list misses GitHub and Slack tokens and
             the generic "password=..." shape, and the attack set tests them).

          2. SHAPE - is it a dict, is there a non-empty string `key`, is there
             a non-empty string `value` that contains at least one letter or
             digit? A weak model returns records with a key and no value, with
             value: null, or with a literal placeholder. Reject them rather
             than storing junk that later code has to defend against.

          3. ONE FACT PER RECORD - reject values that pack two facts together,
             e.g. "the ServerRoom and the Lab". COMPOUND_MARKERS is a starting
             point. A record you cannot look up by one key is a record you
             cannot update.

        Now the interesting part: what this function must NOT check.

        Do not reject a record because the store already holds it, and do not
        reject one because the store holds that key with a different value.
        Both of those are comparisons against STATE, and state is TODO 3's
        subject - the first is its NOOP verdict, the second is its UPDATE.
        Screen either one out here and you make a branch of TODO 3 unreachable.

        The boundary is: this function asks "is this record admissible?",
        TODO 3 asks "what does it mean, given what I already know?"

        (`store` is still a parameter because you may want to look at it -
        just don't let it drive your verdict.)
        """
        raise NotImplementedError("TODO 2: validate_record")

    # ====================================================================
    # TODO 3 - update and forget.
    # ====================================================================
    def reconcile(self, client, store, records: list[dict], conversation: list[dict],
                  session_no: int) -> None:
        """Apply the accepted records to the store: ADD / UPDATE / DELETE / NOOP.

        Returns nothing; it mutates the store. All four verdicts occur in the
        briefing transcript, judged against the seed store:

            ADD     "logs/access_2026-09.csv", "audit runs on day 1"
            UPDATE  "the fine is 250 now, not 200"      fine_per_violation 200 -> 250
            DELETE  "stop sending the report to security-team"
            NOOP    "the incident file is still incident_0812.txt"

        The split to hold onto: THE MODEL JUDGES THE RELATIONSHIP, YOUR CODE
        PERFORMS THE OPERATION. Judging needs language - "fine_per_violation"
        and "the fine per record" are the same fact in different strings.
        Performing must not: whether the store ends up saying 250 or 200
        changes every total anyone computes later, so it has to be
        deterministic and inspectable.

        Part A - judge each candidate. Fill in RECONCILE_PROMPT at the top of
        this file. For each record, look up store.get(record["key"]) and ask
        the model for a verdict:

            reply = client.chat(
                [{"role": "system", "content": RECONCILE_PROMPT},
                 {"role": "user",   "content": <candidate, existing value, and
                                                what the user said>}],
                temperature=0.0, max_tokens=120,
                purpose="reconcile", **self._kwargs())

        Then execute it yourself:

            ADD     -> store.add(record)
            UPDATE  -> store.supersede(key, record)      old row -> "superseded"
            DELETE  -> store.soft_delete(key, source=record["source"])
            NOOP    -> store.noop(key)

        Nothing is ever physically removed. UPDATE replaces the *current
        value* and keeps the old row marked superseded, so the store still
        shows what was believed before and when that changed. The grader
        checks for that row.

        Also decide what to do when the model returns something that is not
        one of the four words. It will happen. Pick a safe default and make it
        explicit.

        Part B - revocations need their own pass. "Stop sending the report to
        security-team" names a stored fact without stating a new value, so
        TODO 1 never produces a candidate for it and the loop above has
        nothing to judge. Fill in REVOKE_PROMPT, then make one more call, once
        per conversation: give the model the facts currently in the store
        (store.all() and store.keys() are provided) plus what the user said,
        and ask which of them this conversation revokes. Use purpose="revoke".

        Be careful with REVOKE_PROMPT. A changed value is an UPDATE, not a
        revocation - conflate them and you will delete fine_per_violation
        instead of updating it.
        """
        raise NotImplementedError("TODO 3: reconcile")

    # ====================================================================
    # TODO 4 - working memory under a budget.
    # ====================================================================
    def build_context(self, client, system: str, store, history: list[dict],
                      budget: int) -> Assembled:
        """Assemble messages for one model call under `budget` tokens.

        In a live agent this runs before EVERY model call. Part B drives it
        once, over the whole briefing transcript, at a budget the transcript
        does not fit into. Return:

            Assembled(messages=[...], tokens=<count>, ladder=[<one line per rung>])

        The budget is checked here, before any client.chat() would be reached.
        Checking usage afterwards is not a budget check - the request already
        went out.

        Measuring is the easy half. The real work is what you do when it does
        not fit. Implement a LADDER, cheapest and least lossy first, and record
        each rung you tried in `ladder` so the degradation is visible:

          L0  assemble everything
              system prompt, then store.digest() if it is non-empty, then all
              of `history`. Count it with count_messages(). If it fits,
              return here.

          L1  trim oversized messages          code only, no API
              The transcript contains a ~40-line config paste. Shorten it with
              the provided self.trim_oversized() and reassemble. The message
              stays in the conversation, it just gets shorter - a trim you can
              see, unlike a turn that silently disappeared.

          L2  compact turns 0..N-k             one API call
              Summarise everything except the last `self.tail_keep` turns into
              a single system message, and put it where those turns were. Use
              the provided self.compact().

          L3  the same mechanism, k = 1
              Only the current turn stays verbatim. Cheaper, and much lossier.

          still over -> raise ContextOverflow(used, budget, "<why>")
              At this point the budget itself is too small for the task.

        Why L1 before L2: trimming one oversized message is targeted, free,
        and keeps the message. Compaction costs an API call and loses detail
        across every turn it touches. Cheap before expensive, lossless before
        lossy.

        Also set self.max_ladder_rung to the highest rung you needed, so the
        pipeline can report it.
        """
        raise NotImplementedError("TODO 4: build_context")

    # ==================================================================
    # Provided. Not a TODO. Both TODO 1 (so the long paste cannot drown
    # the short facts) and TODO 4's L1 rung use this helper.
    # ==================================================================
    def trim_oversized(self, message: dict) -> dict:
        """Shorten one message; do not drop it.

        Returns `message` unchanged if it fits MAX_MESSAGE_TOKENS. Otherwise
        keeps the head and the tail (the head carries the framing, the tail
        often the conclusion) and leaves a visible marker, so anyone reading
        the trace can tell a trim happened.
        """
        content = str(message.get("content", ""))
        if count_tokens(content) <= MAX_MESSAGE_TOKENS:
            return message
        lines = content.splitlines()
        head, tail = lines[:10], lines[-3:]
        removed = max(0, len(lines) - len(head) - len(tail))
        shorter = "\n".join(head + [f"[... {removed} lines trimmed ...]"] + tail)
        return {**message, "content": shorter}

    # ==================================================================
    # Provided. Not a TODO. TODO 4's L2 and L3 rungs call this to squeeze
    # several turns into one short note - one API call per use, driven by
    # the provided COMPACT_PROMPT above.
    # ==================================================================
    def compact(self, client, messages: list[dict]) -> str:
        """Several turns in, one short prose note out. Lossy by design -
        which is exactly why your ladder tries the free, lossless trim first."""
        self.compactions += 1
        body = "\n\n".join(f'[{m["role"]}] {m["content"]}' for m in messages)
        reply = client.chat(
            [
                {"role": "system", "content": COMPACT_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
            max_tokens=280,
            purpose="compact",
            **self._kwargs(),
        )
        return f"[compacted {len(messages)} earlier turns] {reply}"

    # ==================================================================
    # Provided. Not a TODO. This is the background write path: it runs once
    # when a session ends, and it is where 1 -> 2 -> 3 connect. Part A's
    # memory mode calls it with --implementation starter; Part B's pipeline
    # drives the four methods directly.
    # ==================================================================
    def close_session(self, client, store, conversation: list[dict], session_no: int) -> None:
        candidates = self.write_memory(client, conversation, session_no)

        accepted = []
        for record in candidates:
            ok, reason = self.validate_record(record, store)
            if ok:
                accepted.append(record)
            else:
                store.log_rejection(record, reason)

        self.reconcile(client, store, accepted, conversation, session_no)
        store.save()
