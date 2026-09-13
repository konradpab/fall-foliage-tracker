#!/usr/bin/env node
/**
 * Payload budget check. Run after `npm run build`.
 *
 * The budgets are split deliberately. Our own code has a tight budget we can
 * actually hold. MapLibre has its own, much larger, because a WebGL vector-tile
 * renderer simply is that big -- see DECISIONS.md, "Bundle budget". Splitting
 * the two keeps the number we control honest instead of hiding it in a total.
 */

import { gzipSync } from 'node:zlib';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const BUDGETS = {
  'app JS (entry + lazy app chunks)': 150 * 1024,
  'app CSS': 20 * 1024,
  'MapLibre JS (deferred, cached across deploys)': 260 * 1024,
  'MapLibre CSS': 16 * 1024,
  'forecast.json': 600 * 1024,
};

const gz = (p) => gzipSync(readFileSync(p)).length;
const kb = (n) => `${(n / 1024).toFixed(1)} kB`;

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

let files;
try {
  files = walk('dist');
} catch {
  console.error('No dist/ - run `npm run build` first.');
  process.exit(1);
}

const isMapLibre = (p) => /maplibre/i.test(p);
const sum = (pred) => files.filter(pred).reduce((n, p) => n + gz(p), 0);

const measured = {
  'app JS (entry + lazy app chunks)': sum((p) => p.endsWith('.js') && !isMapLibre(p)),
  'app CSS': sum((p) => p.endsWith('.css') && !isMapLibre(p)),
  'MapLibre JS (deferred, cached across deploys)': sum((p) => p.endsWith('.js') && isMapLibre(p)),
  'MapLibre CSS': sum((p) => p.endsWith('.css') && isMapLibre(p)),
  'forecast.json': (() => {
    try {
      return gz('public/data/forecast.json');
    } catch {
      return 0;
    }
  })(),
};

let failed = false;
console.log('gzipped payload budgets\n');
for (const [name, budget] of Object.entries(BUDGETS)) {
  const actual = measured[name];
  const ok = actual <= budget;
  if (!ok) failed = true;
  const pct = ((actual / budget) * 100).toFixed(0);
  console.log(
    `  ${ok ? 'PASS' : 'FAIL'}  ${name.padEnd(46)} ${kb(actual).padStart(9)} / ${kb(budget).padStart(9)}  (${pct}%)`,
  );
}

const total = measured['app JS (entry + lazy app chunks)'] + measured['app CSS'] +
  measured['MapLibre JS (deferred, cached across deploys)'] + measured['MapLibre CSS'];
console.log(`\n  total transferred on a cold first load: ${kb(total)} gzipped`);
console.log('  (MapLibre is a separate deferred chunk: the shell and the forecast');
console.log('   panel are interactive before it arrives, and it stays cached.)');

process.exit(failed ? 1 : 0);
