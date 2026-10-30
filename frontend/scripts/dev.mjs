import http from 'node:http';
import { Readable } from 'node:stream';
import { execFileSync } from 'node:child_process';
execFileSync(process.execPath,['scripts/build.mjs'],{stdio:'inherit'});
const { default:worker } = await import('../dist/server/index.js');
const port = Number(process.env.PORT || 4173);
http.createServer(async (req,res) => {
  const input = new Request(`http://localhost:${port}${req.url}`, { method:req.method });
  const output = await worker.fetch(input, process.env);
  res.writeHead(output.status,Object.fromEntries(output.headers));
  if (output.body) Readable.fromWeb(output.body).pipe(res); else res.end();
}).listen(port,'0.0.0.0',()=>console.log(`SharpEdge preview on port ${port}`));
