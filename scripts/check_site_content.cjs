// 只检查本地静态源码；不启动网页、不联网、不修改文件。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(process.argv[2]);
const errors = [], languageFiles = [], photoReferences = [];
let scriptCount = 0;
function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry =>
    entry.isDirectory() ? files(path.join(directory, entry.name)) : [path.join(directory, entry.name)]);
}
for (const file of files(root).filter(file => file.endsWith('.js'))) {
  const relative = path.relative(root, file).replaceAll(path.sep, '/');
  try {
    const script = new vm.Script(fs.readFileSync(file, 'utf8'), { filename: relative });
    scriptCount++;
    if (path.basename(file) === 'content.js') {
      const context = { window: {} };
      script.runInNewContext(context, { timeout: 1000 });
      const candidates = Object.entries(context.window).filter(([key, value]) =>
        key.endsWith('_TEXT') && value && typeof value === 'object');
      if (candidates.length !== 1) throw new Error('须包含一份三语文案对象');
      const texts = candidates[0][1];
      if (JSON.stringify(Object.keys(texts).sort()) !== JSON.stringify(['en', 'ja', 'zh'])) throw new Error('语言必须是ja/zh/en');
      const keys = [...new Set(Object.values(texts).flatMap(text => Object.keys(text)))];
      for (const language of ['ja', 'zh', 'en']) {
        for (const key of keys) {
          if (typeof texts[language]?.[key] !== 'string') errors.push(`${relative}: ${language}.${key} 缺失或不是文字`);
        }
      }
      const html = path.join(path.dirname(file), 'index.html');
      if (fs.existsSync(html)) {
        for (const match of fs.readFileSync(html, 'utf8').matchAll(/\bdata-i18n(?:-alt|-aria-label)?\s*=\s*["']([^"']+)["']/g)) {
          for (const language of ['ja', 'zh', 'en']) {
            if (typeof texts[language]?.[match[1]] !== 'string') errors.push(`${relative}: HTML键 ${language}.${match[1]} 不存在`);
          }
        }
      }
      languageFiles.push({ file: relative, keyCount: keys.length,
        ...(texts.ja.roleValue ? { roleValues: Object.fromEntries(['ja', 'zh', 'en'].map(lang => [lang, texts[lang].roleValue])) } : {}) });
    } else if (relative === 'documents.js') {
      const context = { window: {} };
      script.runInNewContext(context, { timeout: 1000 });
      const documents = context.window.PORTFOLIO_DOCUMENTS;
      if (!documents || Object.keys(documents).sort().join() !== 'career,resume') throw new Error('材料配置必须含resume/career');
      for (const [slot, file] of Object.entries(documents)) {
        if (file === null) continue;
        if (typeof file !== 'string' || !/^documents\/[a-zA-Z0-9][a-zA-Z0-9._/-]*\.(pdf|docx)$/.test(file) ||
            file.split('/').some(part => !part || part === '.' || part === '..')) throw new Error(slot + ': 材料路径须为documents内的PDF/DOCX');
        const target = path.join(root, file);
        if (!fs.existsSync(target) || !fs.statSync(target).isFile()) throw new Error(slot + ': 材料文件不存在 ' + file);
        const bytes = fs.readFileSync(target);
        if (file.endsWith('.pdf') ? bytes.subarray(0, 5).toString() !== '%PDF-' : bytes.subarray(0, 4).toString('hex') !== '504b0304') {
          throw new Error(slot + ': 文件头与扩展名不符');
        }
        photoReferences.push({ source: relative, url: file });
      }
    } else if (relative === 'photos.js') {
      const context = { window: {} };
      script.runInNewContext(context, { timeout: 1000 });
      const photos = context.window.PORTFOLIO_PHOTOS;
      if (!photos?.hero || !Array.isArray(photos.gallery)) throw new Error('首页照片清单无效');
      for (const photo of [photos.hero, ...photos.gallery]) photoReferences.push({ source: relative, url: photo.src });
    }
  } catch (error) {
    errors.push(`${relative}: ${error.message}`);
  }
}
process.stdout.write(JSON.stringify({ ok: errors.length === 0, errors, scriptCount, languageFiles, photoReferences }));
process.exitCode = errors.length ? 1 : 0;
