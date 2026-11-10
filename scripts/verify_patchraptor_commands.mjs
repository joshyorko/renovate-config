#!/usr/bin/env node
// Prove repository-scoped global options using the same pinned engine as the sweep.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.env.RENOVATE_CANDIDATE_ROOT ?? process.cwd();
const dist = process.env.RENOVATE_PACKAGE_ROOT ?? '/usr/local/renovate/dist';
const load = relative => import(pathToFileURL(path.join(dist, relative)).href);
const { init } = await load('logger/index.js');
const { GlobalConfig } = await load('config/global.js');
const { getRepositoryConfig } = await load('workers/global/index.js');
const { autodiscoverRepositories } = await load('workers/global/autodiscover.js');
const { setPlatformApi } = await load('modules/platform/index.js');
const { default: platformApis } = await load('modules/platform/api.js');
const { regEx } = await load('util/regex.js');
await init();
const runner = JSON.parse(fs.readFileSync(path.join(root, 'renovate-config.json')));
const expected = new Map([
  ['joshyorko/camp', ['node developer/update_dependency_locks.mjs']],
  ['joshyorko/review', [
    'node scripts/update-omp-pins.mjs',
    'node scripts/update-gh-pins.mjs',
    'node scripts/update-rtk-pins.mjs',
    'node scripts/update-requirements-ci-hashes.mjs',
    'node scripts/update-typesafe-pins.mjs',
  ]],
]);
assert.equal(runner.allowedCommands, undefined);
assert.deepEqual(runner.repositories.map(entry => entry.repository).sort(), [...expected.keys()].sort());
const originalPlatform = platformApis.get('github');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'patchraptor-command-proof-'));
try {
  platformApis.set('github', { ...originalPlatform, getRepos: async () => runner.autodiscoverFilter });
  setPlatformApi('github');
  const discovered = await autodiscoverRepositories(structuredClone(runner));
  assert.equal(discovered.repositories.length, runner.autodiscoverFilter.length);
  for (const repository of discovered.repositories) {
    const name = typeof repository === 'string' ? repository : repository.repository;
    GlobalConfig.set({ platform: 'github' });
    const config = await getRepositoryConfig({ ...runner, baseDir: temp }, repository);
    GlobalConfig.set(config);
    const patterns = GlobalConfig.get('allowedCommands') ?? [];
    const permits = command => patterns.some(pattern => regEx(pattern).test(command));
    const allowed = expected.get(name) ?? [];
    for (const command of [...expected.values()].flat()) {
      assert.equal(permits(command), allowed.includes(command), `${name}: ${command}`);
      for (const injected of [`${command}; id`, `${command} && id`, `${command}\nid`, `${command} --extra`, `echo ${command}`]) {
        assert.equal(permits(injected), false, `${name}: reject command extension`);
      }
    }
    assert.equal(patterns.length, allowed.length);
    console.log(JSON.stringify({ repository: name, allowedPostUpgradeCommands: allowed }));
  }
} finally {
  platformApis.set('github', originalPlatform);
  setPlatformApi('github');
  fs.rmSync(temp, { recursive: true, force: true });
}
