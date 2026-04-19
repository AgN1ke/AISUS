// Quick remote diagnostics via ssh2. Runs a few status commands on the VPS.
const { Client } = require('ssh2');
const fs = require('fs');
const path = require('path');

const dotenvPath = path.join(__dirname, '.env');
for (const line of fs.readFileSync(dotenvPath, 'utf8').split('\n')) {
  const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.+?)\s*$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}

const cmd = process.argv.slice(2).join(' ') || 'pm2 list && echo "---" && ls /opt/smartest/app | head -5';

const conn = new Client();
conn.on('ready', () => {
  conn.exec(cmd, (err, stream) => {
    if (err) { console.error(err); conn.end(); return; }
    stream.on('close', (code) => { conn.end(); process.exit(code || 0); })
          .on('data', (d) => process.stdout.write(d))
          .stderr.on('data', (d) => process.stderr.write(d));
  });
}).on('error', (e) => { console.error('SSH error:', e.message); process.exit(1); })
  .connect({
    host: process.env.DEPLOY_HOST,
    username: process.env.DEPLOY_USER || 'root',
    password: process.env.DEPLOY_PASS,
    readyTimeout: 20000,
  });
