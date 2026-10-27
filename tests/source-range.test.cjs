const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// The folding rules live in TypeScript next to the renderer; transpile the real
// module so the checks run against the shipped source rather than a copy.
function load() {
  const file = path.join(__dirname, '..', 'src', 'source-range.ts');
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('exports', 'require', 'module', output)(module.exports, require, module);
  return module.exports;
}

const { compactSourceLine, compactSourceLines, formatClock, mergeRanges, rangeLabel, segmentSpans } = load();

const sid = (index) => `dcd43a14-ba50-4372-8324-d0f195b1${String(index).padStart(4, '0')}`;
const other = '3c1b8680-72b6-474e-a9e7-ad0f51c04c1c';
const sources = (starts) => starts.map((start, index) => ({ id: sid(index), start }));
const cite = (rows) => rows.map(([id, time]) => `[来源:${id}]${time === null ? '' : `（${formatClock(time)}）`}`).join(' ');

test('video clock keeps mm:ss below an hour and h:mm:ss above it', () => {
  assert.equal(formatClock(0), '00:00');
  assert.equal(formatClock(186), '03:06');
  assert.equal(formatClock(3723), '1:02:03');
});

test('a fragment ends where the next fragment starts', () => {
  const spans = segmentSpans(sources([0, 2.04, 4.88, 6.16]));
  assert.deepEqual(spans.get(sid(0)), { start: 0, end: 2.04 });
  assert.deepEqual(spans.get(sid(3)), { start: 6.16, end: 9.16 });
});

test('touching fragments merge into one interval', () => {
  const rows = cite([[sid(0), 186], [sid(1), 188], [sid(2), 190], [sid(3), 192]]);
  const spans = segmentSpans(sources([186, 188, 190, 192, 194]));
  assert.equal(compactSourceLine(rows, spans), '[视频来源:03:06–03:14]');
});

test('clearly separate stretches keep several intervals in clock order', () => {
  const spans = segmentSpans(sources([186, 188, 190, 400, 402]));
  const rows = cite([[sid(3), 400], [sid(0), 186], [sid(4), 402]]);
  assert.equal(compactSourceLine(rows, spans), '[视频来源:03:06–03:08、06:40–06:45]');
});

test('a short uncited gap still reads as one stretch of video', () => {
  const spans = segmentSpans(sources([186, 188, 190, 192, 194, 196]));
  const rows = cite([[sid(0), 186], [sid(2), 190], [sid(5), 196]]);
  assert.equal(compactSourceLine(rows, spans), '[视频来源:03:06–03:19]');
});

test('mergeRanges keeps intervals apart beyond the merge gap', () => {
  const merged = mergeRanges([{ start: 100, end: 110 }, { start: 110, end: 120 }, { start: 200, end: 210 }]);
  assert.deepEqual(merged, [{ start: 100, end: 120 }, { start: 200, end: 210 }]);
  assert.equal(rangeLabel(merged), '01:40–02:00、03:20–03:30');
});

test('fragments without a real video time keep their original chips', () => {
  const line = cite([[other, 186], [sid(0), null]]);
  assert.equal(compactSourceLine(line, segmentSpans(sources([186, 188]))), null);
});

test('prose, indented code and fenced code keep their citation markers', () => {
  const line = cite([[sid(0), 186], [sid(1), 188]]);
  const spans = segmentSpans(sources([186, 188, 190]));
  assert.equal(compactSourceLine(`讲解如下 ${line}`, spans), null);
  assert.equal(compactSourceLine(`    ${line}`, spans), null);
  const markdown = ['```', line, '```', '', line].join('\n');
  const folded = compactSourceLines(markdown, sources([186, 188, 190])).split('\n');
  assert.equal(folded[1], line);
  assert.equal(folded[4], '[视频来源:03:06–03:10]');
});

test('compaction leaves the rest of the tutorial untouched', () => {
  const line = cite([[sid(0), 186], [sid(1), 188]]);
  const markdown = ['## 中国央行的预期管理实践', '', '讲解指出，咱们的央行现在也经常做类似的预期管理。', '', line, '', '## 核心结论'].join('\n');
  const folded = compactSourceLines(markdown, sources([186, 188, 190]));
  assert.equal(folded, ['## 中国央行的预期管理实践', '', '讲解指出，咱们的央行现在也经常做类似的预期管理。', '', '[视频来源:03:06–03:10]', '', '## 核心结论'].join('\n'));
});

test('a document without markers is returned unchanged', () => {
  const markdown = '# 笔记\n\n没有任何来源标记。';
  assert.equal(compactSourceLines(markdown, sources([0])), markdown);
});
