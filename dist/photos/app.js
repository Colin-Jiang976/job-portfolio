(() => {
  const texts = window.PHOTO_TEXT;
  const gallery = document.querySelector('#gallery');
  const status = document.querySelector('#status');
  const retry = document.querySelector('#retry');
  const dialog = document.querySelector('#preview-dialog');
  const previous = document.querySelector('#previous');
  const next = document.querySelector('#next');
  let language = 'ja', photos = [], cursors = [null], pageIndex = 0, nextCursor = null;
  let statusKey = 'loading', loading = false, selectedPhoto = null, activeRequest;
  try { language = localStorage.getItem('cloud-nature-language') || 'ja'; } catch {}
  const requestedLanguage = new URLSearchParams(location.search).get('lang');
  if (Object.hasOwn(texts, requestedLanguage)) language = requestedLanguage;
  if (!Object.hasOwn(texts, language)) language = 'ja';
  const text = (key, values = {}) => texts[language][key].replace(/\{(\w+)\}/g, (_, name) => values[name] ?? '');
  function updateStatus(key) { statusKey = key; status.textContent = key ? text(key) : ''; }
  // 人工标题可选；单一标题用于所有语言，没有当前语言标题时显示原文件名。
  function photoTitle(photo) {
    if (typeof photo.title === 'string' && photo.title.trim()) return photo.title;
    return photo.title?.[language]?.trim() || photo.filename;
  }

  function updatePreview() {
    if (!selectedPhoto) return;
    document.querySelector('#preview-title').textContent = photoTitle(selectedPhoto);
    document.querySelector('#preview-image').src = selectedPhoto.previewUrl;
    document.querySelector('#preview-image').alt = photoTitle(selectedPhoto);
    const link = document.querySelector('#preview-download');
    link.href = selectedPhoto.downloadUrl; link.download = selectedPhoto.filename;
  }
  function render() {
    document.documentElement.lang = language;
    document.title = texts[language].pageTitle;
    document.querySelectorAll('[data-i18n]').forEach(node => { node.textContent = text(node.dataset.i18n); });
    document.querySelectorAll('[data-lang]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.lang === language)));
    gallery.replaceChildren();
    photos.forEach(photo => {
      const card = document.createElement('article'); card.className = 'photo-card';
      const preview = document.createElement('button'); preview.type = 'button'; preview.className = 'preview-button';
      preview.setAttribute('aria-label', text('preview', { title: photoTitle(photo) }));
      const image = document.createElement('img'); image.src = photo.previewUrl; image.alt = photoTitle(photo); image.loading = 'lazy';
      image.addEventListener('error', () => {
        if (card.querySelector('.image-error')) return;
        const warning = document.createElement('p'); warning.className = 'image-error'; warning.textContent = text('imageError'); card.append(warning);
      });
      preview.append(image);
      preview.addEventListener('click', () => { selectedPhoto = photo; updatePreview(); dialog.showModal(); });
      const title = document.createElement('h3'); title.textContent = photoTitle(photo);
      const info = document.createElement('p'); info.className = 'file-info';
      info.textContent = `JPG · ${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(photo.sizeBytes / 1000000)} MB`;
      const download = document.createElement('a'); download.className = 'download'; download.href = photo.downloadUrl;
      download.download = photo.filename; download.textContent = text('download');
      download.addEventListener('click', () => updateStatus('downloadStarted'));
      card.append(preview, title, info, download); gallery.append(card);
    });
    document.querySelector('#page-summary').textContent = photos.length ? text('loaded', { start: pageIndex * 24 + 1, end: pageIndex * 24 + photos.length }) : '';
    document.querySelector('#page-number').textContent = text('page', { page: pageIndex + 1 });
    document.querySelector('#pagination').hidden = !photos.length;
    previous.disabled = loading || pageIndex === 0; next.disabled = loading || !nextCursor;
    gallery.setAttribute('aria-busy', String(loading));
    updateStatus(statusKey); updatePreview();
  }
  function validatePhoto(photo) {
    const sameOriginPath = (value, prefix) => typeof value === 'string' && value.startsWith(prefix) &&
      new URL(value, location.origin).origin === location.origin && !value.includes('..');
    const validTitle = value => value == null || (typeof value === 'string' && value.length <= 300) ||
      (typeof value === 'object' && !Array.isArray(value) && Object.entries(value).every(([lang, title]) =>
        ['ja', 'zh', 'en'].includes(lang) && typeof title === 'string' && title.length <= 300));
    return photo && typeof photo.id === 'string' && Number.isSafeInteger(photo.sizeBytes) && photo.sizeBytes > 0 &&
      typeof photo.filename === 'string' && validTitle(photo.title) &&
      sameOriginPath(photo.previewUrl, '/assets/photos/') && sameOriginPath(photo.downloadUrl, '/photo-originals/main/');
  }
  async function loadPage(cursor, targetIndex) {
    activeRequest?.abort(); activeRequest = new AbortController();
    const request = activeRequest;
    loading = true; retry.hidden = true; updateStatus('loading'); render();
    const timeout = setTimeout(() => request.abort(), 15000);
    try {
      const response = await fetch('/api/photos' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''), { signal: request.signal, credentials: 'same-origin', cache: 'no-store' });
      if (response.status === 403 || response.status === 401) throw new Error('invitationRequired');
      if (response.status === 400) throw new Error('invalidCursor');
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (!Array.isArray(data.photos) || data.photos.length > 24 || !data.photos.every(validatePhoto) ||
          !(data.nextCursor === null || typeof data.nextCursor === 'string')) throw new Error('unavailable');
      photos = data.photos; nextCursor = data.nextCursor; pageIndex = targetIndex;
      cursors[targetIndex] = cursor; cursors.length = targetIndex + 1;
      document.querySelector('#local-notice').hidden = data.mode !== 'local';
      updateStatus(photos.length ? '' : 'empty');
    } catch (error) {
      if (request !== activeRequest) return;
      updateStatus(['invitationRequired', 'invalidCursor'].includes(error.message) ? error.message : 'unavailable');
      retry.hidden = statusKey === 'invitationRequired';
      if (statusKey === 'invitationRequired') { photos = []; nextCursor = null; }
    } finally {
      clearTimeout(timeout);
      if (request === activeRequest) { loading = false; render(); }
    }
  }
  document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => {
    language = button.dataset.lang;
    try { localStorage.setItem('cloud-nature-language', language); } catch {}
    render();
  }));
  previous.addEventListener('click', () => loadPage(cursors[pageIndex - 1], pageIndex - 1));
  next.addEventListener('click', () => loadPage(nextCursor, pageIndex + 1));
  retry.addEventListener('click', () => statusKey === 'invalidCursor' ? loadPage(null, 0) : loadPage(cursors[pageIndex], pageIndex));
  document.querySelector('#close-preview').addEventListener('click', () => dialog.close());
  document.querySelector('#preview-download').addEventListener('click', () => updateStatus('downloadStarted'));
  dialog.addEventListener('close', () => { selectedPhoto = null; });
  render(); loadPage(null, 0);
})();
