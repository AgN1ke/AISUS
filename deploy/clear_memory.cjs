// Clear bot memory from VPS database
// Requires env vars: DEPLOY_HOST, DEPLOY_USER, DEPLOY_PASS (or set in deploy/.env)
const { Client } = require('ssh2');
const path = require('path');
const fs = require('fs');

// Load deploy/.env if exists
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
  console.error('[clear] Missing DEPLOY_HOST or DEPLOY_PASS. Set env vars or create deploy/.env');
  process.exit(1);
}

const tmpScript = path.join(__dirname, '.clear_memory_tmp.py');

// Create temporary Python script
const scriptContent = `
import asyncio, os, aiomysql
from dotenv import load_dotenv

load_dotenv()

async def clear():
    db_config = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "aisus"),
        "password": os.getenv("DB_PASS", ""),
        "db": os.getenv("DB_NAME", "aisus"),
    }
    conn = await aiomysql.connect(**db_config)
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM memory_recent")
        recent = cur.rowcount
        await cur.execute("DELETE FROM memory_long")
        long = cur.rowcount
        await conn.commit()
        print(f"[clear] memory_recent: {recent} rows deleted")
        print(f"[clear] memory_long: {long} rows deleted")
    conn.close()

asyncio.run(clear())
`;

fs.writeFileSync(tmpScript, scriptContent);

const conn = new Client();

conn.on('ready', () => {
  console.log('[clear] Connected, clearing memory...');

  // Upload script to server
  conn.sftp((err, sftp) => {
    if (err) { console.error(err); conn.end(); return; }

    const remotePath = '/tmp/.clear_memory.py';
    const ws = sftp.createWriteStream(remotePath);

    ws.on('close', () => {
      // Execute the script
      const cmd = 'cd /opt/smartest/app && source /opt/smartest/venv/bin/activate && python3 /tmp/.clear_memory.py && rm -f /tmp/.clear_memory.py';

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

    ws.on('error', e => { console.error('[clear] SFTP error:', e); conn.end(); });
    ws.end(scriptContent);
  });
}).on('error', e => { console.error('SSH ERROR:', e.message); process.exit(1); })
  .connect({ host: DEPLOY_HOST, port: 22, username: DEPLOY_USER, password: DEPLOY_PASS, readyTimeout: 30000 });

