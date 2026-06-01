# IANS Claude Skills

Public marketplace of [Claude Code](https://code.claude.com) and [Claude Cowork](https://claude.ai) plugins published by [IANS Research](https://www.iansresearch.com).

This repo publishes **Claude plugins** (skills + supporting assets). Plugins that talk to IANS require the user to connect the **IANS Research MCP** server (see each plugin README). Some plugins ship a **full skill** in-repo (workflow, prompts, scripts); others may remain thin routers over a hosted workflow.

## Available plugin and skills

| Plugin | Skill | Description |
| --- | --- | --- |
| [`ians`](./plugins/ians) | [`request-ask-an-expert`](./plugins/ians/skills/request-ask-an-expert/SKILL.md) | Submit a faculty-led Ask-an-Expert (AAE) request to IANS. Form-shaped review, Python validation/submission helpers, connector-only submit path with graceful failure when the MCP is unavailable. Submit-only in this release. |

## Installation

From inside Claude Code:

```txt
/plugin marketplace add ians-research/claude-skills
/plugin install ians@ians-tools
```

Installing the `ians` plugin enables every IANS skill it contains.

## How these plugins are structured

Each plugin lives under `plugins/<name>/` with a `.claude-plugin/plugin.json` manifest and one or more `skills/<skill-name>/SKILL.md` directories. The `ians` plugin is the IANS Research bundle: every IANS-branded skill lives under [`plugins/ians/skills/`](./plugins/ians/skills/), so they share one plugin root and can chain to each other via `${CLAUDE_PLUGIN_ROOT}/skills/<skill-name>/SKILL.md`. Each skill ships its supporting assets (e.g. `scripts/` for Python helpers, `evals/` for repeatable checks) alongside its `SKILL.md`.

This layout follows Anthropic's [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces) and [plugins reference](https://docs.claude.com/en/docs/claude-code/plugins-reference) spec.

## Repository layout

```txt
claude-skills/
├── .claude-plugin/
│   └── marketplace.json            # marketplace catalog
└── plugins/
    └── ians/                       # IANS Research bundle (one plugin, many skills)
        ├── .claude-plugin/
        │   └── plugin.json         # plugin manifest
        ├── README.md
        └── skills/
            └── request-ask-an-expert/
                ├── SKILL.md
                ├── scripts/        # draft, validate, submit, poll-fit check
                └── evals/          # scenario fixtures (dev-only, not shipped)
```

## Adding a new IANS skill

Drop a new directory under [`plugins/ians/skills/<skill-name>/`](./plugins/ians/skills/):

```txt
plugins/ians/skills/<new-skill-name>/
├── SKILL.md
└── scripts/        # optional, Python or shell helpers
```

[`scripts/build-skill-zip.mjs`](./scripts/build-skill-zip.mjs) walks `plugins/*/skills/*`, so the new skill is auto-discovered — no [`marketplace.json`](./.claude-plugin/marketplace.json) edits required. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full `SKILL.md` frontmatter contract (including the `metadata.description_short` rule for Claude.ai/Desktop uploads), validation steps, and the public-release hygiene checklist.

## Adding a new (non-IANS) plugin

For a plugin that is not an IANS skill, create a sibling directory under `plugins/`:

```txt
plugins/<plugin-name>/
├── .claude-plugin/plugin.json
├── README.md
└── skills/<skill-name>/
    └── SKILL.md
```

Then add a corresponding entry to [`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json) using `"source": "<plugin-name>"` (shorthand enabled by `metadata.pluginRoot`). See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the marketplace-entry field reference.

## Releasing skill zips (for Claude.ai / Claude Desktop)

Claude Code installs plugins straight from this repo. To make a skill usable on **Claude.ai** (web) or **Claude Desktop**, end users instead upload a `.zip` of the skill via Settings → Capabilities → Skills. This repo ships a builder that produces those zips.

Prereqs: Node.js 20+.

```bash
npm install
npm run build:skills           # builds every skill under plugins/*/skills/*
npm run build:skill -- ians    # build one plugin only (by plugin directory name)
node scripts/build-skill-zip.mjs --check       # validate without writing zips
```

Each skill produces `dist/<skill-name>-<version>.zip` and a matching `.sha256`. The zip contains a single top-level `<skill-name>/` directory with `SKILL.md` at its root, which is the layout Claude.ai expects. Developer-only files (`evals/`, `__pycache__`, `*.pyc`, `.DS_Store`, etc.) are excluded automatically.

**Frontmatter rules the builder enforces.** Claude.ai caps the SKILL.md `description` at 200 characters, but the Claude Code marketplace tolerates a much longer trigger paragraph. To keep one source SKILL.md that works for both, add a `description_short` under `metadata:`:

```yaml
---
name: my-skill
description: "Long, trigger-rich description used by Claude Code..."
metadata:
  version: "0.1.0"
  description_short: "Short (<=200 char) summary used in the Claude.ai/Desktop upload."
---
```

The builder substitutes `description_short` into the zipped SKILL.md's `description` and drops the `description_short` helper. If `description_short` is missing **and** the long `description` is over 200 chars, the build fails with a clear message.

### Cutting a release

Tag a commit with a `v*` tag and push it. The `Release skill zips` workflow builds every skill and attaches the zips (plus their `.sha256`) to a GitHub Release.

```bash
git tag v1.0.0
git push origin v1.0.0
```

Pull requests run the same builder in `--check` mode so frontmatter regressions surface in CI before merge.

## Trust and safety

These plugins may call tools on the IANS platform MCP server. Review the source of any plugin in this repo before installing. For questions about the IANS platform itself, contact `support@iansresearch.com`.

## License

See [LICENSE](./LICENSE).
