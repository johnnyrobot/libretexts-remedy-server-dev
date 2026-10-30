// TRANSPORT fault fixture only. Every product byte comes from the actual Server.
// No signer, authentication shortcut, retry, redirect or operation/proof factory.
import https from 'node:https';
import fs from 'node:fs';
import {createHash, timingSafeEqual} from 'node:crypto';
import {pathToFileURL} from 'node:url';

export function createResponseGate({key, cert, ca, target, controlToken, requestBytes = 5000000,
  responseBytes = 32000000, deadlineMS = 620000}) {
  const destination = new URL(target);
  if (destination.protocol !== 'https:' || destination.username || destination.password
    || destination.pathname !== '/' || destination.search || destination.hash) throw Error('private_https_target_required');
  const state = {forwarded: 0, completed: 0, dropped: 0, errors: 0, armed: false,
    lastStatus: null, lastResponseSHA256: null};
  const authenticated = supplied => typeof supplied === 'string'
    && Buffer.byteLength(supplied) === Buffer.byteLength(controlToken)
    && timingSafeEqual(Buffer.from(supplied), Buffer.from(controlToken));
  const server = https.createServer({key, cert, minVersion: 'TLSv1.2'}, async (req, res) => {
    let upstream, timer;
    const fail = () => { state.errors++; upstream?.destroy(); res.destroy(); };
    try {
      if (req.url.startsWith('/control/')) {
        if (!authenticated(req.headers['x-fixture-control'])) { res.writeHead(401); res.end(); return; }
        let size = 0;
        for await (const chunk of req) { size += chunk.length; if (size > 1000) { res.writeHead(413); res.end(); return; } }
        if (req.method === 'POST' && req.url === '/control/drop-next-apply-reply') state.armed = true;
        else if (!(req.method === 'GET' && req.url === '/control/status')) { res.writeHead(404); res.end(); return; }
        const bytes = Buffer.from(JSON.stringify(state));
        res.writeHead(200, {'Content-Type': 'application/json', 'Content-Length': bytes.length}); res.end(bytes); return;
      }
      const chunks = []; let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > requestBytes) { res.writeHead(413); res.end(); return; }
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks);
      // Preserve all received headers (including Host and credentials) verbatim.
      // TLS hostname verification still uses the actual upstream destination.
      upstream = https.request({hostname: destination.hostname, port: destination.port || 443,
        servername: destination.hostname, ca, rejectUnauthorized: true, method: req.method,
        path: req.url, headers: req.rawHeaders, agent: false}, async reply => {
        try {
          const buffers = []; let bytes = 0;
          for await (const chunk of reply) {
            bytes += chunk.length;
            if (bytes > responseBytes) { fail(); return; }
            buffers.push(chunk);
          }
          if (!reply.complete) { fail(); return; }
          const raw = Buffer.concat(buffers);
          state.completed++; state.lastStatus = reply.statusCode;
          state.lastResponseSHA256 = createHash('sha256').update(raw).digest('hex');
          let known = false;
          if (state.armed && req.method === 'POST' && req.url === '/v1/cxone/page/apply-fix'
            && reply.statusCode === 200) {
            try { known = JSON.parse(raw.toString('utf8')).outcome === 'known_success'; } catch {}
          }
          if (known) {
            state.armed = false; state.dropped++;
            // The REAL upstream finished before the downstream socket is lost.
            // No response is substituted and the request is never resent.
            res.destroy(); return;
          }
          res.writeHead(reply.statusCode, reply.statusMessage, reply.rawHeaders);
          res.end(raw);
        } catch { fail(); }
        finally { clearTimeout(timer); }
      });
      state.forwarded++;
      timer = setTimeout(fail, deadlineMS); timer.unref();
      upstream.once('error', () => { clearTimeout(timer); fail(); });
      req.once('aborted', () => { clearTimeout(timer); upstream.destroy(); });
      upstream.end(body);
    } catch { clearTimeout(timer); fail(); }
  });
  server.requestTimeout = deadlineMS;
  server.headersTimeout = 10000;
  server.keepAliveTimeout = 1000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.env.GITHUB_ACTIONS !== 'true' || process.platform !== 'linux') {
    console.error('isolated_linux_ci_required'); process.exitCode = 1;
  } else {
    const server = createResponseGate({key: fs.readFileSync('/fixtures/key.pem'), cert: fs.readFileSync('/fixtures/cert.pem'),
      ca: fs.readFileSync('/fixtures/ca.pem'), target: 'https://remedy-server:8000', controlToken: 'synthetic-control-only'});
    server.listen(8444, '0.0.0.0');
    for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {
      server.close(); server.closeIdleConnections();
      setTimeout(() => server.closeAllConnections(), 1000).unref();
    });
  }
}
