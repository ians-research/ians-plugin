# IANS

The IANS plugin for [Claude Code](https://code.claude.com) and [Claude Cowork](https://claude.ai), published by [IANS](https://www.iansresearch.com). It bundles the **IANS MCP** connector, which exposes the IANS platform's tools (gated by the user's active IANS entitlements) directly to Claude.

## What's in this plugin

This plugin is **connector-only** in this release: it ships the bundled IANS MCP connector (declared in [`.mcp.json`](./.mcp.json)) and no skills. IANS skills may be added under a `skills/` directory over time; when present, they share this plugin root and can chain to each other via `${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>/SKILL.md` references.

## Requirements

- Claude Code, Claude Desktop, or Claude Cowork
- Active IANS account with MCP access
- **IANS MCP** — bundled with this plugin (declared in [`.mcp.json`](./.mcp.json)). How you connect it depends on the app:
  - **Claude Code** — registers automatically when the plugin is installed. On first use you complete a one-time IANS sign-in (OAuth) so the IANS tools (e.g. `ians_whoami`) can authenticate. No manual setup.
  - **Claude Desktop** — the bundled connector is *not* auto-registered (plugin auto-registration is a Claude Code feature). Add it once yourself via **Settings → Connectors → Add custom connector**, using the remote MCP URL `https://mcp.iansresearch.com/mcp`, then complete the one-time IANS sign-in. On Team/Enterprise plans a workspace **Owner** adds the connector and members enable it.
  - **Claude Cowork** — end users can't add remote MCP servers directly, so the IANS connector is made available by your organization's admin (managed MCP servers / organization plugins) or from the Claude Connector Directory. Contact your IANS account team if it isn't already available in your workspace.

## Installation

```txt
/plugin marketplace add ians-research/ians-plugin
/plugin install ians@ians-tools
```

**In Claude Code**, installing the plugin registers the bundled IANS MCP connector automatically (no separate `/mcp` setup); the first time a tool calls the connector, Claude Code prompts you to sign in to IANS once (OAuth). On **Claude Desktop and Claude Cowork**, the bundled connector is not auto-registered (that's a Claude Code feature) — see [Requirements](#requirements) for the per-app connect steps.

Once connected, the IANS platform's tools are available to Claude directly, gated by your active IANS entitlements.

## Support

For plugin issues, open an issue in this repo. For IANS platform entitlement or account questions, contact `support@iansresearch.com`.
