// Deploy Smartest to VPS
// Usage: node deploy/deploy.cjs --target=prod
//        node deploy/deploy.cjs --target=staging
// --target must be explicit (no default) to avoid confusing prod and staging.
// Requires env vars: DEPLOY_HOST, DEPLOY_USER, DEPLOY_PASS (or set in deploy/.env)
const { Client } = require('ssh2');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const TARGETS = {
  prod: {
    remoteApp: '/opt/smartest/app',
    remoteAppPrev: '/opt/smartest/app.prev',
    remoteVenv: '/opt/smartest/venv',
    envPath: '/opt/smartest/.env',
    botService: 'smartest-bot',
    adminService: 'smartest-admin',
  },
  staging: {
    remoteApp: '/opt/smartest-staging',
    remoteAppPrev: '/opt/smartest-staging/app.prev',
    remoteVenv: '/opt/smartest-staging/.venv',
    envPath: '/opt/smartest-staging/.env',
    botService: 'smartest-staging-bot',
    adminService: 'smartest-staging-admin',
  },
};

const argTarget = (process.argv.find(a => a.startsWith('--target=')) || '').split('=')[1];
if (!argTarget || !TARGETS[argTarget]) {
  console.error('[deploy] --target=prod or --target=staging is required.');
  console.error('         prod    -> /opt/smartest/app (smartest.klawa.top, @saintaibot)');
  console.error('         staging -> /opt/smartest-staging (test.klawa.top, test bot)');
  process.exit(1);
}
const cfg = TARGETS[argTarget];

const dotenvPath = path.join(__dirname, '.env');
if (fs.existsSync(dotenvPath)) {
  for (const line of fs.readFileSync(dotenvPath, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.+?)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}

const DEPLOY_HOST = process.env.DEPLOY_HOST;
const DEPLOY_USER = process.env.DEPLOY_USER || 'root';
const DEPLOY_PASS = process.env.DEPLOY_PASS;
if (!DEPLOY_HOST || !DEPLOY_PASS) {
  console.error('[deploy] Missing DEPLOY_HOST or DEPLOY_PASS. Set env vars or create deploy/.env');
  process.exit(1);
}

const PROJECT_DIR = 'C:/Python_projects/Smartest';

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
  '.tmp',
  'Audio',
  'deploy/*.tar.gz',
  'deploy/node_modules',
  'mariadb-*.zip',
].map(e => `--exclude="${e}"`).join(' ');

const tarFile = path.join(PROJECT_DIR, 'deploy', `smartest-${argTarget}.tar.gz`);

console.log(`[deploy] target=${argTarget} -> ${cfg.remoteApp}`);
console.log('[deploy] Creating archive...');
try {
  const tarPosix = tarFile.replace(/\\/g, '/').replace(/^([A-Z]):/i, '/$1');
  const projPosix = PROJECT_DIR.replace(/\\/g, '/').replace(/^([A-Z]):/i, '/$1');
  execSync(`tar czf "${tarPosix}" ${excludes} -C "${projPosix}" .`, {
    stdio: 'inherit', shell: 'bash', cwd: PROJECT_DIR,
  });
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

    const remoteTar = `/tmp/smartest-${argTarget}.tar.gz`;
    const ws = sftp.createWriteStream(remoteTar);
    ws.on('close', () => {
      console.log('[deploy] Uploaded, deploying...');
      const cmd = [
        `cp ${cfg.envPath} /tmp/smartest-${argTarget}-env.bak 2>/dev/null || true`,
        `rm -rf ${cfg.remoteAppPrev}`,
        `mkdir -p ${cfg.remoteAppPrev}`,
        `cp -a ${cfg.remoteApp}/. ${cfg.remoteAppPrev}/ 2>/dev/null || true`,
        `mkdir -p ${cfg.remoteApp}`,
        `tar xzf ${remoteTar} -C ${cfg.remoteApp}`,
        `rm -f ${remoteTar}`,
        `cp /tmp/smartest-${argTarget}-env.bak ${cfg.envPath} 2>/dev/null || true`,
        `${cfg.remoteVenv}/bin/pip install -q -r ${cfg.remoteApp}/requirements.txt`,
        `systemctl restart ${cfg.botService}`,
        `systemctl restart ${cfg.adminService}`,
        `sleep 2`,
        `systemctl is-active ${cfg.botService} && echo '[deploy] ${cfg.botService}: OK' || echo '[deploy] ${cfg.botService}: FAILED'`,
        `systemctl is-active ${cfg.adminService} && echo '[deploy] ${cfg.adminService}: OK' || echo '[deploy] ${cfg.adminService}: FAILED'`,
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
  .connect({ host: DEPLOY_HOST, port: 22, username: DEPLOY_USER, password: DEPLOY_PASS, readyTimeout: 30000 });
