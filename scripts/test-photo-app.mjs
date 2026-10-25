import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createHandler, encodeCursor } from '../backend/photo-api/core.mjs';
import { createPhotoServer } from './photo-dev-server.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const catalog = JSON.parse(fs.readFileSync(path.join(root, '.local/photo-app/catalog.json'), 'utf8'));
const source = JSON.parse(fs.readFileSync(path.join(root, '.local/photo-app/source.json'), 'utf8'));
const event = (query = '', method = 'GET') => ({ rawPath: '/api/photos', rawQueryString: query, requestContext: { http: { method } } });

test('三语界面键一致，已有文案和照片标题可用', () => {
  const context = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'dist/photos/content.js'), 'utf8'), context);
  const texts = context.window.PHOTO_TEXT;
  assert.deepEqual(Object.keys(texts.ja).sort(), Object.keys(texts.zh).sort());
  assert.deepEqual(Object.keys(texts.ja).sort(), Object.keys(texts.en).sort());
  for (const match of fs.readFileSync(path.join(root, 'dist/photos/index.html'), 'utf8').matchAll(/data-i18n="([^"]+)"/g)) {
    assert.ok(texts.ja[match[1]], match[1]);
  }
  assert.equal(catalog.length, 5);
});

test('53 条合成资料按 24/24/5 分页，无重漏；下一页游标按相册约束', async () => {
  const items = Array.from({ length: 53 }, (_, index) => {
    const id = `test-${String(index + 1).padStart(3, '0')}`;
    return { ...catalog[0], id, SK: `PHOTO#${String(index + 1).padStart(9, '0')}#${id}`,
      originalKey: `photo-originals/main/${id}.jpg`, internalOnly: 'must-not-be-returned' };
  });
  const handler = createHandler({ async queryPage({ partition, after, limit }) {
    assert.equal(partition, 'ALBUM#main'); assert.equal(limit, 24);
    const matching = items.filter(item => !after || item.SK > after.SK);
    const batch = matching.slice(0, limit);
    return { items: batch, lastKey: matching.length > limit ? { PK: partition, SK: batch.at(-1).SK } : null };
  } });
  let cursor = null; const ids = []; const sizes = [];
  do {
    const result = await handler(event(cursor ? `cursor=${cursor}` : ''));
    assert.equal(result.statusCode, 200);
    const data = JSON.parse(result.body);
    assert.equal(data.photos.some(photo => 'internalOnly' in photo), false);
    sizes.push(data.photos.length); ids.push(...data.photos.map(photo => photo.id)); cursor = data.nextCursor;
  } while (cursor);
  assert.deepEqual(sizes, [24, 24, 5]); assert.equal(new Set(ids).size, 53);
  assert.deepEqual(ids, items.map(item => item.id));
});

test('拒绝跨相册/畸形/重复游标、未知参数和写入方法，不触发资料读取', async () => {
  let reads = 0;
  const handler = createHandler({ queryPage: async () => { reads++; return { items: [] }; } });
  const crossAlbum = encodeCursor({ PK: 'ALBUM#private', SK: catalog[0].SK });
  for (const query of ['cursor=!', 'cursor=' + 'A'.repeat(513), 'cursor=' + crossAlbum, 'cursor=a&cursor=b', 'limit=999999']) {
    assert.equal((await handler(event(query))).statusCode, 400);
  }
  for (const method of ['POST', 'PUT', 'DELETE', 'OPTIONS']) assert.equal((await handler(event('', method))).statusCode, 405);
  assert.equal(reads, 0);
});

test('故障不泄露原始错误，坏资料不伪装成功，HEAD 无正文，空相册有明确结果', async () => {
  const errors = [];
  const failed = createHandler({ queryPage: async () => { throw new Error('private database detail'); }, logError: message => errors.push(message) });
  const result = await failed(event());
  assert.equal(result.statusCode, 503); assert.equal(result.body.includes('private database detail'), false);
  assert.equal(errors.length, 1);
  const corrupt = createHandler({ queryPage: async () => ({ items: [{ ...catalog[0], originalKey: 'https://outside.example/secret.jpg' }] }), logError: () => {} });
  assert.equal((await corrupt(event())).statusCode, 503);
  const empty = createHandler({ queryPage: async () => ({ items: [], lastKey: null }) });
  assert.deepEqual(JSON.parse((await empty(event())).body), { photos: [], nextCursor: null });
  assert.equal((await empty(event('', 'HEAD'))).body, '');
});

async function start(t, scenario = 'normal') {
  const server = createPhotoServer({ catalog, sourceDirectory: source.directory, scenario });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  t.after(() => new Promise(resolve => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}`;
}

test('真实本地读取五个原 JPG，逐个验证字节数和 SHA256；网页只引用预览图', async t => {
  const origin = await start(t);
  const response = await fetch(origin + '/api/photos');
  const data = await response.json(); assert.equal(data.mode, 'local'); assert.equal(data.photos.length, 5);
  for (const photo of data.photos) {
    const preview = await fetch(origin + photo.previewUrl); assert.equal(preview.status, 200); await preview.arrayBuffer();
    const file = await fetch(origin + photo.downloadUrl); assert.equal(file.status, 200);
    assert.match(file.headers.get('content-disposition'), /attachment/);
    const bytes = Buffer.from(await file.arrayBuffer());
    assert.equal(bytes.length, photo.sizeBytes);
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), photo.sha256);
  }
  const missing = await fetch(origin + '/photo-originals/main/not-provided.jpg'); assert.equal(missing.status, 404); await missing.text();
});

test('原图范围读取、HEAD、错误范围及本地路径/跨站限制', async t => {
  const origin = await start(t); const url = origin + '/' + catalog[0].originalKey;
  const partial = await fetch(url, { headers: { Range: 'bytes=0-99' } });
  assert.equal(partial.status, 206); assert.equal((await partial.arrayBuffer()).byteLength, 100);
  const head = await fetch(url, { method: 'HEAD' }); assert.equal(head.status, 200); assert.equal((await head.arrayBuffer()).byteLength, 0);
  const invalid = await fetch(url, { headers: { Range: 'bytes=999999999999-' } }); assert.equal(invalid.status, 416); await invalid.text();
  const privateFile = await fetch(origin + '/.local/cloudfront/private-key.pem'); assert.equal(privateFile.status, 404); await privateFile.text();
  const cross = await fetch(origin + '/api/photos', { headers: { Origin: 'https://outside.example' } }); assert.equal(cross.status, 403); await cross.text();
});

test('本地过期与服务失败场景返回 403/503；不是 CloudFront 真实授权验收', async t => {
  for (const [scenario, status] of [['expired', 403], ['unavailable', 503]]) {
    const origin = await start(t, scenario); const response = await fetch(origin + '/api/photos');
    assert.equal(response.status, status); await response.text();
  }
});
