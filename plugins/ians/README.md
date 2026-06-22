# IANS

A bundle of [Claude Code](https://code.claude.com) and [Claude Cowork](https://claude.ai) skills published by [IANS](https://www.iansresearch.com). All skills in this plugin gate on the IANS MCP connector and use the user's active IANS entitlements to decide what they can do.

## Skills in this plugin

| Skill | Description |
| --- | --- |
| [`request-ask-an-expert`](./skills/request-ask-an-expert/SKILL.md) | Submit a faculty-led Ask-an-Expert (AAE) request to IANS. Conversational form-filler that mirrors the platform AAE form, validates required fields, and submits through the IANS MCP connector (with graceful failure handling when the connector is unavailable). |

More IANS skills will be added under [`skills/`](./skills/) over time. Skills inside this plugin can chain to each other via `${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>/SKILL.md` references — they share one plugin root.

## Requirements

- Claude Code or Claude Cowork
- Active IANS account with MCP access
- **IANS MCP** connected and authenticated (for `ians_whoami` and any submission tooling each skill needs)
- **Python 3** on the path when a skill runs scripts via the Bash tool

## Installation

```txt
/plugin marketplace add ians-research/claude-skills
/plugin install ians@ians-tools
```

Installing the plugin enables every skill it contains. Skills self-invoke based on conversation context, or you can call them explicitly (the exact slash command depends on Claude Code's plugin naming).

## Example prompts

These prompts exercise the `request-ask-an-expert` skill end-to-end. With the IANS MCP connected and AAE entitlement active, the skill recommends a delivery method, drafts a form-shaped review you can edit in chat, validates the required fields, and submits through the connector. (Without the connector it stops and explains how to connect; without entitlement it ends gracefully.)

1. **Ask-an-Expert call with a deadline**

   > Set up an Ask-an-Expert call about our PCI DSS 4.0 transition. I present a recommendation to the steering committee next Friday and want faculty input first.

   The skill recommends a **Phone** consultation, parses "next Friday" into a deadline, sets the expedite flag, surfaces the 8–12 business-day faculty turnaround so you can judge whether the timeline is tight, then submits after you confirm the review.

2. **Faculty Poll across multiple faculty**

   > I'd like a Faculty Poll on whether peers are adopting zero-trust segmentation, which vendors they prefer, and how to sequence identity vs. network controls.

   The skill drafts a **Faculty Poll** (1–3 questions, 4–6 business-day turnaround), runs the poll-fit check, and — if the questions read more like a discussion than a poll — offers to switch you to a Phone call. Both paths submit through the connector.

3. **Escalation from a high-stakes situation**

   > We just contained a breach and I'm prepping the board update with counsel involved. Can I get an IANS expert's read on how to frame it?

   The skill leads with a one-line rationale for why faculty review fits, grounds the request in relevant IANS content first, drafts the Driver and Questions for your review, and submits. It files the request only — it does not improvise incident-response advice or name other IANS services.

4. **Let IANS pick the format**

   > I'm not sure whether I need a call or written input — set up an Ask-an-Expert about emerging cyber-insurance trends over the next 12 months.

   The skill uses the **Undecided** resolution (IANS Client Services selects the best avenue), asks you to pick the guidance type (Strategic / Executive, Technical / Tactical, or both) rather than guessing, and submits once the review passes validation.

After any successful submission, an IANS Client Services coordinator contacts you within 24–48 hours to schedule; faculty turnaround follows after scheduling.

## Support

For plugin issues, open an issue in this repo. For IANS platform entitlement or account questions, contact `support@iansresearch.com`.
