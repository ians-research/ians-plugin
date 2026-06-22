#!/usr/bin/env node
// Build a claude.ai / Claude Desktop-compatible skill zip from each
// plugins/<plugin>/skills/<skill>/ directory in this repo.
//
// Output: dist/<skill-name>-<version>.zip and dist/<skill-name>-<version>.sha256
//
// The zipped SKILL.md uses `metadata.description_short` (<=200 chars) as the
// frontmatter `description`, so the same source SKILL.md can keep a verbose
// trigger paragraph for the Claude Code marketplace while still passing the
// stricter claude.ai upload validation.
//
// Usage:
//   node scripts/build-skill-zip.mjs                 # build every skill
//   node scripts/build-skill-zip.mjs <plugin-name>   # build one plugin only
//   node scripts/build-skill-zip.mjs --check         # validate without writing zips

import { createHash } from 'node:crypto';
import {
  createReadStream,
  createWriteStream,
  existsSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
} from 'node:fs';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ZipArchive } from 'archiver';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const pluginsDir = path.join(repoRoot, 'plugins');
const distDir = path.join(repoRoot, 'dist');

const CLAUDE_AI_DESCRIPTION_LIMIT = 200;
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

// Files/dirs we never ship in the user-facing zip. Evals and bytecode are
// developer-only artifacts.
const EXCLUDE_DIRS = new Set([
  'evals',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.git',
  '.vscode',
  '.idea',
  'node_modules',
]);
const EXCLUDE_FILE_EXACT = new Set(['.DS_Store', 'Thumbs.db', 'desktop.ini']);
const EXCLUDE_FILE_SUFFIX = ['.pyc', '.pyo', '.swp', '~'];

function parseArgs(argv) {
  const args = { check: false, plugin: null };
  for (const a of argv.slice(2)) {
    if (a === '--check') args.check = true;
    else if (a.startsWith('--')) throw new Error(`Unknown flag: ${a}`);
    else args.plugin = a;
  }
  return args;
}

// Minimal YAML frontmatter parser focused on the fields we use
// (name, metadata.version, metadata.description_short, description). The
// goal is to avoid a YAML dependency for a one-off build script while still
// supporting quoted multi-line description values.
function parseFrontmatter(src) {
  // Normalize line endings so CRLF (Windows checkouts) parses identically to LF.
  const norm = src.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (!norm.startsWith('---\n')) {
    throw new Error('SKILL.md is missing YAML frontmatter');
  }
  const end = norm.indexOf('\n---', 3);
  if (end === -1) throw new Error('SKILL.md frontmatter is not terminated');
  const block = norm.slice(4, end);
  const body = norm.slice(end + 4).replace(/^\n/, '');

  const out = {};
  const lines = block.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim() || line.trim().startsWith('#')) {
      i += 1;
      continue;
    }
    const topMatch = line.match(/^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$/);
    if (topMatch) {
      const [, key, rawVal] = topMatch;
      if (rawVal === '' || rawVal === '|' || rawVal === '>') {
        // Nested object or block scalar
        const child = {};
        let j = i + 1;
        while (j < lines.length && /^\s+/.test(lines[j])) {
          const sub = lines[j].match(/^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$/);
          if (sub) child[sub[1]] = unquote(sub[2]);
          j += 1;
        }
        out[key] = child;
        i = j;
      } else {
        out[key] = unquote(rawVal);
        i += 1;
      }
    } else {
      i += 1;
    }
  }
  return { data: out, body };
}

function unquote(v) {
  const t = v.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1).replace(/\\"/g, '"');
  }
  return t;
}

function findSkills(onlyPlugin) {
  if (!existsSync(pluginsDir)) {
    throw new Error(`plugins/ directory not found at ${pluginsDir}`);
  }
  const plugins = readdirSync(pluginsDir).filter((p) =>
    statSync(path.join(pluginsDir, p)).isDirectory(),
  );
  const skills = [];
  for (const plugin of plugins) {
    if (onlyPlugin && plugin !== onlyPlugin) continue;
    const skillsRoot = path.join(pluginsDir, plugin, 'skills');
    if (!existsSync(skillsRoot)) continue;
    for (const skill of readdirSync(skillsRoot)) {
      const skillDir = path.join(skillsRoot, skill);
      if (!statSync(skillDir).isDirectory()) continue;
      const skillMdPath = path.join(skillDir, 'SKILL.md');
      if (!existsSync(skillMdPath)) continue;
      skills.push({ plugin, skill, skillDir, skillMdPath });
    }
  }
  return skills;
}

function validateSkill({ skill, skillDir, skillMdPath }) {
  const raw = readFileSync(skillMdPath, 'utf8');
  const { data, body } = parseFrontmatter(raw);

  const errors = [];
  if (!data.name) errors.push('frontmatter missing `name`');
  if (data.name && data.name !== skill)
    errors.push(`frontmatter name "${data.name}" does not match directory "${skill}"`);
  if (data.name && !NAME_PATTERN.test(data.name))
    errors.push(`name must match ${NAME_PATTERN} (lowercase, digits, hyphens, max 64 chars)`);
  if (!data.description) errors.push('frontmatter missing `description`');

  const meta = data.metadata && typeof data.metadata === 'object' ? data.metadata : {};
  const version = meta.version;
  if (!version) errors.push('frontmatter missing `metadata.version`');

  const descShort = meta.description_short;
  const effectiveDescription = descShort || data.description || '';
  if (effectiveDescription.length > CLAUDE_AI_DESCRIPTION_LIMIT) {
    errors.push(
      `description for claude.ai upload is ${effectiveDescription.length} chars, ` +
        `must be <= ${CLAUDE_AI_DESCRIPTION_LIMIT}. ` +
        `Add metadata.description_short to SKILL.md.`,
    );
  }

  return { data, body, version, effectiveDescription, errors };
}

function buildSkillMdContents({ name, description, version, body }) {
  const escDesc = description.replace(/"/g, '\\"');
  const frontmatter =
    '---\n' +
    `name: ${name}\n` +
    `description: "${escDesc}"\n` +
    'metadata:\n' +
    `  version: "${version}"\n` +
    '---\n\n';
  return frontmatter + body;
}

function shouldInclude(relPath) {
  const segments = relPath.split(/[\\/]+/);
  for (const seg of segments) {
    if (EXCLUDE_DIRS.has(seg)) return false;
  }
  const base = segments[segments.length - 1];
  if (EXCLUDE_FILE_EXACT.has(base)) return false;
  for (const sfx of EXCLUDE_FILE_SUFFIX) {
    if (base.endsWith(sfx)) return false;
  }
  return true;
}

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else if (entry.isFile()) {
      out.push(full);
    }
  }
  return out;
}

async function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function buildZip({ skillDir, name, description, version, body }) {
  const zipName = `${name}-${version}.zip`;
  const zipPath = path.join(distDir, zipName);
  await mkdir(distDir, { recursive: true });
  if (existsSync(zipPath)) rmSync(zipPath);

  const output = createWriteStream(zipPath);
  const archive = new ZipArchive({ zlib: { level: 9 } });

  const done = new Promise((resolve, reject) => {
    output.on('close', resolve);
    output.on('error', reject);
    archive.on('warning', (err) => {
      if (err.code === 'ENOENT') console.warn(`zip warning: ${err.message}`);
      else reject(err);
    });
    archive.on('error', reject);
  });

  archive.pipe(output);

  const skillMd = buildSkillMdContents({ name, description, version, body });
  archive.append(skillMd, { name: `${name}/SKILL.md` });

  const files = walk(skillDir);
  for (const file of files) {
    const rel = path.relative(skillDir, file).split(path.sep).join('/');
    if (rel === 'SKILL.md') continue; // already injected with rewritten frontmatter
    if (!shouldInclude(rel)) continue;
    archive.file(file, { name: `${name}/${rel}` });
  }

  await archive.finalize();
  await done;

  const size = statSync(zipPath).size;
  const sha = await sha256File(zipPath);
  const shaPath = `${zipPath}.sha256`;
  await mkdir(distDir, { recursive: true });
  // Use createWriteStream for atomicity
  await new Promise((resolve, reject) => {
    const s = createWriteStream(shaPath);
    s.on('error', reject);
    s.on('close', resolve);
    s.end(`${sha}  ${zipName}\n`);
  });

  return { zipPath, size, sha, shaPath };
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

async function main() {
  const args = parseArgs(process.argv);
  const skills = findSkills(args.plugin);

  if (skills.length === 0) {
    console.error(
      args.plugin
        ? `No skills found under plugins/${args.plugin}/skills/`
        : 'No skills found under plugins/*/skills/',
    );
    process.exit(1);
  }

  let hadError = false;
  for (const s of skills) {
    const { data, body, version, effectiveDescription, errors } = validateSkill(s);
    const tag = `${s.plugin}/${s.skill}`;
    if (errors.length) {
      hadError = true;
      console.error(`\nx ${tag}`);
      for (const e of errors) console.error(`  - ${e}`);
      continue;
    }
    console.log(`\n* ${tag}  v${version}  (desc ${effectiveDescription.length} chars)`);

    if (args.check) {
      console.log('  (check-only mode, skipping zip write)');
      continue;
    }

    try {
      const { zipPath, size, sha } = await buildZip({
        skillDir: s.skillDir,
        name: data.name,
        description: effectiveDescription,
        version,
        body,
      });
      console.log(`  wrote ${path.relative(repoRoot, zipPath)}  ${fmtBytes(size)}`);
      console.log(`  sha256 ${sha}`);
    } catch (err) {
      hadError = true;
      console.error(`  build failed: ${err.message}`);
    }
  }

  if (hadError) process.exit(1);
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
