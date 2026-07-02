---
name: request-ask-an-expert
description: "Submit a faculty-led Ask-an-Expert (AAE) session at IANS. Triggers when the user asks to schedule an AAE call, talk to an IANS expert, get a 1:1 faculty consultation, request faculty time, or escalate a question to faculty review. Also triggers as a chained recommendation from other Ask IANS Skills when the model's synthesis hits the limits of unsupervised AI work (post-breach litigation prep, hostile board dynamics, novel regulatory situations, etc.). The default action is submission via the IANS MCP — direct connector write through `ians_request_aae`. The skill mirrors the platform AAE form field-for-field — same labels, same order, same conditional rules. This release supports submit mode only (branded scoping .docx is deferred until the IANS design system skill ships). Do not use for general AAE explanation, content browsing, or non-IANS expert systems."
metadata:
  version: "1.0.1"
  description_short: "Submit a faculty-led Ask-an-Expert request to IANS. Use when the user wants to schedule an AAE call, request faculty time, or escalate a question to IANS expert review."
---

# Request Ask-an-Expert

Conversational form-filler for the IANS platform Ask-an-Expert form. This release is **submit-only**: the skill drafts what it can from conversation context, presents a **form-shaped review** that mirrors the platform form's labels and order, lets the user edit fields in chat, validates, then submits via the IANS MCP connector.

User-facing prompts are quoted verbatim in this SKILL.md. Use the exact text — do not paraphrase. Consistency in wording matters; users learn the prompts and rely on them.

## Step 0 — Connector gate (non-negotiable)

Call `ians_whoami()` first. Cache the response.

If the call fails, the IANS connector isn't connected. Refuse and show this message verbatim (**Gate 1 — plugin installed, connector not connected**):

> The IANS skills run on the IANS connector, which isn't connected yet. Connect it in your Claude connector settings, then ask me again.
>
> Connecting requires IANS credentials. If you don't have them, your organization may not have IANS access yet — visit http://iansresearch.com to learn more.

This is the unentitled first-run experience for two audiences at once: clients who have IANS credentials are routed to connect; non-clients with no IANS relationship are routed to iansresearch.com (top-of-funnel). Never surface a raw error or a broken-tool state in place of this message.

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

Check connector-payload entitlement (AAE access) from the cached `ians_whoami` response.

If the user is entitled: continue.

If they aren't, show this message verbatim, then end gracefully without producing a submission or artifact (**Gate 2 — connected client, account not enabled for the connector**):

> **You're connected, but connector access isn't included in your current IANS subscription.** Connector access is a separate add-on. To get it, contact your IANS account manager at {account manager email} and ask for more information.

Render `{account manager email}` as the account manager email from the cached `ians_whoami` response when the connector exposes one; otherwise use `support@iansresearch.com`. Substitute the address into the sentence and keep every other word exactly as written. This is the entitlement/access path for existing clients — end gracefully, never surface a raw error or a broken-tool state.

## Step 2.5 — Ground the request in IANS content first (warm requests only)

**Cold-open gate.** Skip this entire step on a **cold-open** AAE request — one where the user's opening turn is just a request to file an AAE with no prior substantive conversation to ground (no topic or problem has been discussed in-conversation, and no context was chained in from another Ask IANS Skill). On a cold open, do NOT call `ians_search` for grounding, do NOT surface source candidates, and do NOT ask the user to pick a source — forcing a content-selection step here is an unrequested barrier to the creation flow. Proceed straight to Step 3 and let the `must_ask` placeholders gather the driver and questions (inventing nothing).

> **Scope note:** this does not reverse the grounding rule — it scopes it. Grounding still runs on **warm** requests (a real topic was discussed in-conversation, or another skill chained in with context). It only removes the cold-open barrier where there is nothing to ground yet.

When the request is **warm** (there is substantive conversation context or chained context to ground), continue:

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

**Turnaround & scheduling timing — canonical statement.** State this once, here; everywhere else in this skill *references* it instead of restating the numbers or re-warning about the distinction:

- **Faculty turnaround** is the faculty deliverable window, downstream — it begins *after* IANS Client Services schedules. The standard window per resolution is the one shown inline in each Resolution Type option above (**Phone / Undecided → 8-12 business days**, **Faculty Poll → 4-6 business days**). Expedite prioritizes the request but does not shorten the standard window.
- **First Client Services contact** is the *scheduling* timing: an IANS Client Services coordinator reaches out within **24-48 hours**. This is **separate from** faculty turnaround — never conflate the scheduling call with the faculty deliverable window.

When any later step needs to surface timing (Expedite comparison, deadline warning, post-submit confirmation, close), point back to this canonical statement rather than repeating the windows or the do-not-conflate warning.

Make a recommendation based on conversation context using `scripts/recommend_resolution.py` for structured reasoning. **Whether you state a "why this fits" rationale is conditional on the script finding a real signal** — a forced rationale where none exists nudges invention, which this skill forbids elsewhere.

**When `recommend_resolution.py` returns a signal** (non-empty `matched_signals`, i.e. a confident Phone/Faculty Poll recommendation): frame the recommendation as one line *after* the options, and lead with a rationale tied to the specific conversational signal.

> Based on your conversation, **{Phone | Faculty Poll}** fits because {one-line reason}. You can change it.

> Faculty review fits here because {specific signal in the conversation} — {what a faculty member adds that the AI can't}.

- The rationale must tie to a **specific signal** in the conversation, not a generic value-prop. Generic framing like "you might want to talk to an expert" is not enough.
- Examples:
  - "Faculty review fits here because you're heading into a board conversation with hostile dynamics — a Faculty member can rehearse the hard questions with you."
  - "Faculty review fits here because the regulatory framing is novel and post-breach — a Faculty member's judgment beats AI synthesis when the wrong frame creates legal exposure."

**When `recommend_resolution.py` returns NO signal** (empty `matched_signals` — e.g. a cold-open request with no problem yet on the table, where the script returns `recommendation: "Undecided"`): do **NOT** render a "fits because" line, and do **NOT** invent a rationale. Show the three Resolution Type options and let the user pick, with a neutral prompt:

> Which would you prefer? Pick an option above, or tell me a bit about what's prompting this and I'll suggest one.

Never put words in the user's mouth on the no-signal path — the rationale only appears once a real signal exists.

**Faculty Poll mis-scope nudge.** Run this check **only when the user selects Faculty Poll** — do not run `check_poll_fit.py` for Phone or Undecided resolutions.

When the user selects **Faculty Poll**, run `scripts/check_poll_fit.py` against the drafted questions (and driver if present):

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/scripts/check_poll_fit.py \
  --input <path-to-questions-json>
```

Input shape: `{"questions": <locked or draft question value>, "driver": "<optional driver>"}`.

If `suggest_phone` is true, surface this nudge verbatim (suggestion only — Poll remains the default):

> This reads more like a discussion than a poll — want me to switch to Phone? Faculty can go deeper in a call.

- If the user accepts the switch, change resolution to Phone and re-render the form-shaped review with Phone/Undecided sections.
- If the user keeps Poll, proceed with Faculty Poll unchanged — both paths are fully supported.
- When the user keeps Poll despite the nudge, emit this internal note verbatim (for heuristic tuning later; not shown to the user):

  > `[poll_nudge_declined] signals={matched_signals from check_poll_fit output} resolution=Faculty Poll`

  Do not block submission.

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

The locked payload must carry the **canonical picklist values exactly** — `"Strategic / Executive"` and `"Technical / Tactical"` (with spaces around the slash). Short forms like `"Strategic"` are silently dropped by the platform form. `infer_guidance.py` already emits the canonical strings, and `validate_submission.py` normalizes short-form aliases with a warning — don't hand-write the short form into the payload.

Skip section entirely for Faculty Poll.

### Additional details on your request

#### Would you like to expedite this request?

> Yes / No

**Always surface the faculty turnaround window here**, before the user decides — they can't make an informed expedite choice without seeing it. Render the canonical window for the selected resolution (from the Turnaround & scheduling timing statement above), whether or not a deadline has been parsed:

> **Turnaround for {resolution}:** {canonical window for the resolution} (faculty deliverable, after scheduling); expedited requests are prioritized.

(The 24-48h first Client Services contact and the scheduling-vs-turnaround distinction are already stated canonically above — reference them only if relevant; do not restate them here.)

If yes, render:

> **When is the deadline?** ({YYYY-MM-DD or [needs your input]})

Use `scripts/parse_urgency.py` to draft. Deadline must be ≥ today. If the parsed deadline is fewer than 14 calendar days out, append a warning:

> *Note: this is {N} calendar days away — shorter than the standard faculty turnaround for {resolution} (see the window in the options above). The expedite flag prioritizes your request, but it may still be tight.*

#### Email and submitter identity (server-side — do NOT render)

`ians_whoami` returns only entitlement flags (and, when on file, the *account manager's* contact) — it does **not** return the signed-in user's name or email. The connector sets the submitter identity and the reply-to email server-side from the authenticated IANS session.

- Do NOT read Email or Submitter name from `ians_whoami`.
- Do NOT render an `Email:` or `Submitter:` line, and never invent, guess, or placeholder an identity value.
- Omit `email_address` from the payload so the server uses the signed-in user's email. Set `email_address` only when the user explicitly asks to route replies to a *different* address — that's a deliberate reply-to override, not identity confirmation.

#### Scheduling (Phone/Undecided only)

> *"What dates work best for you to schedule this AAE?"* (optional)
>
> *"Feel free to share a calendar link or provide name/email of your executive assistant for scheduling."* (optional)

Use `scripts/parse_scheduling.py` to draft if the user mentioned scheduling in conversation. Both fields optional; if no input was found, show empty placeholders:

> Availability: `[optional]`
> Calendar link / EA: `[optional]`

Skip entirely for Faculty Poll.

## Step 4 — Present the review

**No partial reviews.** The first review message MUST render every required section for the resolution in a single message — never reveal a section only after the user prompts for it. The required section list is locked per resolution:

- **Phone / Undecided:** Resolution Type, Driver and Context, Specific Questions, **Other Details**, Guidance Type, Expedite + Deadline (with turnaround windows), **Scheduling**.
- **Faculty Poll:** Resolution Type, Driver and Context, Specific Questions, Expedite + Deadline (with turnaround windows). Faculty Poll **skips Other Details, Guidance, and Scheduling entirely** — do not show those headings.

Do not render an Email or Submitter section in any review — identity and reply-to email are set server-side from the authenticated session (see Step 3).

For Phone/Undecided, **Other Details** and **Scheduling** always render on the first pass, even when `parse_scheduling.py` / detail extraction returned nothing — show their `[optional]` placeholders so the user learns the fields exist:

> **Scheduling**
> Availability: `[optional]`
> Calendar link / EA: `[optional]`

Render the entire review as a single chat message with all required sections shown, conditional rules applied. Then ask verbatim:

> Does this look right? Reply with edits in plain language (e.g., "shorten the driver", "add to details that we're on AWS", "make question 3 more specific about IAM"), or say **submit** to send.

If the user replies with edits, apply them, re-render the affected fields with updated counts, and ask again. If the user says submit (or equivalent — *"send it"*, *"go ahead"*, *"looks good"*), proceed to Step 4.5 (validation), then Step 5.

## Step 4.5 — Required-field validation gate

**Hard rule — script execution is non-negotiable.** Before calling `ians_request_aae`, you MUST run `validate_submission.py` on the locked payload and check its exit code. Do NOT skip this step, do NOT eyeball validation, do NOT decide a field "looks fine" without running the script. The platform AAE form has required fields; the connector validates server-side but only after the user has been told the request was sent. This step is the client-side gate.

Run `validate_submission.py` and require `valid: true` before calling `ians_request_aae` directly. A `placeholder_unfilled` or empty required field MUST block the connector call. (The connector also rejects unfilled placeholders server-side as defense in depth, but never rely on that — it errors only after the user thinks the request was sent.)

**Canonical payload keys — use these EXACT keys; do NOT snake-case the review labels.** The form-shaped review uses friendly labels, but the locked payload JSON (the one you write to the temp file and pass to `validate_submission.py` and `ians_request_aae`) MUST use these exact keys:

| Review label | Payload key |
|---|---|
| Resolution Type | `resolution` |
| Driver and Context | `driver` |
| Specific Questions | `question` (a string, or an array of strings) |
| Other Details | `details` |
| Guidance Type | `guidance` (array) |
| Expedite | `expedite_request` (boolean) |
| Deadline | `deadline` (`YYYY-MM-DD`) |
| Availability | `availability` |
| Calendar link / EA | `calendarlink` |
| (no review field; optional reply-to override, usually omitted) | `email_address` |
| (no label) | `idempotency_key` (a fresh UUID) |
| (no label) | `context` (`ask_ians_id` / `related_ians_content`) |

Do NOT invent keys like `driver_and_context`, `specific_questions`, or `resolution_type` — the validator and connector expect the canonical keys above and will reject or mis-handle anything else.

Write the locked payload to a temp JSON (the same one Step 5 submits), then call:

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/scripts/validate_submission.py \
  --payload <path-to-payload.json>
```

(The validator does not need identity input — email is set server-side from the authenticated session and is not a client-side required field.)

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

## Step 5 — Submit via connector

**Precondition: Step 4.5 must have returned `valid: true`.** If you somehow reach this step without running validation, stop and run Step 4.5 first.

**Hard rule — connector submission is the only write path; never redirect to the web form.** When the IANS MCP is connected (Step 0 passed) and the user is entitled (Step 2 passed), this skill submits **through the connector**. Do NOT tell the user to go fill out the Ask-an-Expert form on iansresearch.com, and do NOT hand them a website link in place of submitting. The Beta connector counts as available: if `ians_request_aae` is registered, use it.

**Hard rule — submit by calling the `ians_request_aae` MCP tool directly.** In a live MCP session you MUST call the `ians_request_aae` tool directly with the canonical payload. Do NOT fabricate a success message. If the tool call fails, surface the error inline — never continue silently or pretend the request was sent.

1. Submit by calling the `ians_request_aae` MCP tool directly with the canonical connector payload — the **Input** shape documented in the Connector contract below.

2. **Status `submitted`** — connector accepted the request. Surface verbatim (the connector returns `integration_request_id` for idempotency and internal reference; do not render it, a case number, or a tracking link in the user-facing confirmation):

   > Your Ask-an-Expert request has been submitted. An IANS Client Services coordinator will contact you within **24-48 hours** to schedule. After scheduling, faculty turnaround is the standard window for your selected resolution (**{faculty_window}**, the canonical window from the options).

   Fill `{faculty_window}` from the canonical Turnaround & scheduling timing statement for the selected resolution — do not re-list both windows.

3. **Status `connector_unavailable`** — the connector could not accept the submission (`tool_not_registered`, `server_error`, or equivalent). Surface the error **inline** and offer these three options verbatim:

   > I couldn't submit your Ask-an-Expert request through the IANS connector right now. Your draft is still here — what would you like to do?
   >
   > 1. **Try again** — I'll retry the submission.
   > 2. **Contact Client Services** — reach your IANS account manager or Client Services team to submit manually.
   > 3. **Save as a scope draft** — hold the draft for now.

   - **Try again:** call `ians_request_aae` once more. Do not auto-retry in a loop.
   - **Contact Client Services:** end gracefully; the user's locked draft remains in chat for them to copy or reference.
   - **Save as a scope draft:** show the Step 1 scope-deferral message verbatim (*"Scoping doc support is coming once the IANS design system skill ships — for now I can only submit on your behalf or pause."*) and stop. Do not fabricate a .docx.

4. **Status `error`** — read `error_code` and surface `user_message`:
   - `entitlement_missing` — defect (gate should have caught it). Surface message, end.
   - `validation_failed` — return to Step 4 with `details` shown so the user revises.
   - `rate_limited` — surface message, don't auto-retry.
   - **Any other `error_code`** (unknown connector contract) — surface `user_message`, do **not** offer retry/contact/scope-draft options (`retryable: false`). Treat as a connector contract regression, not an availability outage. Preserve `details.original_error_code` if present.

## Step 6 — Confirm and close

End with:

1. A clear statement of what just happened.
2. The expected timeline — reuse the two windows from the Step 5 confirmation (Client Services scheduling vs. faculty turnaround). Do not re-list the numbers or re-warn about conflating them; the canonical statement and the distinction already live in the Resolution Type section and the Step 5 confirmation.

**Who follows up:** the response loop is coordinated by **IANS Client Services**, not by faculty directly. Faculty produce the deliverable; IANS Client Services contacts the client. When you tell the user who they'll hear from, say "an IANS Client Services coordinator" — never "you'll hear back from faculty."

Don't promise specific faculty members or specific dates.

## Connector contract

`ians_request_aae` submits directly to IANS when the connector is available. The skill calls this MCP tool directly. There is no JSON-artifact fallback — when the connector is unavailable, the skill surfaces graceful failure options (retry, contact Client Services, save as scope draft).

- **Input** matches the JSON shape the platform AAE form posts. `origin` and `submitter` are server-populated, NOT in the skill's input.
- **Output**: `status: "submitted"`, `integration_request_id` (request reference parsed from the destination system's status message; may be null — retained for idempotency and internal reference, not rendered to the user), `expected_response_window` (computed client-side from the resolution), `submitted_at`, `idempotency_key`. The connector does **not** return a case number or a portal tracking URL, and the skill renders neither `integration_request_id` nor a tracking link in the user-facing confirmation.
- **Error model**: `entitlement_missing`, `validation_failed`, `rate_limited`; transient/unavailable paths return `connector_unavailable` with retry/contact/scope-draft options. Unknown `error_code` values return `status: "error"` with `retryable: false` and `details.original_error_code` — not `connector_unavailable`.
- **Idempotency**: `idempotency_key` prevents duplicate cases on retry.

## Chain pattern — invoked from another skill

Other Ask IANS Skills can chain to this skill:

```
Read: ${CLAUDE_PLUGIN_ROOT}/skills/request-ask-an-expert/SKILL.md
```

Then invoke this skill for **submit** (this release does not support scope mode). Pass conversation context.

A chained invocation carries conversation context, so `recommend_resolution.py` will normally return a signal — when it does, lead with the one-line rationale from Step 3 ("Faculty review fits here because {signal} — {what faculty adds}") tied to that specific signal. The conditional-rationale rule applies identically to chained and self-triggered recommendations: if no signal is present, follow the no-signal path (show options, invent no rationale).

## Out of scope

- **Active-incident response advice** — when the user is in a live incident (see Step 0.5), this skill does NOT improvise IR playbooks, containment steps, or "while we wait" parallel work. It files the AAE and nothing more.
- **Naming or recommending other IANS services** — the skill never name-drops IANS ICC / Incident Command Center, retainers, or other offerings (including during an active incident). Routing to another service is a coordinator / account-manager decision, not the skill's. The only IANS pathway this skill offers is the AAE.
- **Branded scoping .docx** — deferred until the `ians-design-system` skill ships; Step 1 refuses doc-only requests with the verbatim message above.
- Internal stakeholders / attendees field — matches the platform form, which doesn't collect this.
- Preferred contact method (phone vs email) — matches the platform form's current commented-out state.
- Re-collection of email, phone, or submitter name — identity and the reply-to email are set server-side from the authenticated IANS session. `ians_whoami` does NOT expose the user's name or email (only entitlement flags), so the skill never displays, asks for, or fabricates them. `email_address` is sent only as a deliberate reply-to override.
- Ask IANS conversation linking via `ask_ians_id` — no Ask IANS → MCP bridge today.
- Faculty matching, faculty preferences, or faculty profile lookup — coordinator's job.
- Attachments / file uploads in the AAE request itself — not supported by the current connector contract.
- Submission on behalf of another user — entitlement model deferred to the platform "Import scoping doc" feature.
- Localization / non-English content — matches the platform.

## Scripts

- `scripts/recommend_resolution.py` — Heuristic resolution recommender (Phone / Faculty Poll / Undecided) with one-line reasoning.
- `scripts/check_poll_fit.py` — Detects mis-scoped Faculty Poll questions; emits a suggestion-only Phone nudge.
- `scripts/draft_payload.py` — Extracts Driver / Question / Details from conversation transcript with cap and resolution-specific shape enforcement.
- `scripts/infer_guidance.py` — Strategic / Technical inference. Empty array signals "must ask the user."
- `scripts/parse_urgency.py` — Natural language urgency cues → `expedite_request` + ISO date.
- `scripts/parse_scheduling.py` — Combined scheduling input → `availability` / `calendarlink` routing.
- `scripts/validate_submission.py` — Required-field gate matching the platform AAE form's required rules. Run before submit; exit code 0 = valid, 1 = invalid. The skill MUST call this in Step 4.5 before calling `ians_request_aae`. Rejects unfilled review placeholders (`placeholder_unfilled`), canonicalizes the question shape, and normalizes short-form guidance to the canonical picklist labels.
- `scripts/aae_common.py` — Shared helpers imported by the scripts above: canonical question serialization (list or string → `"1. Q\n2. Q"`, sub-labels stripped), guidance canonicalization (`"Strategic / Executive"` / `"Technical / Tactical"`), and unfilled-placeholder detection. Not a CLI.
