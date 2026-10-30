// Bundle entrypoint: private credential files, then the unchanged product command.
import {open, constants} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {constants as osConstants} from 'node:os';

const roles = {
  server: ['APP_API_KEY', 'OLLAMA_API_KEY'],
  scanner: ['SCANNER_API_KEY', 'ADAPT_TOKEN', 'REMEDY_API_KEY'],
  bridge: ['SERVER_KEY', 'SERVER_SECRET', 'SERVER_USER'],
};
const [role, ...command] = process.argv.slice(2);
async function privateFile(name) {
  const path = process.env[name];
  if (!path) throw new Error(name);
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) || info.size > 16384) throw new Error(name);
    const value = (await file.readFile('utf8')).replace(/\n$/, '');
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw new Error(name);
    return value;
  } finally { await file.close(); }
}
try {
  if (!Object.hasOwn(roles, role) || !command.length) throw new Error('role_or_command');
  const env = {...process.env};
  for (const name of roles[role]) {
    if (env[name]) throw new Error(`${name}_ambiguous`);
    env[name] = await privateFile(`${name}_FILE`);
  }
  if (env.REMEDY_BRIDGE_SERVICE_KEY_FILE) {
    const service = await privateFile('REMEDY_BRIDGE_SERVICE_KEY_FILE');
    if (!/^[a-f0-9]{64}$/.test(service)) throw new Error('service_key_format');
  }
  if (command.length === 1 && command[0] === '--check') {
    console.log(JSON.stringify({ok: true, role, uid: process.getuid(), credentialNames: roles[role]}));
  } else {
    const child = spawn(command[0], command.slice(1), {env, stdio: 'inherit'});
    let ended = false;
    const signals = ['SIGTERM', 'SIGINT'];
    const handlers = signals.map(signal => () => { if (!ended) child.kill(signal); });
    signals.forEach((signal, index) => process.on(signal, handlers[index]));
    child.once('error', () => { console.error('product_start_failed'); process.exitCode = 1; });
    child.once('exit', (code, signal) => {
      ended = true;
      signals.forEach((name, index) => process.removeListener(name, handlers[index]));
      process.exitCode = code ?? 128 + (osConstants.signals[signal] ?? 1);
    });
  }
} catch {
  // Never print credential contents, provider responses or stack traces.
  console.error('credential_configuration_invalid');
  process.exitCode = 1;
}
