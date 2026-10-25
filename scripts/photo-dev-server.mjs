// 仅监听本机。模拟资料读取，不连接 AWS；原 JPG 直接从本人指定目录流式读取。
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHandler } from '../backend/photo-api/core.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.webp': 'image/webp', '.svg': 'image/svg+xml' };

export function createPhotoServer({ catalog, sourceDirectory, scenario = 'normal' }) {
  const sorted = [...catalog].sort((a, b) => a.SK.localeCompare(b.SK));
  const handler = createHandler({ logError: () => {}, async queryPage({ partition, after, limit }) {
    const eligible = sorted.filter(item => item.PK === partition && (!after || item.SK > after.SK));
    const items = eligible.slice(0, limit);
    const last = items.at(-1);
    return { items, lastKey: eligible.length > limit ? { PK: last.PK, SK: last.SK } : null };
  } });
  const send = (req, res, status, body) => {
    res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
    res.end(req.method === 'HEAD' ? '' : body);
  };
  return http.createServer(async (req, res) => {
    // 防止把仅供本机的原图预览接口当成局域网/跨站服务。
    if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(req.headers.host || '') ||
        (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) || req.headers['sec-fetch-site'] === 'cross-site') {
      return send(req, res, 403, 'Local preview only');
    }
    let url, pathname;
    try { url = new URL(req.url, `http://${req.headers.host}`); pathname = decodeURIComponent(url.pathname); }
    catch { return send(req, res, 400, 'Invalid path'); }
    res.setHeader('x-content-type-options', 'nosniff');
    if (pathname.startsWith('/api/')) {
      if (scenario === 'expired') return send(req, res, 403, 'Access denied (local scenario)');
      if (scenario === 'unavailable') return send(req, res, 503, 'Unavailable (local scenario)');
      const result = await handler({ rawPath: pathname, rawQueryString: url.search.slice(1), requestContext: { http: { method: req.method } } });
      if (result.statusCode === 200 && result.body) {
        const data = JSON.parse(result.body); data.mode = 'local';
        if (scenario === 'empty') { data.photos = []; data.nextCursor = null; }
        result.body = JSON.stringify(data);
      }
      res.writeHead(result.statusCode, result.headers); return res.end(result.body);
    }
    if (!['GET', 'HEAD'].includes(req.method)) return send(req, res, 405, 'Method not allowed');
    let filename, original;
    if (pathname.startsWith('/photo-originals/')) {
      original = sorted.find(item => '/' + item.originalKey === pathname);
      if (!original || path.basename(original.filename) !== original.filename) return send(req, res, 404, 'Photo not found');
      filename = path.join(sourceDirectory, original.filename);
    } else {
      const relative = pathname === '/' ? 'photos/index.html' : pathname.replace(/^\/+/, '') + (pathname.endsWith('/') ? 'index.html' : '');
      const dist = path.join(root, 'dist');
      filename = path.resolve(dist, relative);
      if (!filename.startsWith(dist + path.sep)) return send(req, res, 404, 'Not found');
    }
    let stat;
    try { stat = fs.statSync(filename); if (!stat.isFile()) throw new Error(); }
    catch { return send(req, res, 404, 'File not found'); }
    let start = 0, end = stat.size - 1, code = 200;
    const headers = { 'content-type': original ? 'image/jpeg' : types[path.extname(filename)] || 'application/octet-stream',
      'cache-control': 'private, no-store', 'accept-ranges': 'bytes' };
    if (original) headers['content-disposition'] = `attachment; filename*=UTF-8''${encodeURIComponent(original.filename).replace(/['()*]/g, c => '%' + c.charCodeAt(0).toString(16))}`;
    if (req.headers.range) {
      const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
      if (range && (range[1] || range[2])) {
        if (range[1]) { start = Number(range[1]); if (range[2]) end = Math.min(Number(range[2]), end); }
        else start = Math.max(0, stat.size - Number(range[2]));
      }
      if (!range || (!range[1] && !range[2]) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start < 0) {
        res.writeHead(416, { 'content-range': `bytes */${stat.size}` }); return res.end();
      }
      code = 206; headers['content-range'] = `bytes ${start}-${end}/${stat.size}`;
    }
    headers['content-length'] = end - start + 1;
    res.writeHead(code, headers);
    if (req.method === 'HEAD') return res.end();
    const stream = fs.createReadStream(filename, { start, end });
    stream.on('error', () => res.destroy()); res.on('close', () => stream.destroy()); stream.pipe(res);
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const catalog = JSON.parse(fs.readFileSync(path.join(root, '.local/photo-app/catalog.json'), 'utf8'));
    const source = JSON.parse(fs.readFileSync(path.join(root, '.local/photo-app/source.json'), 'utf8'));
    const port = Number(process.env.PHOTO_PREVIEW_PORT || 8766);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('预览端口无效');
    createPhotoServer({ catalog, sourceDirectory: source.directory, scenario: process.env.PHOTO_PREVIEW_SCENARIO || 'normal' })
      .listen(port, '127.0.0.1', () => console.log(`本地照片应用：http://127.0.0.1:${port}/photos/index.html?lang=zh（未连接 AWS）`));
  } catch (error) { console.error('请先运行 prepare-photo-data.cjs 准备本地资料。' + error.message); process.exitCode = 1; }
}
