// 资料读取逻辑。queryPage 由 AWS 适配器或本地模拟器提供。
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const SORT_KEY = /^PHOTO#\d{9}#[a-z0-9][a-z0-9-]{0,63}$/;
export const PAGE_SIZE = 24;

export function encodeCursor(key) {
  return key ? Buffer.from(JSON.stringify(key)).toString('base64url') : null;
}

function decodeCursor(token, partition) {
  if (!token) return undefined;
  if (token.length > 512 || !/^[A-Za-z0-9_-]+$/.test(token)) throw new Error('INVALID_CURSOR');
  try {
    const key = JSON.parse(Buffer.from(token, 'base64url').toString('utf8'));
    if (Object.keys(key).length !== 2 || key.PK !== partition || !SORT_KEY.test(key.SK)) throw new Error();
    return key;
  } catch { throw new Error('INVALID_CURSOR'); }
}

// 只允许返回选定的同源照片路径；不把整条数据库记录直接发给浏览器。
function publicPhoto(item, albumId) {
  if (typeof item.id !== 'string' || !ID.test(item.id) || !Number.isSafeInteger(item.sizeBytes) || item.sizeBytes <= 0 ||
      !/^[a-f0-9]{64}$/.test(item.sha256) ||
      !/^assets\/photos\/[A-Za-z0-9_.-]+\.webp$/.test(item.previewKey) ||
      item.originalKey !== `photo-originals/${albumId}/${item.id}.jpg` ||
      !/^[^/\\\x00-\x1f]+\.jpe?g$/i.test(item.filename) ||
      !['ja', 'zh', 'en'].every(lang => typeof item.title?.[lang] === 'string' && item.title[lang].length > 0 && item.title[lang].length <= 300)) {
    throw new Error('INVALID_PHOTO_RECORD');
  }
  return {
    id: item.id, title: { ja: item.title.ja, zh: item.title.zh, en: item.title.en },
    previewUrl: '/' + item.previewKey,
    downloadUrl: '/' + item.originalKey,
    filename: item.filename, sizeBytes: item.sizeBytes, sha256: item.sha256
  };
}

export function createHandler({ queryPage, albumId = 'main', logError = console.error }) {
  if (!ID.test(albumId)) throw new Error('INVALID_ALBUM_ID');
  const partition = `ALBUM#${albumId}`;
  return async function handler(event) {
    const method = event.requestContext?.http?.method;
    const respond = (statusCode, value, extraHeaders = {}) => ({
      statusCode,
      headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff', ...extraHeaders },
      body: method === 'HEAD' ? '' : JSON.stringify(value)
    });
    if (event.rawPath !== '/api/photos') return respond(404, { code: 'NOT_FOUND' });
    if (!['GET', 'HEAD'].includes(method)) return respond(405, { code: 'METHOD_NOT_ALLOWED' }, { allow: 'GET, HEAD' });
    const params = new URLSearchParams(event.rawQueryString || '');
    if ([...params.keys()].some(key => key !== 'cursor') || params.getAll('cursor').length > 1) {
      return respond(400, { code: 'INVALID_REQUEST' });
    }
    let after;
    try { after = decodeCursor(params.get('cursor'), partition); }
    catch { return respond(400, { code: 'INVALID_CURSOR' }); }
    try {
      const page = await queryPage({ partition, after, limit: PAGE_SIZE });
      // 校验完整页面后返回；损坏资料不以“成功”静默遗漏。
      if (!Array.isArray(page.items) || page.items.length > PAGE_SIZE) throw new Error('INVALID_PAGE');
      const photos = page.items.map(item => publicPhoto(item, albumId));
      if (page.lastKey && (page.lastKey.PK !== partition || !SORT_KEY.test(page.lastKey.SK))) throw new Error('INVALID_PAGE_KEY');
      return respond(200, { photos, nextCursor: encodeCursor(page.lastKey) });
    } catch (error) {
      // 不记录 Cookie、完整 URL、照片内容或 AWS 凭据。
      logError(JSON.stringify({ code: 'PHOTO_READ_FAILED', name: error.name, requestId: event.requestContext?.requestId }));
      return respond(503, { code: 'PHOTO_SERVICE_UNAVAILABLE' });
    }
  };
}
