const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { resolvePaths } = require('../desktop/paths.cjs');
const { resolveDataOverride } = require('../desktop/paths.cjs');

test('development data stays alongside the project', () => {
  const result = resolvePaths({ packaged:false, projectDirectory:'F:\\video-knowledge-desktop' });
  assert.equal(result.dataDirectory, 'F:\\video-knowledge-desktop\\data');
  assert.equal(result.stateDirectory, path.join(result.dataDirectory, 'app-state'));
});
test('unpacked executable keeps data in the project root', () => {
  const result = resolvePaths({ packaged:true, executablePath:'F:\\video-knowledge-desktop\\release\\win-unpacked\\Zhixu.exe' });
  assert.equal(result.dataDirectory, 'F:\\video-knowledge-desktop\\data');
});
test('portable self extraction uses the original exe directory', () => {
  const result = resolvePaths({ packaged:true, executablePath:'C:\\temp\\random\\Zhixu.exe', portableDirectory:'F:\\video-knowledge-desktop\\release' });
  assert.equal(result.dataDirectory, 'F:\\video-knowledge-desktop\\data');
});
test('explicit isolated test directories override defaults', () => {
  const result = resolvePaths({ packaged:false, projectDirectory:'F:\\video-knowledge-desktop', overrideDirectory:'F:\\video-knowledge-desktop\\.test-data\\isolated' });
  assert.equal(result.dataDirectory, 'F:\\video-knowledge-desktop\\.test-data\\isolated');
});

test('command-line data profiles override environment without changing default profile', () => {
  assert.equal(typeof resolveDataOverride, 'function');
  assert.equal(resolveDataOverride(['app','--data-dir=D:/audit'], 'D:/normal'), 'D:/audit');
  assert.equal(resolveDataOverride(['app','--data-dir','D:/audit'], ''), 'D:/audit');
  assert.equal(resolveDataOverride(['app'], 'D:/normal'), 'D:/normal');
  assert.equal(resolveDataOverride(['app'], ''), undefined);
  assert.throws(() => resolveDataOverride(['app','--data-dir'], ''), /data-dir/);
});
