import http from 'node:http';
import { Readable } from 'node:stream';
import { execFileSync } from 'node:child_process';
execFileSync(process.execPath,['scripts/build.mjs'],{stdio:'inherit'});
const { default:worker } = await import('../dist/server/index.js');
const port = Number(process.env.PORT || 4173);
const authDiagnostics = [];
http.createServer(async (req,res) => {
  // Local diagnostics contain status/error codes only, never tokens or profiles.
  // This endpoint exists only in the development server, not the hosted Worker.
  if (req.url === '/api/auth/diagnostics' && req.method === 'GET') {
    const address = req.socket.remoteAddress || '';
    if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address)) {
      res.writeHead(403); res.end(); return;
    }
    res.writeHead(200, {'content-type':'application/json', 'cache-control':'no-store'});
    res.end(JSON.stringify({errors:authDiagnostics}));
    return;
  }
  const input = new Request(`http://${req.headers.host || `localhost:${port}`}${req.url}`, { method:req.method, headers:req.headers,
    ...(!['GET', 'HEAD'].includes(req.method) ? {body:Readable.toWeb(req), duplex:'half'} : {}) });
  const output = await worker.fetch(input, process.env);
  if (req.url === '/api/session' && output.status >= 400) {
    const body = await output.clone().json().catch(() => ({}));
    const diagnostic = {at:new Date().toISOString(), status:output.status, code:body.code || 'AUTH_UNAVAILABLE'};
    authDiagnostics.push(diagnostic);
    if (authDiagnostics.length > 20) authDiagnostics.shift();
    console.warn('SharpEdge session:', JSON.stringify(diagnostic));
  }
  res.writeHead(output.status,Object.fromEntries(output.headers));
  if (output.body) Readable.fromWeb(output.body).pipe(res); else res.end();
}).listen(port,'0.0.0.0',()=>console.log(`SharpEdge preview on port ${port}`));
