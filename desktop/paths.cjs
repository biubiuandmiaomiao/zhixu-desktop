const path = require('node:path');

function resolvePaths({ packaged, projectDirectory, executablePath, portableDirectory, overrideDirectory }) {
  let root = projectDirectory;
  if (packaged) {
    root = portableDirectory || path.dirname(executablePath);
    const folder = path.basename(root).toLowerCase();
    if (folder === 'win-unpacked' && path.basename(path.dirname(root)).toLowerCase() === 'release') {
      root = path.resolve(root, '..', '..');
    } else if (folder === 'release') {
      root = path.resolve(root, '..');
    }
  }
  const dataDirectory = overrideDirectory ? path.resolve(overrideDirectory) : path.join(root, 'data');
  return { dataDirectory, stateDirectory: path.join(dataDirectory, 'app-state') };
}

function resolveDataOverride(argv, environmentValue) {
  const index = argv.findIndex(value => value === '--data-dir' || value.startsWith('--data-dir='));
  if (index < 0) return environmentValue || undefined;
  const value = argv[index].startsWith('--data-dir=') ? argv[index].slice(11) : argv[index + 1];
  if (!value || value.startsWith('--') || value.includes('\0') || value.length > 4096) throw new Error('--data-dir 需要有效目录');
  return value;
}

module.exports = { resolvePaths, resolveDataOverride };
