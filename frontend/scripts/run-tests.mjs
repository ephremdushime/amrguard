import { readdirSync, rmSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { build } from 'esbuild';

const root = resolve(process.cwd());
const testsDir = join(root, 'tests');
const outDir = join(root, '.test-dist');

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const testFiles = readdirSync(testsDir)
  .filter((f) => f.endsWith('.test.ts') || f.endsWith('.test.tsx'))
  .sort()
  .map((f) => join(testsDir, f));

if (testFiles.length === 0) {
  console.error('No frontend test files found in', testsDir);
  process.exit(1);
}

await build({
  entryPoints: testFiles,
  outdir: outDir,
  bundle: true,
  platform: 'node',
  format: 'esm',
  jsx: 'automatic',
  target: 'node22',
  packages: 'external',
  outExtension: { '.js': '.mjs' },
  logLevel: 'silent',
});

const builtFiles = readdirSync(outDir)
  .filter((f) => f.endsWith('.mjs'))
  .sort()
  .map((f) => join(outDir, f));

const result = spawnSync(process.execPath, ['--test', ...builtFiles], {
  stdio: 'inherit',
  cwd: root,
});

rmSync(outDir, { recursive: true, force: true });
process.exit(result.status ?? 1);
