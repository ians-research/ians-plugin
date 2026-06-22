# Contributing

This repo publishes IANS plugins for Claude Code and Claude Cowork. This guide covers the `SKILL.md` frontmatter contract, the `marketplace.json` entry fields, the validation steps every change must pass, and the public-release hygiene checklist.

## Repository layout

```txt
claude-skills/
├── .claude-plugin/
│   └── marketplace.json            # marketplace catalog
└── plugins/
    └── ians/                       # IANS bundle (one plugin, many skills)
        ├── .claude-plugin/
        │   └── plugin.json         # plugin manifest
        ├── README.md
        └── skills/
            └── <skill-name>/
                ├── SKILL.md
                ├── scripts/        # optional Python/shell helpers
                └── evals/          # dev-only fixtures (not shipped)
```

## `SKILL.md` frontmatter contract

Every skill's `SKILL.md` begins with YAML frontmatter:

```yaml
---
name: my-skill
description: "Long, trigger-rich description used by Claude Code. May exceed 200 chars."
metadata:
  version: "1.0.0"
  description_short: "Short (<=200 char) summary used for the Claude.ai / Claude Desktop upload."
---
```

- **`name`** — kebab-case, unique within the plugin, matches the skill directory name.
- **`description`** — the trigger-rich paragraph Claude Code uses to decide when to invoke the skill. Claude Code tolerates a long description; Claude.ai caps it at **200 characters**.
- **`metadata.version`** — semver string; bump on any behavior change.
- **`metadata.description_short`** — required whenever `description` exceeds 200 chars. The skill-zip / plugin-bundle builders substitute this into the zipped `SKILL.md`'s `description` and drop the helper key, so one source `SKILL.md` works for both Claude Code and Claude.ai. If `description_short` is missing **and** `description` is over 200 chars, the build fails.

## `marketplace.json` entry fields

Each plugin gets one object in the top-level `plugins` array of [`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json):

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Plugin id; matches the plugin directory name and `plugin.json` `name`. |
| `displayName` | no | Human-friendly name shown in the directory. |
| `description` | yes | One-line summary of the plugin. |
| `source` | yes | **Repo-relative path that MUST start with `./`** — e.g. `"./plugins/ians"`. The bare-name shorthand (`"source": "ians"`) fails `claude plugin validate` with `plugins.N.source: Invalid input`, even though `metadata.pluginRoot` is set. Always use the explicit `./plugins/<name>` form. |
| `category` | no | Directory category (e.g. `research`). |
| `keywords` | no | Search keywords. |

`plugin.json` `version` and the matching `marketplace.json` entry must agree; `claude plugin tag` validates this before cutting a release tag.

## Validation steps

Run all of these before opening a PR. CI runs the bundle builder in `--check` mode on every PR, but validate locally first:

```bash
# 1. Validate the marketplace manifest (plain + strict)
claude plugin validate .claude-plugin/marketplace.json
claude plugin validate --strict .claude-plugin/marketplace.json

# 2. Validate the plugin manifest
claude plugin validate --strict plugins/ians

# 3. Build/verify skill zips and plugin bundles without writing files
node scripts/build-skill-zip.mjs --check
node scripts/build-plugin-bundle.mjs --check

# 4. Run any skill script tests (Python helpers)
python -m unittest discover -s plugins/ians/skills/<skill-name>/evals/tests -v
```

## Public-release hygiene checklist

This is a **public** repo. Before merging or cutting a release:

- [ ] `claude plugin validate --strict` passes for both the marketplace manifest and every plugin.
- [ ] No secrets, tokens, internal hostnames, customer names, or private URLs in any shipped file.
- [ ] Developer-only artifacts (`evals/`, `__pycache__`, `*.pyc`, `.DS_Store`) stay out of shipped bundles — the builders already exclude them; don't defeat that.
- [ ] `SKILL.md` `description_short` is present wherever `description` exceeds 200 chars.
- [ ] `plugin.json` and the `marketplace.json` entry agree on `name` and `version`.
- [ ] README and docs links resolve (no dangling references).

## Support

For IANS platform entitlement or account questions, contact `support@iansresearch.com`.
