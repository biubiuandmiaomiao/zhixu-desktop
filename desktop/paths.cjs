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

module.exports = { resolvePaths };
