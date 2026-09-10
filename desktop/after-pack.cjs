// Strip Finder metadata from newly built macOS files before code signing.
// Never remove quarantine or change system security settings.
const { execFileSync } = require('node:child_process');
module.exports = async context => {
  if (context.electronPlatformName !== 'darwin') return;
  for (const attribute of ['com.apple.FinderInfo', 'com.apple.ResourceFork']) {
    try {
      execFileSync('/usr/bin/xattr', ['-r', '-d', attribute, context.appOutDir], { stdio: 'pipe' });
    } catch (error) {
      // xattr reports status 1 when an attribute was already absent.
      if (error.status !== 1) throw error;
    }
  }
};
