// 读取明确选择的原 JPG；只在被 Git 忽略的 .local/ 内生成资料，不修改/复制原图。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');

function prepare(sourceDirectory) {
  const source = fs.realpathSync(sourceDirectory);
  const selection = JSON.parse(fs.readFileSync(path.join(root, 'config/photo-selection.json'), 'utf8'));
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(selection.albumId) || !/^[A-Za-z0-9_.-]{3,255}$/.test(selection.tableName)) throw new Error('相册 ID 或表名无效。');
  const context = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'dist/content.js'), 'utf8'), context);
  const usedIds = new Set();
  const usedOrders = new Set();
  const items = selection.photos.map(photo => {
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(photo.id) || usedIds.has(photo.id) ||
        !Number.isSafeInteger(photo.order) || photo.order < 1 || photo.order > 999999999 || usedOrders.has(photo.order) ||
        !/^[^/\\\x00-\x1f]+\.jpe?g$/i.test(photo.filename) ||
        !/^assets\/photos\/[A-Za-z0-9_.-]+\.webp$/.test(photo.previewKey)) throw new Error('照片 ID、文件名、顺序或预览路径无效/重复。');
    usedIds.add(photo.id); usedOrders.add(photo.order);
    if (!fs.existsSync(path.join(root, 'dist', photo.previewKey))) throw new Error(`预览图不存在：${photo.id}`);
    const file = fs.readFileSync(path.join(source, photo.filename));
    if (file[0] !== 0xff || file[1] !== 0xd8) throw new Error(`不是 JPG 文件：${photo.id}`);
    const title = Object.fromEntries(['ja', 'zh', 'en'].map(lang => {
      const value = photo.title?.[lang] ?? context.window.PORTFOLIO_TEXT[lang][photo.captionKey];
      if (typeof value !== 'string' || !value.trim() || value.length > 300) throw new Error(`缺少 ${photo.id} 的 ${lang} 标题，或标题过长。`);
      return [lang, value];
    }));
    return {
      PK: `ALBUM#${selection.albumId}`, SK: `PHOTO#${String(photo.order).padStart(9, '0')}#${photo.id}`,
      id: photo.id, title, previewKey: photo.previewKey,
      originalKey: `photo-originals/${selection.albumId}/${photo.id}.jpg`, filename: photo.filename,
      sizeBytes: file.length, sha256: crypto.createHash('sha256').update(file).digest('hex')
    };
  }).sort((a, b) => a.SK.localeCompare(b.SK));
  if (items.length === 0) throw new Error('选择清单不能为空。');
  const directory = path.join(root, '.local/photo-app');
  fs.mkdirSync(directory, { recursive: true });
  const write = (name, value) => fs.writeFileSync(path.join(directory, name), JSON.stringify(value, null, 2) + '\n');
  write('catalog.json', items);
  write('source.json', { directory: source });
  // BatchWriteItem 每个请求最多 25 条，自动拆成若干份；上传前需核对表名及权限。
  for (let start = 0; start < items.length; start += 25) {
    const marshal = item => Object.fromEntries(Object.entries(item).map(([key, value]) => [key,
      typeof value === 'number' ? { N: String(value) } : typeof value === 'string' ? { S: value } :
        { M: Object.fromEntries(Object.entries(value).map(([lang, text]) => [lang, { S: text }])) }]));
    write(`batch-${String(start / 25 + 1).padStart(3, '0')}.json`, {
      [selection.tableName]: items.slice(start, start + 25).map(item => ({ PutRequest: { Item: marshal(item) } }))
    });
  }
  write('upload-plan.json', items.map(({ filename, originalKey, sizeBytes, sha256 }) => ({ filename, originalKey, sizeBytes, sha256 })));
  console.log(`已生成 ${items.length} 张照片的本地资料，共 ${items.reduce((sum, item) => sum + item.sizeBytes, 0).toLocaleString('en-US')} 字节。没有调用 AWS。`);
  return items;
}
module.exports = { prepare };
if (require.main === module) {
  try {
    if (!process.argv[2]) throw new Error('用法：node scripts/prepare-photo-data.cjs "原 JPG 所在文件夹"');
    prepare(process.argv[2]);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
