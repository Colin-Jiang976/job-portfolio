// 页面文字从 content.js 读取；照片路径与顺序从 photos.js 读取。
(() => {
  const translations = window.PORTFOLIO_TEXT;
  // 新相册入口单独补充三语，保留本人原 content.js 文案的字节内容。
  const photoAppLabels = {
    ja: '写真を閲覧・ダウンロード',
    zh: '浏览与下载照片',
    en: 'Browse & download photos'
  };
  const languageButtons = document.querySelectorAll('[data-lang]');
  const menuButton = document.querySelector('.menu-toggle');
  const mobileNav = document.querySelector('#mobile-nav');
  const architecture = document.querySelector('#architecture');
  const architectureButtons = document.querySelectorAll('[data-architecture-view]');
  const architectureExplanations = {
    all: 'architectureExplainAll', page: 'architectureExplainPage',
    catalog: 'architectureExplainCatalog', download: 'architectureExplainDownload'
  };
  let architectureView = 'all';

  function renderContact(text) {
    const list = document.querySelector('#contact-links');
    const contact = window.PORTFOLIO_CONTACT || {};
    list.replaceChildren();
    const add = (label, value, href) => {
      const row = document.createElement('p');
      const link = document.createElement('a'); link.className = 'text-link'; link.href = href;
      const caption = document.createElement('span'); caption.textContent = label;
      const display = document.createElement('span'); display.textContent = value;
      link.append(caption, display); row.append(link); list.append(row);
    };
    if (typeof contact.email === 'string' && /^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$/.test(contact.email)) {
      add(text.contactEmailLabel, contact.email, 'mailto:' + contact.email);
    }
    if (typeof contact.phone === 'string' && /^\+[0-9]{8,15}$/.test(contact.phone)) {
      add(text.contactPhoneLabel, typeof contact.phoneLabel === 'string' ? contact.phoneLabel : contact.phone, 'tel:' + contact.phone);
    }
  }

  function renderDocuments(text) {
    const list = document.querySelector('#document-downloads');
    list.replaceChildren();
    for (const slot of ['resume', 'career']) {
      const file = window.PORTFOLIO_DOCUMENTS?.[slot];
      if (typeof file !== 'string' || !/^documents\/[a-zA-Z0-9][a-zA-Z0-9._/-]*\.(pdf|docx)$/.test(file) ||
          file.split('/').some(part => !part || part === '.' || part === '..')) continue;
      const link = document.createElement('a');
      link.className = 'text-link'; link.href = file; link.download = file.split('/').at(-1);
      link.textContent = text[slot === 'resume' ? 'downloadResume' : 'downloadCareer'];
      const row = document.createElement('p'); row.append(link); list.append(row);
    }
    document.querySelector('#document-status').textContent = text[list.childElementCount ? 'documentsReady' : 'documentsPending'];
  }

  function renderArchitecture(language) {
    if (!architecture) return;
    architecture.dataset.view = architectureView;
    architectureButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.architectureView === architectureView));
    });
    const explanation = document.querySelector('#architecture-explanation');
    explanation.dataset.i18n = architectureExplanations[architectureView];
    explanation.textContent = translations[language][explanation.dataset.i18n];
  }

  architectureButtons.forEach(button => button.addEventListener('click', () => {
    if (!Object.hasOwn(architectureExplanations, button.dataset.architectureView)) return;
    architectureView = button.dataset.architectureView;
    renderArchitecture(document.documentElement.lang);
  }));

  // 按配置生成相册。更换图片、排序或标题不需要修改这段代码。
  const photos = window.PORTFOLIO_PHOTOS;
  const hero = document.querySelector('#hero-photo');
  hero.src = photos.hero.src;
  hero.width = photos.hero.width;
  hero.height = photos.hero.height;
  hero.dataset.i18nAlt = photos.hero.captionKey;
  const gallery = document.querySelector('#photo-gallery');
  photos.gallery.forEach((photo, index) => {
    const figure = document.createElement('figure');
    figure.className = 'photo-slot photo-card';
    const link = document.createElement('a');
    link.href = photo.src;
    link.target = '_blank';
    link.rel = 'noopener';
    const image = document.createElement('img');
    image.src = photo.src;
    image.width = photo.width;
    image.height = photo.height;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.dataset.i18nAlt = photo.captionKey;
    link.append(image);
    const caption = document.createElement('figcaption');
    const number = document.createElement('span');
    number.textContent = `PHOTOGRAPHY / ${String(index + 1).padStart(2, '0')}`;
    const title = document.createElement('span');
    title.dataset.i18n = photo.captionKey;
    caption.append(number, title);
    figure.append(link, caption);
    gallery.append(figure);
  });

  function setLanguage(language) {
    if (!Object.hasOwn(translations, language)) return;
    const text = translations[language];
    document.documentElement.lang = language;
    document.title = text.pageTitle;
    document.querySelector('meta[name="description"]').content = text.pageDescription;
    document.querySelectorAll('[data-i18n]').forEach(element => {
      const key = element.dataset.i18n;
      if (Object.hasOwn(text, key)) element.textContent = text[key];
    });
    document.querySelectorAll('[data-i18n-alt]').forEach(image => {
      image.alt = text[image.dataset.i18nAlt] || '';
    });
    languageButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.lang === language));
    });
    document.querySelectorAll('[data-photo-app-link]').forEach(link => {
      link.href = `photos/index.html?lang=${language}`;
      link.querySelector('[data-photo-app-label]').textContent = photoAppLabels[language];
    });
    renderArchitecture(language);
    document.querySelectorAll('[data-log-check-link]').forEach(link => {
      link.href = `log-check/index.html?lang=${language}`;
    });
    document.querySelectorAll('[data-tools-link]').forEach(link => {
      link.href = `work-tools/index.html?lang=${language}`;
    });
    renderDocuments(text);
    renderContact(text);
    // 某些浏览器或本地文件模式会禁用存储；禁用时仍可正常切换。
    try { localStorage.setItem('cloud-nature-language', language); } catch {}
    // 链接中的lang也同步，避免刷新时旧参数覆盖刚选择的语言。
    try {
      const url = new URL(location.href);
      url.searchParams.set('lang', language);
      history.replaceState(null, '', url);
    } catch {}
  }

  languageButtons.forEach(button => {
    button.addEventListener('click', () => setLanguage(button.dataset.lang));
  });

  function closeMenu() {
    mobileNav.hidden = true;
    menuButton.setAttribute('aria-expanded', 'false');
  }

  menuButton.addEventListener('click', () => {
    const willOpen = mobileNav.hidden;
    mobileNav.hidden = !willOpen;
    menuButton.setAttribute('aria-expanded', String(willOpen));
  });
  mobileNav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !mobileNav.hidden) {
      closeMenu();
      menuButton.focus();
    }
  });
  window.matchMedia('(min-width: 761px)').addEventListener('change', event => {
    if (event.matches) closeMenu();
  });

  let initialLanguage = 'ja';
  try { initialLanguage = localStorage.getItem('cloud-nature-language') || 'ja'; } catch {}
  const requestedLanguage = new URLSearchParams(location.search).get('lang');
  if (Object.hasOwn(translations, requestedLanguage)) initialLanguage = requestedLanguage;
  setLanguage(Object.hasOwn(translations, initialLanguage) ? initialLanguage : 'ja');
})();
