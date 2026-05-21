# IANS Research

A bundle of [Claude Code](https://code.claude.com) and [Claude Cowork](https://claude.ai) skills published by [IANS Research](https://www.iansresearch.com). All skills in this plugin gate on the IANS Research MCP connector and use the user's active IANS entitlements to decide what they can do.

## Skills in this plugin

| Skill | Description |
| --- | --- |
| [`request-ask-an-expert`](./skills/request-ask-an-expert/SKILL.md) | Submit a faculty-led Ask-an-Expert (AAE) request to IANS Research. Conversational form-filler that mirrors the platform AAE form, validates required fields, and either submits through the IANS MCP or produces a JSON submission artifact for your account manager. |

More IANS skills will be added under [`skills/`](./skills/) over time. Skills inside this plugin can chain to each other via `${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>/SKILL.md` references — they share one plugin root.

## Requirements

- Claude Code or Claude Cowork
- Active IANS Research account with MCP access
- **IANS Research MCP** connected and authenticated (for `ians_whoami` and any submission tooling each skill needs)
- **Python 3** on the path when a skill runs scripts via the Bash tool

## Installation

```txt
/plugin marketplace add ians-research/claude-skills
/plugin install ians@ians-tools
```

Installing the plugin enables every skill it contains. Skills self-invoke based on conversation context, or you can call them explicitly (the exact slash command depends on Claude Code's plugin naming).

## Support

For plugin issues, open an issue in this repo. For IANS platform entitlement or account questions, contact `support@iansresearch.com`.
