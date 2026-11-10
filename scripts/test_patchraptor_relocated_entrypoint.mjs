#!/usr/bin/env node
// Reproduce docker-cmd-file's relocated entrypoint without copying its siblings.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = process.env.RENOVATE_CANDIDATE_ROOT ?? process.cwd();
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'patchraptor-entrypoint-proof-'));
try {
  const entrypoint = path.join(temp, 'verify_patchraptor_inherited.mjs');
  fs.copyFileSync(path.join(root, 'scripts/verify_patchraptor_inherited.mjs'), entrypoint);
  const result = spawnSync(process.execPath, [entrypoint], {
    cwd: temp,
    env: { ...process.env, RENOVATE_CANDIDATE_ROOT: root },
    encoding: 'utf8',
    timeout: 120000,
    maxBuffer: 4 * 1024 * 1024,
  });
  process.stdout.write(result.stdout ?? '');
  process.stderr.write(result.stderr ?? '');
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, 'Relocated entrypoint must retain helper access through the candidate mount');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
