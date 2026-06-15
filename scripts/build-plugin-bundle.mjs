#!/usr/bin/env node
// Build a whole-plugin bundle from each plugins/<plugin>/ directory in this
// repo, suitable for Claude Desktop's "Personal plugins -> + -> Create Plugin
// -> Upload Plugin" flow.
//
// Output (per plugin):
//   dist/<plugin>-<version>.zip       <- upload this in Claude Desktop today
//   dist/<plugin>-<version>.plugin    <- byte-identical copy with the .plugin
//                                        extension the file picker advertises
//   dist/<plugin>-<version>.zip.sha256
//
// IMPORTANT — .zip vs .plugin: Claude Desktop's "Upload Plugin" file picker
// lists BOTH .zip and .plugin as selectable types, but the upload backend
// currently ingests only .zip and silently rejects .plugin
// (anthropics/claude-code#40414). We still emit the .plugin copy so it is ready
// the day the backend accepts the extension, but end users should upload the
// .zip. Both files have identical bytes/contents — only the extension differs.
//
// Archive layout (zip root == plugin root, NO wrapper folder), per the plugin
// spec: .claude-plugin/plugin.json lives at the archive root and skills/,
// commands/, agents/, etc. sit beside it at the root — never nested inside
// .claude-plugin/.
//
// Each skill's SKILL.md frontmatter is rewritten the same way build-skill-zip.mjs
// does it: metadata.description_short (<=200 chars) becomes the `description`,
// so the same source SKILL.md keeps a verbose Claude Code trigger paragraph
// while still passing the stricter claude.ai/Desktop description limit.
//
// Usage:
//   node scripts/build-plugin-bundle.mjs                 # build every plugin
//   node scripts/build-plugin-bundle.mjs <plugin-name>   # build one plugin only
//   node scripts/build-plugin-bundle.mjs --check         # validate without writing files

import { createHash } from 'node:crypto';
import {
  copyFileSync,
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

// Files/dirs we never ship in the user-facing bundle. Evals and bytecode are
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

// Minimal YAML frontmatter parser focused on the fields we use (name,
// metadata.version, metadata.description_short, description). Mirrors
// build-skill-zip.mjs so both builders agree on how SKILL.md is read.
function parseFrontmatter(src) {
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

function findPlugins(onlyPlugin) {
  if (!existsSync(pluginsDir)) {
    throw new Error(`plugins/ directory not found at ${pluginsDir}`);
  }
  const plugins = [];
  for (const name of readdirSync(pluginsDir)) {
    const pluginDir = path.join(pluginsDir, name);
    if (!statSync(pluginDir).isDirectory()) continue;
    if (onlyPlugin && name !== onlyPlugin) continue;
    const manifestPath = path.join(pluginDir, '.claude-plugin', 'plugin.json');
    if (!existsSync(manifestPath)) continue;
    plugins.push({ name, pluginDir, manifestPath });
  }
  return plugins;
}

function validatePlugin({ name, pluginDir, manifestPath }) {
  const errors = [];
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  } catch (err) {
    return { manifest: null, version: null, skills: [], errors: [`plugin.json is not valid JSON: ${err.message}`] };
  }

  if (!manifest.name) errors.push('plugin.json missing `name`');
  if (manifest.name && manifest.name !== name)
    errors.push(`plugin.json name "${manifest.name}" does not match directory "${name}"`);
  if (manifest.name && !NAME_PATTERN.test(manifest.name))
    errors.push(`name must match ${NAME_PATTERN} (lowercase, digits, hyphens, max 64 chars)`);
  const version = manifest.version;
  if (!version) errors.push('plugin.json missing `version`');

  // Validate each skill's SKILL.md the same way the skill-zip builder does.
  const skills = [];
  const skillsRoot = path.join(pluginDir, 'skills');
  if (existsSync(skillsRoot)) {
    for (const skill of readdirSync(skillsRoot)) {
      const skillDir = path.join(skillsRoot, skill);
      if (!statSync(skillDir).isDirectory()) continue;
      const skillMdPath = path.join(skillDir, 'SKILL.md');
      if (!existsSync(skillMdPath)) continue;

      const { data } = parseFrontmatter(readFileSync(skillMdPath, 'utf8'));
      if (!data.name) errors.push(`skills/${skill}: SKILL.md missing \`name\``);
      if (data.name && data.name !== skill)
        errors.push(`skills/${skill}: SKILL.md name "${data.name}" does not match directory "${skill}"`);
      if (!data.description) errors.push(`skills/${skill}: SKILL.md missing \`description\``);

      const meta = data.metadata && typeof data.metadata === 'object' ? data.metadata : {};
      const effectiveDescription = meta.description_short || data.description || '';
      if (effectiveDescription.length > CLAUDE_AI_DESCRIPTION_LIMIT) {
        errors.push(
          `skills/${skill}: description for upload is ${effectiveDescription.length} chars, ` +
            `must be <= ${CLAUDE_AI_DESCRIPTION_LIMIT}. Add metadata.description_short to SKILL.md.`,
        );
      }
      skills.push({ skill, skillMdPath });
    }
  }

  return { manifest, version, skills, errors };
}

function rewriteSkillMd(raw) {
  const { data, body } = parseFrontmatter(raw);
  const meta = data.metadata && typeof data.metadata === 'object' ? data.metadata : {};
  const description = meta.description_short || data.description || '';
  const version = meta.version || '';
  const escDesc = description.replace(/"/g, '\\"');
  let frontmatter = '---\n' + `name: ${data.name}\n` + `description: "${escDesc}"\n`;
  if (version) {
    frontmatter += 'metadata:\n' + `  version: "${version}"\n`;
  }
  frontmatter += '---\n\n';
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
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.isFile()) out.push(full);
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

async function buildBundle({ name, pluginDir, version }) {
  const baseName = `${name}-${version}`;
  const zipPath = path.join(distDir, `${baseName}.zip`);
  const pluginPath = path.join(distDir, `${baseName}.plugin`);
  await mkdir(distDir, { recursive: true });
  if (existsSync(zipPath)) rmSync(zipPath);
  if (existsSync(pluginPath)) rmSync(pluginPath);

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

  // Walk the whole plugin dir; the manifest at .claude-plugin/plugin.json and
  // everything else land at the archive root (no wrapper folder). SKILL.md
  // files get their frontmatter rewritten on the way in.
  const files = walk(pluginDir);
  for (const file of files) {
    const rel = path.relative(pluginDir, file).split(path.sep).join('/');
    if (!shouldInclude(rel)) continue;
    const isSkillMd = /^skills\/[^/]+\/SKILL\.md$/.test(rel);
    if (isSkillMd) {
      archive.append(rewriteSkillMd(readFileSync(file, 'utf8')), { name: rel });
    } else {
      archive.file(file, { name: rel });
    }
  }

  await archive.finalize();
  await done;

  // The .plugin copy is byte-identical to the .zip — only the extension the
  // Desktop file picker shows differs.
  copyFileSync(zipPath, pluginPath);

  const size = statSync(zipPath).size;
  const sha = await sha256File(zipPath);
  const shaPath = `${zipPath}.sha256`;
  await new Promise((resolve, reject) => {
    const s = createWriteStream(shaPath);
    s.on('error', reject);
    s.on('close', resolve);
    s.end(`${sha}  ${baseName}.zip\n`);
  });

  return { zipPath, pluginPath, size, sha, shaPath };
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

async function main() {
  const args = parseArgs(process.argv);
  const plugins = findPlugins(args.plugin);

  if (plugins.length === 0) {
    console.error(
      args.plugin
        ? `No plugin with a .claude-plugin/plugin.json found at plugins/${args.plugin}/`
        : 'No plugins with a .claude-plugin/plugin.json found under plugins/*/',
    );
    process.exit(1);
  }

  let hadError = false;
  for (const p of plugins) {
    const { version, skills, errors } = validatePlugin(p);
    if (errors.length) {
      hadError = true;
      console.error(`\nx ${p.name}`);
      for (const e of errors) console.error(`  - ${e}`);
      continue;
    }
    console.log(`\n* ${p.name}  v${version}  (${skills.length} skill${skills.length === 1 ? '' : 's'})`);

    if (args.check) {
      console.log('  (check-only mode, skipping bundle write)');
      continue;
    }

    try {
      const { zipPath, pluginPath, size, sha } = await buildBundle({
        name: p.name,
        pluginDir: p.pluginDir,
        version,
      });
      console.log(`  wrote ${path.relative(repoRoot, zipPath)}  ${fmtBytes(size)}  (upload this)`);
      console.log(`  wrote ${path.relative(repoRoot, pluginPath)}  (identical copy; .plugin not yet accepted on upload)`);
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
