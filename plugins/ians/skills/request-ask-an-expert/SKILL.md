---
name: request-ask-an-expert
description: "Submit a faculty-led Ask-an-Expert (AAE) session at IANS Research. Triggers when the user asks to schedule an AAE call, talk to an IANS expert, get a 1:1 faculty consultation, request faculty time, or escalate a question to faculty review. Also triggers as a chained recommendation from other Ask IANS Skills when the model's synthesis hits the limits of unsupervised AI work (post-breach litigation prep, hostile board dynamics, novel regulatory situations, etc.). The default action is submission via the IANS MCP — direct connector write when `ians_request_aae` returns a successful submission, or a JSON submission artifact in the platform AAE form's submission shape that IANS can ingest directly. The skill mirrors the platform AAE form field-for-field — same labels, same order, same conditional rules. This release supports submit mode only (branded scoping .docx is deferred until the IANS design system skill ships). Do not use for general AAE explanation, content browsing, or non-IANS expert systems."
metadata:
  version: "1.0.0"
  description_short: "Submit a faculty-led Ask-an-Expert request to IANS Research. Use when the user wants to schedule an AAE call, request faculty time, or escalate a question to IANS expert review."
---

# Request Ask-an-Expert

Conversational form-filler for the IANS platform Ask-an-Expert form. This release is **submit-only**: the skill drafts what it can from conversation context, presents a **form-shaped review** that mirrors the platform form's labels and order, lets the user edit fields in chat, validates, then submits or produces a JSON artifact.

User-facing prompts are quoted verbatim in this SKILL.md. Use the exact text — do not paraphrase. Consistency in wording matters; users learn the prompts and rely on them.

## Step 0 — Connector gate (non-negotiable)

Call `ians_whoami()` first. Cache the response.

If the call fails, refuse. Show this message verbatim:

> **IANS MCP connector is not available.**
>
> This skill works with Ask-an-Expert requests on behalf of IANS Research. It can't run without a live connection to the IANS Research MCP server.
>
> To connect:
>
> 1. Confirm your IANS platform credentials are active.
> 2. Connect the IANS Research MCP server (contact your admin or visit your IANS onboarding guide).
> 3. Try again once the connection is established.

## Step 0.5 — Active-incident guard (non-negotiable)

Before anything else, scan the conversation for **active-incident language** — the user is in the middle of a live security event, not planning ahead. Trigger phrases (non-exhaustive, case-insensitive): "active breach", "we're being breached", "happening now", "in the middle of", "ongoing incident", "currently under attack", "live ransomware", "we're getting hit", "right now we're".

When active-incident language is present:

- **Do not improvise incident-response advice.** This skill files an AAE request; it is not an IR responder. Do not produce IR playbooks, containment steps, or "while we wait, here's what you can do" parallel-work suggestions.
- **Do not name or recommend any other IANS service** (ICC, the IANS Incident Command Center, retainers, other offerings). Naming a service reads as the skill recommending it, which is a coordinator/account-manager call, not the skill's. The only IANS pathway this skill offers is the AAE itself.
- Proceed straight to the AAE flow: draft the submission, present the form-shaped review, submit. Keep the framing to filing the request.

This rule holds identically on every model (Opus and Sonnet). It is a hard behavioral constraint, not a stylistic preference.

## Step 1 — Submit mode only (no scope in this release)

Proceed in **submit** mode without prompting for mode.

If the user explicitly asks for a doc to review, a scoping document, a .docx to share, or to hand off a file instead of submitting, tell them verbatim:

> Scoping doc support is coming once the IANS design system skill ships — for now I can only submit on your behalf or pause.

Then stop (do not fabricate a .docx).

Chained skills invoke this skill for **submit** only in this release; ignore any `mode: "scope"` hint from callers.

## Step 2 — Entitlement gate

Check AAE entitlement from the cached `ians_whoami` response.

If the user has AAE entitlement: continue.

If they don't, show this message verbatim, then end gracefully without producing a submission or artifact:

> Your IANS subscription doesn't currently include Ask-an-Expert. Contact your IANS account manager — they can help you add AAE access or discuss other ways to get faculty input.

## Step 2.5 — Ground the request in IANS content first

Before you draft Driver / Questions from open-web knowledge or your own synthesis, search IANS first. IANS has published content on most topics a CISO will raise, and a driver grounded in IANS sources reduces coordinator triage time.

Call `ians_search` with the topic phrase:

```
ians_search({ query: "<topic phrase>", top: 5 })
```

- **When results come back:** surface up to **three** candidate IANS sources to the user as linked titles, then ask verbatim before drafting:
  > I found IANS content on this. Want me to ground your request in any of these before I draft?
  >
  > 1. [Title](url)
  > 2. [Title](url)
  > 3. [Title](url)
  >
  > Say a number (or "none") and I'll fold it into the driver.
  Carry any selected sources into `context.related_ians_content` on the payload. Open-web knowledge becomes *supplementary* — use it only to fill gaps IANS coverage doesn't cover.
- **When `ians_search` returns no results:** say so plainly — *"No IANS content matched this topic, so I'll draft from our conversation."* — and continue from conversation context only. Do **not** silently fall back to open-web sourcing as if it were IANS content.
- **When `ians_search` is not registered** (the MCP exposes the AAE tools but not search, or the call errors with tool-not-found): skip grounding silently, note nothing to the user, and proceed to Step 3 drafting from conversation context. Never block the AAE flow on search availability.

## Step 3 — Build the form-shaped review

Don't ask the user a series of questions. Run `scripts/draft_payload.py` against the conversation context to extract Driver / Question / Details, then surface a **review that mirrors the platform AAE form** field-for-field.

**Hard rule — no fabrication on `must_ask` fields.** When `draft_payload.py` returns a field in `must_ask` (driver or question came back null), render that field with its exact placeholder string from the field spec below. Do NOT invent content from the topic phrase, the user's profile, general knowledge, or anything else. A fabricated draft that the user accepts at review goes in front of faculty as if the user wrote it — that's a correctness failure even when the fabrication happens to be plausible. Details is optional and never appears in `must_ask`; if details came back null, render its placeholder anyway.

**Low-confidence drivers.** If the script returns `low_confidence: ["driver"]`, the driver was seeded from a topic-phrase fallback (e.g. "AAE is about X"). Render the seed verbatim — do not expand it — and append a one-line review prompt: *"This is a topic-phrase seed; please expand on what's driving this for you right now."* The user has something to react to without you putting words in their mouth.

The form-shaped review with placeholders IS the prompt for the user — the placeholders tell them which fields they need to fill in. Don't paraphrase the topic phrase into a fuller draft to look helpful; the helpful move is showing the user exactly where their input is needed.

Field order, labels, and conditional rules below are locked to match the platform AAE form.

### Resolution Type (always shown, always asked first)

The platform form opens with this question. Render this in the review with the same three options it shows:

> **What kind of Ask-An-Expert would you prefer?**
>
> Pick a delivery method:
>
> 1. **Ask-An-Expert Call** (Phone) — Explore nuanced challenges with an IANS Faculty member in an interactive, live setting. *30-60 minute interactive discussion. 8-12 business days. In-depth call with 1 Faculty.*
> 2. **Faculty Poll** — Get short, written responses from multiple faculty members on a topic. *Written deliverable. 4-6 business days. Broad perspectives from 5 Faculty.*
> 3. **Don't Know?** (Undecided) — Feel free to send us your request. Our team is here to help select the best avenue to answer your specific question.

Make a recommendation based on conversation context (use `scripts/recommend_resolution.py` for structured reasoning). Frame the recommendation as one line *after* the options:

> Based on your conversation, **{Phone | Faculty Poll | Undecided}** fits because {one-line reason}. You can change it.

**Always state why an AAE fits — a one-line rationale tied to the conversation.** Whenever an AAE is put in front of the user — whether this skill self-triggers or another Ask IANS Skill chains to it — lead with one sentence explaining *why faculty review is the right next step at this point in the conversation*. Use the format:

> Faculty review fits here because {specific signal in the conversation} — {what a faculty member adds that the AI can't}.

Examples:

- "Faculty review fits here because you're heading into a board conversation with hostile dynamics — a Faculty member can rehearse the hard questions with you."
- "Faculty review fits here because the regulatory framing is novel and post-breach — a Faculty member's judgment beats AI synthesis when the wrong frame creates legal exposure."

The rationale must tie to a **specific signal** in the conversation, not a generic value-prop. Generic framing like "you might want to talk to an expert" is not enough.

### What challenge do you want to discuss?

#### Driver and Context — *"What is the driver and context behind this request?"*

- Cap: 1000 chars (Phone/Undecided) or 750 chars (Faculty Poll).
- Draft from conversation. If empty after drafting, render with the placeholder: `[needs your input — what's driving this for you right now?]`.
- Show character count as `({len}/{cap})` after the label, matching the form.

#### Specific Questions — *"What are the {3-5 | 1-3} specific questions you would like addressed?"*

- 3-5 questions for Phone/Undecided; 1-3 for Faculty Poll.
- Same caps as Driver.
- **Always `must_ask`.** Questions go to faculty, and questions phrased in the user's own words get better answers. So this field is *never* silently accepted from a Claude draft — treat it as `must_ask` on every run, even when `draft_payload.py` extracted candidate questions.
- **Render the placeholder and prompt above any draft.** Show the prompt `[needs your input — what 3-5 specific questions do you want a faculty member to answer? (1-3 for Faculty Poll)]` first. If `draft_payload.py` produced candidate questions, render them *below* the prompt inside a **"suggested starting point"** callout — clearly a suggestion, not the locked value:
  > **Suggested starting point** (edit or replace these — they're my draft, not your final questions):
  > 1. {question} ({len}/{cap})
  > 2. {question} ({len}/{cap})
  > 3. {question} ({len}/{cap})
  >
  > Questions section: {section_total}/{cap}
- Each question renders with its own `({len}/{cap})` counter; the section total renders below the list. The counter must reflect the **locked payload value** (the canonical serialized string after the user confirms), not just what the user typed in chat.
- The field only locks after the user explicitly confirms or rewrites the questions. Accepting the draft silently (e.g. the user says "submit" without ever acknowledging the questions) does **not** lock the field — re-prompt for confirmation first.

#### Other Details (Phone/Undecided only) — *"Are there other details relevant to this challenge?"*

- Cap 500 chars.
- Skip section entirely for Faculty Poll. Don't show the heading.
- Draft from context. Empty placeholder: `[optional — team size, current tools, policies, or anything else that will help]`.

### What kind of guidance are you expecting? (Phone/Undecided only)

> This helps us select Faculty based on your desired outcome. Select all that apply.

- **Strategic / Executive** — *Examples: Aligning security priorities with business goals, budgeting & organization planning, governance strategy, influencing the board or C-suite.*
- **Technical / Tactical** — *Examples: Tool selection & configuration, architecture, threat detection, regulatory compliance, privacy policies & controls.*

Required for Phone/Undecided. Use `scripts/infer_guidance.py` to draft the selection. If the inference returns an empty array (ambiguous), render the section with this placeholder:

> `[needs your input — pick Strategic, Technical, or both]`

The locked payload must carry the **canonical Salesforce picklist values exactly** — `"Strategic / Executive"` and `"Technical / Tactical"` (with spaces around the slash). Short forms like `"Strategic"` are silently dropped by the platform form. `infer_guidance.py` already emits the canonical strings, and `validate_submission.py` normalizes short-form aliases with a warning — don't hand-write the short form into the payload.

Skip section entirely for Faculty Poll.

### Additional details on your request

#### Would you like to expedite this request?

> Yes / No

**Always surface the turnaround windows here**, before the user decides — they can't make an informed expedite choice without seeing the comparison. Render the windows for the selected resolution whether or not a deadline has been parsed:

> **Turnaround for {resolution}:** {standard} business days standard; expedited requests are prioritized.

Canonical windows (must match what IANS Client Services communicates to clients):

- **Faculty Poll:** 4-6 business days standard, expedited prioritized.
- **Phone / Undecided:** 8-12 business days standard, expedited prioritized.

If yes, render:

> **When is the deadline?** ({YYYY-MM-DD or [needs your input]})

Use `scripts/parse_urgency.py` to draft. Deadline must be ≥ today. If the parsed deadline is fewer than 14 calendar days out, append a warning:

> *Note: this is {N} calendar days away. Standard turnaround is 8-12 business days for Phone, 4-6 for Faculty Poll. The expedite flag prioritizes your request, but it may still be tight.*

#### Please confirm your email — *"Our Client Services team will use this to contact you about your request."*

- Pulled from `ians_whoami`. Render as the value, not a prompt:
  > **Email:** {email from whoami}

#### Scheduling (Phone/Undecided only)

> *"What dates work best for you to schedule this AAE?"* (optional)
>
> *"Feel free to share a calendar link or provide name/email of your executive assistant for scheduling."* (optional)

Use `scripts/parse_scheduling.py` to draft if the user mentioned scheduling in conversation. Both fields optional; if no input was found, show empty placeholders:

> Availability: `[optional]`
> Calendar link / EA: `[optional]`

Skip entirely for Faculty Poll.

### Submitter (read-only)

Show what will be sent as the submitter, pulled from `ians_whoami`:

> **Submitter:** {name} <{email}>

User can't edit this — it comes from the authenticated session.

## Step 4 — Present the review

**No partial reviews.** The first review message MUST render every required section for the resolution in a single message — never reveal a section only after the user prompts for it. The required section list is locked per resolution:

- **Phone / Undecided:** Resolution Type, Driver and Context, Specific Questions, **Other Details**, Guidance Type, Expedite + Deadline (with turnaround windows), Email (read-only), **Scheduling**, Submitter (read-only).
- **Faculty Poll:** Resolution Type, Driver and Context, Specific Questions, Expedite + Deadline (with turnaround windows), Email (read-only), Submitter (read-only). Faculty Poll **skips Other Details, Guidance, and Scheduling entirely** — do not show those headings.

For Phone/Undecided, **Other Details** and **Scheduling** always render on the first pass, even when `parse_scheduling.py` / detail extraction returned nothing — show their `[optional]` placeholders so the user learns the fields exist:

> **Scheduling**
> Availability: `[optional]`
> Calendar link / EA: `[optional]`

Render the entire review as a single chat message with all required sections shown, conditional rules applied. Then ask verbatim:

> Does this look right? Reply with edits in plain language (e.g., "shorten the driver", "add to details that we're on AWS", "make question 3 more specific about IAM"), or say **submit** to send.

If the user replies with edits, apply them, re-render the affected fields with updated counts, and ask again. If the user says submit (or equivalent — *"send it"*, *"go ahead"*, *"looks good"*), proceed to Step 4.5 (validation), then Step 5.

## Step 4.5 — Required-field validation gate

**Hard rule — script execution is non-negotiable.** Before any call to `submit_via_connector.py` or `build_submission_artifact.py`, you MUST run `validate_submission.py` on the locked payload and check its exit code. Do NOT skip this step, do NOT eyeball validation, do NOT decide a field "looks fine" without running the script. The platform AAE form has required fields; the connector validates server-side but only after the user has been told the request was sent. This step is the client-side gate.

**This gate runs on BOTH submit paths.** It is not artifact-only. The live connector (`ians_request_aae`) is a distinct surface from the Option B JSON artifact, and an incomplete Specific Questions field reaching the connector still creates a real IANS case. Run `validate_submission.py` and require `valid: true` before *either* `submit_via_connector.py` (Option A) or `build_submission_artifact.py` (Option B). A `placeholder_unfilled` or empty required field MUST block the `ians_request_aae` call, not just the artifact write. (The connector also rejects unfilled placeholders server-side as defense in depth, but never rely on that — it errors only after the user thinks the request was sent.)

Write the locked payload to a temp JSON (the same one Step 5 will pass to the connector / artifact builder), then call:

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/scripts/validate_submission.py \
  --payload <path-to-payload.json> \
  --whoami <path-to-ians-whoami-output.json>
```

Read the JSON result.

**If `valid: true`:** proceed to Step 5. Surface any `warnings` to the user in one line each before submitting (e.g. *"Heads up: deadline is 5 calendar days out — expedite flag is set, but it may still be tight."*). Warnings don't block.

**If `valid: false`:** do NOT submit. Surface each error to the user in plain language mapped from the `code`:

| Code | Plain-language message |
|---|---|
| `missing` | "{Field} is required. {field-specific prompt — same wording as the Step 3 placeholder.}" |
| `placeholder_unfilled` | "{Field} still shows the review placeholder — it was never filled in. {field-specific prompt — same wording as the Step 3 placeholder.}" |
| `topic_seed_only` | "The driver still reads as a topic seed (e.g. 'Topic: X.'). Tell me what's driving this — the situation, the decision, what's on the line." |
| `too_long` | "{Field} is {N} chars; the form caps it at {cap}. I can trim it — want me to?" |
| `too_few` | "{Resolution} needs {min}-{max} questions; you have {N}. Add {min-N} more." |
| `too_many` | "{Resolution} accepts {min}-{max} questions; you have {N}. Drop or merge {N-max}." |
| `invalid` | "{Field} value isn't valid: {message}." |
| `invalid_value` | "{Field} contains unrecognized values: {unknown}. Pick from {allowed}." |
| `in_past` | "Deadline {date} is before today. Pick a future date." |
| `invalid_format` / `invalid_date` | "Deadline must be a real date in YYYY-MM-DD format." |
| `not_allowed` | "Faculty Poll doesn't collect {field}. Want me to drop it, or switch to a Phone resolution?" |

After listing errors, ask verbatim:

> I can't submit until these are fixed. Reply with the corrections (e.g., "use these questions: ...", "set guidance to Strategic and Technical", "drop the deadline").

Loop: apply the user's edits, re-run `validate_submission.py`, and only proceed to Step 5 when `valid: true`.

## Step 5 — Submit: route through connector or artifact

**Precondition: Step 4.5 must have returned `valid: true`.** If you somehow reach this step without running validation, stop and run Step 4.5 first.

**Hard rule — connector submission is the default; never redirect to the web form.** When the IANS MCP is connected (Step 0 passed) and the user is entitled (Step 2 passed), this skill submits **through the connector**. Do NOT tell the user to go fill out the Ask-an-Expert form on iansresearch.com, and do NOT hand them a website link in place of submitting — that is not a path this skill offers when the connector is available. The Beta connector counts as available: if `ians_request_aae` is registered, use it. The **only** fallback when the connector write path is not live is Option B (the JSON submission artifact below) — never a website redirect.

**Hard rule — script execution is non-negotiable.** You MUST execute `submit_via_connector.py` and (on `tool_not_registered` or when the connector response indicates the write path is not live yet) `build_submission_artifact.py` via the Bash tool. Do NOT generate the JSON artifact inline, "describe" the file as if it exists, or invent your own field names — the platform AAE form's submission shape is locked and only `build_submission_artifact.py` produces it correctly. Any inline JSON is wrong and will be rejected by IANS-side ingestion. If the Bash call fails, surface the error to the user; do not fabricate success.

1. Try the connector:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/scripts/submit_via_connector.py \
     --payload <path-to-payload.json>
   ```

2. **Status `submitted`** (Option A — connector accepted the request): surface verbatim:
   > Your Ask-an-Expert request has been submitted. **Case:** {case_id}. You'll hear from an IANS Client Services coordinator within {window.business_days_min}-{window.business_days_max} business days. Track status: {tracking_url}
3. **Status `tool_not_registered`** or any connector response that means the server write is not yet available (including a live MCP `ians_request_aae` call that returns `status: pending` with no case): produce the JSON artifact (Option B):
   - Ask the user where to save (default workspace folder).
   - Filename: `AAE-Submission-{shortSubject}-{YYYYMMDD}.json`.
   - Call:

     ```bash
     python ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/scripts/build_submission_artifact.py \
       --payload <path> \
       --output <user-chosen-path>/AAE-Submission-{slug}-{YYYYMMDD}.json \
       --client-name Claude \
       --whoami <path-to-whoami>
     ```

   - Surface verbatim:
     > I've saved your submission as a JSON artifact at {path}. Hand this to your IANS account manager — they can submit it on your behalf. Once `ians_request_aae` ships end-to-end, future submissions will go directly to IANS without this file step.
4. **Status `error`**: read `error_code` and surface `user_message`:
   - `entitlement_missing` — defect (gate should have caught it). Surface message, end.
   - `validation_failed` — return to Step 4 with `details` shown so the user revises.
   - `rate_limited` — surface message, don't auto-retry.
   - `server_error` — fall through to Option B (artifact path).

## Step 6 — Confirm and close

End with:

1. Clear statement of what just happened.
2. Expected timeline for the resolution type, restating the turnaround window (4-6 business days for Faculty Poll, 8-12 for Phone/Undecided).
3. Standard advisory disclaimer (below).

**Who follows up:** the response loop is coordinated by **IANS Client Services**, not by faculty directly. Faculty produce the deliverable; IANS Client Services contacts the client. When you tell the user who they'll hear from, say "an IANS Client Services coordinator" — never "you'll hear back from faculty."

Don't promise specific faculty members or specific dates.

## Disclaimer

> Ask-an-Expert sessions provide faculty-guided advisory. They don't create an attorney-client or fiduciary relationship. Faculty perspectives are advisory; clients retain decision authority. Standard IANS terms apply.

## Connector contract

`ians_request_aae` may register on the IANS MCP before the full write path is live; until Option A returns `submitted` with `case_id`, this skill uses Option B (JSON submission artifact) by default.

- **Input** matches the JSON shape the platform AAE form posts. `origin` and `submitter` are server-populated, NOT in the input.
- **Output**: `case_id`, `tracking_url`, `expected_response_window`, `submitted_at`, `status`.
- **Error model**: `entitlement_missing`, `validation_failed`, `rate_limited`, `server_error`.
- **Idempotency**: optional `idempotency_key` prevents duplicate cases on retry.

## Chain pattern — invoked from another skill

Other Ask IANS Skills can chain to this skill:

```
Read: ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/SKILL.md
```

Then invoke this skill for **submit** (this release does not support scope mode). Pass conversation context.

A chained invocation must still lead with the one-line rationale from Step 3 ("Faculty review fits here because {signal} — {what faculty adds}") tied to a specific signal in the conversation — the always-rationale rule applies identically to chained and self-triggered recommendations.

## Out of scope

- **Active-incident response advice** — when the user is in a live incident (see Step 0.5), this skill does NOT improvise IR playbooks, containment steps, or "while we wait" parallel work. It files the AAE and nothing more.
- **Naming or recommending other IANS services** — the skill never name-drops IANS ICC / Incident Command Center, retainers, or other offerings (including during an active incident). Routing to another service is a coordinator / account-manager decision, not the skill's. The only IANS pathway this skill offers is the AAE.
- **Branded scoping .docx** — deferred until the `ians-design-system` skill ships; Step 1 refuses doc-only requests with the verbatim message above.
- Internal stakeholders / attendees field — matches the platform form, which doesn't collect this.
- Preferred contact method (phone vs email) — matches the platform form's current commented-out state.
- Re-collection of email or phone — pulled from `ians_whoami`. Server-side identity is authoritative.
- Ask IANS conversation linking via `ask_ians_id` — no Ask IANS → MCP bridge today.
- Faculty matching, faculty preferences, or faculty profile lookup — coordinator's job.
- Attachments / file uploads in the AAE request itself — not supported by the current connector contract.
- Submission on behalf of another user — entitlement model deferred to the platform "Import scoping doc" feature.
- Localization / non-English content — matches the platform.

## Scripts

- `scripts/recommend_resolution.py` — Heuristic resolution recommender (Phone / Faculty Poll / Undecided) with one-line reasoning.
- `scripts/draft_payload.py` — Extracts Driver / Question / Details from conversation transcript with cap and resolution-specific shape enforcement.
- `scripts/infer_guidance.py` — Strategic / Technical inference. Empty array signals "must ask the user."
- `scripts/parse_urgency.py` — Natural language urgency cues → `expedite_request` + ISO date.
- `scripts/parse_scheduling.py` — Combined scheduling input → `availability` / `calendarlink` routing.
- `scripts/build_submission_artifact.py` — Produces a JSON file in the platform AAE form's submission shape for IANS-side ingestion.
- `scripts/submit_via_connector.py` — Wraps the `ians_request_aae` MCP tool. Falls back to artifact when not registered.
- `scripts/validate_submission.py` — Required-field gate matching the platform AAE form's required rules. Run before any submit path; exit code 0 = valid, 1 = invalid. The skill MUST call this in Step 4.5 before invoking `submit_via_connector.py` or `build_submission_artifact.py`. Rejects unfilled review placeholders (`placeholder_unfilled`), canonicalizes the question shape, and normalizes short-form guidance to the canonical Salesforce picklist labels.
- `scripts/aae_common.py` — Shared helpers imported by the scripts above: canonical question serialization (list or string → `"1. Q\n2. Q"`, sub-labels stripped), guidance canonicalization (`"Strategic / Executive"` / `"Technical / Tactical"`), and unfilled-placeholder detection. Not a CLI.
