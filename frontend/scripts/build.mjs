import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const web = path.join(root, 'web');
const dist = path.join(root, 'dist');
const mime = ext => ({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.ico':'image/x-icon'})[ext] || 'application/octet-stream';
const assets = {};
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes:true })) {
    const filename = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(filename);
    else if (entry.isFile()) {
      const key = path.relative(web, filename).split(path.sep).join('/');
      const data = fs.readFileSync(filename);
      const type = mime(path.extname(filename).toLowerCase());
      assets[key] = /^(text\/|application\/json|image\/svg)/.test(type) ? { text:data.toString('utf8'), type } : { base64:data.toString('base64'), type };
    }
  }
}
walk(web);
assets['data/state-platform-filter-2026-10-26.json'] = { text:fs.readFileSync(path.join(root,'data/state-platform-filter-2026-10-26.json'),'utf8'), type:'application/json' };
const source = fs.readFileSync(path.join(root, 'worker/index.js'), 'utf8');
if (!source.includes('__ASSETS__')) throw new Error('Missing asset placeholder');
fs.rmSync(dist,{recursive:true,force:true});
fs.mkdirSync(path.join(dist,'server'),{recursive:true});
fs.mkdirSync(path.join(dist,'.openai'),{recursive:true});
const assetLiteral = '{\n'+Object.entries(assets).map(([name, asset]) => JSON.stringify(name)+':'+JSON.stringify(asset)).join(',\n')+'\n}';
fs.writeFileSync(path.join(dist,'server/index.js'), source.replace('const assets = __ASSETS__;', () => 'const assets = '+assetLiteral+';'));
fs.copyFileSync(path.join(root,'.openai/hosting.json'),path.join(dist,'.openai/hosting.json'));
console.log(`Built SharpEdge Worker with ${Object.keys(assets).length-1} assets`);
