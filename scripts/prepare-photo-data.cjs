// 读取明确选择的原 JPG；只在被 Git 忽略的 .local/ 内生成资料，不修改/复制原图。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');

function optionalTitle(value) {
  const clean = text => {
    if (typeof text !== 'string' || text.length > 300) throw new Error('标题须为不超过 300 字的文字。');
    return text.trim();
  };
  if (value == null) return undefined;
  if (typeof value === 'string') return clean(value) || undefined;
  if (typeof value !== 'object' || Array.isArray(value)) throw new Error('标题格式无效。');
  const translated = Object.fromEntries(['ja', 'zh', 'en'].filter(lang => value[lang] !== undefined)
    .map(lang => [lang, clean(value[lang])]).filter(([, text]) => text));
  return Object.keys(translated).length ? translated : undefined;
}

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
    // 旧五张可沿用已有译名；新增照片可以完全不填 title/captionKey。
    const titleSource = Object.hasOwn(photo, 'title') ? photo.title : (photo.captionKey ? Object.fromEntries(
      ['ja', 'zh', 'en'].filter(lang => context.window.PORTFOLIO_TEXT[lang][photo.captionKey] !== undefined)
        .map(lang => [lang, context.window.PORTFOLIO_TEXT[lang][photo.captionKey]])) : undefined);
    const title = optionalTitle(titleSource);
    return {
      PK: `ALBUM#${selection.albumId}`, SK: `PHOTO#${String(photo.order).padStart(9, '0')}#${photo.id}`,
      id: photo.id, ...(title === undefined ? {} : { title }), previewKey: photo.previewKey,
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
module.exports = { prepare, optionalTitle };
if (require.main === module) {
  try {
    if (!process.argv[2]) throw new Error('用法：node scripts/prepare-photo-data.cjs "原 JPG 所在文件夹"');
    prepare(process.argv[2]);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
