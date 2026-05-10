// Deploy Smartest bot to VPS
// Usage: node deploy/deploy.cjs
const { Client } = require('ssh2');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Always deploy from Smartest project, regardless of where this script runs
// Deploy from the directory containing this script's parent. Use --source to override.
const argSource = (process.argv.find(a => a.startsWith('--source=')) || '').split('=')[1];
const PROJECT_DIR = argSource || path.resolve(__dirname, '..');
const REMOTE_APP = '/opt/smartest/app';
const REMOTE_VENV = '/opt/smartest/venv';
const IS_WIN = process.platform === 'win32';
const EXEC_SHELL = IS_WIN ? undefined : 'bash';

const excludes = [
  '.git',
  '__pycache__',
  '*.pyc',
  '*.pyo',
  '.env',
  'venv',
  '.venv',
  'log.txt',
  'logs',
  'sessions',
  'tmp',
  'Audio',
  'deploy/node_modules',
  'deploy/*.tar.gz',
].map(e => `--exclude="${e}"`).join(' ');

const tarFile = path.join(PROJECT_DIR, 'deploy', 'smartest.tar.gz');

// ── Acceptance gate ──────────────────────────────────────────────
// See docs/project/testing-protocol.md and docs/project/behavior-audit.md.
// Skip with SKIP_ACCEPTANCE=1 only when you know what you're doing.
if (!process.env.SKIP_ACCEPTANCE) {
  console.log('[deploy] Running acceptance tests (gate)...');
  try {
    execSync('python -m pytest --noconftest tests/acceptance/ -x --tb=short -q', {
      stdio: 'inherit', cwd: PROJECT_DIR, shell: EXEC_SHELL,
    });
  } catch (e) {
    console.error('[deploy] Acceptance gate FAILED. Deploy blocked.');
    console.error('[deploy] Fix the failing invariants or set SKIP_ACCEPTANCE=1 to bypass.');
    process.exit(1);
  }
}

console.log('[deploy] Creating archive...');
try {
  if (IS_WIN) {
    // Use a relative output path on Windows. Absolute C:\ paths make bsdtar
    // interpret "C:" as a remote host, and Git Bash is not guaranteed here.
    execSync(`tar czf "deploy/smartest.tar.gz" ${excludes} .`, {
      stdio: 'inherit', shell: EXEC_SHELL, cwd: PROJECT_DIR,
    });
  } else {
    const tarPosix = tarFile.replace(/\\/g, '/');
    const projPosix = PROJECT_DIR.replace(/\\/g, '/');
    execSync(`tar czf "${tarPosix}" ${excludes} -C "${projPosix}" .`, {
      stdio: 'inherit', shell: 'bash', cwd: PROJECT_DIR,
    });
  }
} catch (e) {
  console.error('[deploy] tar failed:', e.message);
  process.exit(1);
}

const tarData = fs.readFileSync(tarFile);
console.log(`[deploy] Archive: ${(tarData.length / 1024 / 1024).toFixed(1)}MB`);

const conn = new Client();
conn.on('ready', () => {
  console.log('[deploy] Connected, uploading...');
  conn.sftp((err, sftp) => {
    if (err) { console.error(err); conn.end(); return; }

    const remoteTar = '/tmp/smartest.tar.gz';
    const ws = sftp.createWriteStream(remoteTar);
    ws.on('close', () => {
      console.log('[deploy] Uploaded, deploying...');
      const cmd = [
        // Preserve .env
        `cp ${REMOTE_APP}/.env /tmp/smartest-env.bak 2>/dev/null || true`,
        // Extract new code
        `tar xzf ${remoteTar} -C ${REMOTE_APP}`,
        `rm -f ${remoteTar}`,
        // Restore .env
        `cp /tmp/smartest-env.bak ${REMOTE_APP}/.env 2>/dev/null || true`,
        // Install/update dependencies
        `${REMOTE_VENV}/bin/pip install -q -r ${REMOTE_APP}/requirements.txt`,
        // Restart services
        `systemctl restart smartest-bot`,
        `systemctl restart smartest-admin`,
        `sleep 2`,
        `systemctl is-active smartest-bot && echo '[deploy] smartest-bot: OK' || echo '[deploy] smartest-bot: FAILED'`,
        `systemctl is-active smartest-admin && echo '[deploy] smartest-admin: OK' || echo '[deploy] smartest-admin: FAILED'`,
      ].join(' && ');

      conn.exec(cmd, (err2, stream) => {
        if (err2) { console.error(err2); conn.end(); return; }
        stream.on('close', (code) => {
          conn.end();
          process.exitCode = code;
        });
        stream.on('data', d => process.stdout.write(d.toString()));
        stream.stderr.on('data', d => process.stderr.write(d.toString()));
      });
    });
    ws.on('error', e => { console.error('[deploy] SFTP error:', e); conn.end(); });
    ws.end(tarData);
  });
}).on('error', e => { console.error('SSH ERROR:', e.message); process.exit(1); })
  .connect({ host: '87.106.11.84', port: 22, username: 'root', password: '8Vib2YTN', readyTimeout: 30000 });
