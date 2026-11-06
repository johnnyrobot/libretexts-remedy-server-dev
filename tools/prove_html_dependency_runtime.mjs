// Benign public-API compatibility check for the installed production graph.
// No exploit payload, network access, browser launch or parent-directory walk.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile, mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';

const toolsRoot = path.resolve(process.argv[2] ?? '/opt/remedy-html-tools');
const require = createRequire(path.join(toolsRoot, 'package.json'));
const sourceRoot = path.resolve(import.meta.dirname, '..');
const top = JSON.parse(await readFile(path.join(toolsRoot, 'package.json'), 'utf8'));
assert.equal(top.overrides, undefined);
assert.deepEqual(Object.keys(top.dependencies).sort(), ['axe-core', 'lighthouse', 'pa11y']);
const versions = {};
for (const name of Object.keys(top.dependencies)) {
  const installed = require(name + '/package.json');
  assert.equal(installed.version, top.dependencies[name]);
  versions[name] = installed.version;
}
const assets = JSON.parse(await readFile(path.join(sourceRoot, 'src/project_remedy/html_tools/assets.json'), 'utf8'));
for (const [name, expected] of Object.entries(assets)) {
  assert.equal(createHash('sha256').update(await readFile(require.resolve(name))).digest('hex'), expected);
}
const lighthouseRequire = createRequire(require.resolve('lighthouse/package.json'));
const sentryRequire = createRequire(lighthouseRequire.resolve('@sentry/node/package.json'));
const bundlerRequire = createRequire(sentryRequire.resolve('@sentry/bundler-plugins/package.json'));
const {glob} = bundlerRequire('glob');
const globRequire = createRequire(bundlerRequire.resolve('glob/package.json'));
const {minimatch} = globRequire('minimatch');
const temporary = await mkdtemp(path.join(tmpdir(), 'remedy-lt227-'));
try {
  await mkdir(path.join(temporary, 'nested'));
  for (const name of ['a.html', 'nested/b.html', 'nested/plain.txt']) {
    await writeFile(path.join(temporary, name), 'finite synthetic fixture');
  }
  assert.deepEqual((await glob('**/*.html', {cwd: temporary, nodir: true})).sort(), ['a.html', 'nested/b.html']);
  assert.equal(minimatch('nested/b.html', '**/*.html'), true);
  assert.equal(minimatch('nested/plain.txt', '**/*.html'), false);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(async () => glob('**/*', {cwd: temporary, signal: controller.signal}),
    error => error.name === 'AbortError');
  // Cancellation must leave a subsequent finite, independent walk usable.
  assert.deepEqual((await glob('*.html', {cwd: temporary, nodir: true})).sort(), ['a.html']);
  console.log(JSON.stringify({node: process.version, versions, assetIntegrity: true,
    finiteWalk: true, ordinaryPatterns: true, abortedWalkRejected: true, subsequentWalk: true}));
} finally {
  await rm(temporary, {recursive: true, force: true});
}
