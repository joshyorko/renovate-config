#!/usr/bin/env node
// Exercise the actual raw-inheritance path against this candidate, without writes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

function renovateDist() {
  const candidates = [process.env.RENOVATE_PACKAGE_ROOT, '/usr/local/renovate/dist'];
  for (const directory of (process.env.PATH ?? '').split(path.delimiter)) {
    try {
      candidates.push(path.dirname(fs.realpathSync(path.join(directory, 'renovate-config-validator'))));
    } catch {}
  }
  const found = candidates.find(directory => directory && fs.existsSync(path.join(directory, 'workers/repository/init/inherited.js')));
  assert.ok(found, 'The installed Renovate package must expose the raw inheritance implementation');
  return found;
}

// The action mounts this entrypoint at /; sibling imports must use the repo mount.
await import(pathToFileURL(path.join(
  process.env.RENOVATE_CANDIDATE_ROOT ?? process.cwd(),
  'scripts/verify_patchraptor_commands.mjs',
)).href);

const dist = renovateDist();
const load = relative => import(pathToFileURL(path.join(dist, relative)).href);
const { init } = await load('logger/index.js');
const { GlobalConfig } = await load('config/global.js');
const { setPlatformApi } = await load('modules/platform/index.js');
const { default: platformApis } = await load('modules/platform/api.js');
const { mergeInheritedConfig } = await load('workers/repository/init/inherited.js');
const { mergeChildConfig } = await load('config/utils.js');
const { validateConfig } = await load('config/validation.js');
const { getOptions } = await load('config/options/index.js');
const { Vulnerabilities } = await load('workers/repository/process/vulnerabilities.js');
const { applyPackageRules } = await load('util/package-rules/index.js');
const { extractPackageFile } = await load('modules/manager/custom/regex/index.js');
const { doAutoReplace } = await load('workers/repository/update/branch/auto-replace.js');
await init();
GlobalConfig.set({ platform: 'github', hostRules: [] });

const candidateRoot = process.env.RENOVATE_CANDIDATE_ROOT ?? process.cwd();
const policiesRoot = process.env.RENOVATE_POLICIES_ROOT ?? path.dirname(candidateRoot);
const candidate = fs.readFileSync(path.join(candidateRoot, 'org-inherited-config.json'), 'utf8');
let reads = 0;
const getCandidate = async (file, repo) => {
  assert.equal(file, 'org-inherited-config.json');
  assert.equal(repo, 'joshyorko/renovate-config');
  reads += 1;
  return candidate;
};
platformApis.set('github', { ...platformApis.get('github'), getRawFile: getCandidate });
setPlatformApi('github');
const defaults = getOptions().find(option => option.name === 'vulnerabilityAlerts').default;
const engine = new Vulnerabilities(null);
const centralPreset = 'github>joshyorko/renovate-config:org-inherited-config';
let imageManagers;

for (const [repository, name] of [
  ['joshyorko/codex-action-server', 'cas.json'],
  ['joshyorko/mcp-tunnel-kit', 'tunnel.json'],
]) {
  // This calls raw validateConfig('inherit', ...) before any preset massaging.
  const inherited = await mergeInheritedConfig({
    repository, parentOrg: 'joshyorko', topLevelOrg: 'joshyorko',
    inheritConfig: true, inheritConfigStrict: true,
    inheritConfigRepoName: 'joshyorko/renovate-config',
    inheritConfigFileName: 'org-inherited-config.json', secrets: {}, variables: {},
  });
  const local = JSON.parse(fs.readFileSync(path.join(policiesRoot, name), 'utf8'));
  assert.deepEqual(local.extends, [centralPreset]);
  assert.equal((await validateConfig('repo', local)).errors.length, 0);
  // The exact central preset pointer resolves to the candidate above, not main.
  // Keep every local policy setting; only the now-resolved pointer is removed.
  const resolvedLocal = mergeChildConfig(inherited, { ...local, extends: [] });
  const effective = mergeChildConfig(inherited, resolvedLocal);
  if (repository === 'joshyorko/mcp-tunnel-kit') imageManagers = JSON.parse(candidate).customManagers;
  const vulnerabilityAlerts = mergeChildConfig(defaults, effective.vulnerabilityAlerts ?? {});
  const affected = { package: { ecosystem: 'PyPI', name: 'mcp' }, ranges: [] };
  const vulnerability = { id: 'GHSA-fixture', summary: 'Fixture', details: 'Synthetic policy fixture', references: [], affected: [affected] };
  const rule = engine.vulnerabilityToPackageRules({ vulnerability, affected, packageName: 'mcp', depVersion: '2.0.0', fixedVersion: '>=2.0.1', datasource: 'pypi', packageFileConfig: { vulnerabilityAlerts } });
  const applied = await applyPackageRules({
    ...effective, repository, manager: 'pip_requirements', packageFile: 'requirements.txt',
    updateType: 'patch', depName: 'mcp', packageName: 'mcp', currentValue: '2.0.0',
    currentVersion: '2.0.0', versioning: 'pep440', datasource: 'pypi',
    packageRules: [...effective.packageRules, rule],
  }, 'pre-lookup');
  const result = mergeChildConfig(applied, applied.force);
  assert.equal(result.dependencyDashboardApproval, true);
  assert.equal(result.prCreation, 'status-success');
  assert.equal(result.automerge, false);
  assert.equal(result.platformAutomerge, false);
  console.log(JSON.stringify({ repository, rawCandidateInheritance: true, localApprovalAndCi: true }));
}
assert.equal(reads, 2);

const liveContent = fs.readFileSync(path.join(policiesRoot, 'images.json'), 'utf8');
const liveImages = JSON.parse(liveContent);
assert.equal(imageManagers.length, 2);
for (const manager of imageManagers) {
  assert.equal(extractPackageFile(liveContent, 'config/deploy-images.json', manager)?.deps.length, 1);
}
for (const order of ['repository-first', 'digest-first']) {
  const fixture = structuredClone(liveImages);
  for (const role of ['executor', 'tunnel']) {
    const { repository, digest, ...rest } = fixture.images[role];
    fixture.images[role] = order === 'repository-first' ? { repository, digest, ...rest } : { digest, repository, ...rest };
  }
  const content = JSON.stringify(fixture, null, 2);
  for (const manager of imageManagers) {
    const extracted = extractPackageFile(content, 'config/deploy-images.json', manager);
    assert.equal(extracted?.deps.length, 1, `${order}: each role must extract exactly one image`);
    const dependency = extracted.deps[0];
    const role = dependency.depName === 'ghcr.io/usefulsoftwareco/executor-selfhost' ? 'executor' : 'tunnel';
    assert.equal(dependency.depName, role === 'executor' ? 'ghcr.io/usefulsoftwareco/executor-selfhost' : 'ghcr.io/openai/tunnel-client');
    for (const update of [
      { newValue: '9.8.7', newDigest: 'sha256:' + '0'.repeat(64) },
      { newDigest: 'sha256:' + '1'.repeat(64) },
      { newValue: '9.8.7' },
    ]) {
      const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'patchraptor-image-proof-'));
      try {
        GlobalConfig.set({ platform: 'github', hostRules: [], localDir: temp });
        fs.mkdirSync(path.join(temp, 'config'));
        fs.writeFileSync(path.join(temp, 'config/deploy-images.json'), content);
        const updated = await doAutoReplace({
          ...manager, ...dependency, ...update,
          manager: 'regex', packageFile: 'config/deploy-images.json', depIndex: 0,
        }, content, false);
        const parsed = JSON.parse(updated);
        const tag = update.newValue ?? dependency.currentValue;
        assert.equal(parsed.images[role].repository, `${dependency.depName}:${role === 'tunnel' ? 'v' : ''}${tag}`);
        assert.equal(parsed.images[role].digest, update.newDigest ?? dependency.currentDigest);
        for (const untouched of ['cas', 'schema_proxy', role === 'executor' ? 'tunnel' : 'executor']) {
          assert.deepEqual(parsed.images[untouched], fixture.images[untouched]);
        }
      } finally {
        fs.rmSync(temp, { recursive: true, force: true });
      }
    }
  }
  console.log(JSON.stringify({ imageKeyOrder: order, actualRenovateExtractAndReplacement: true }));
}
