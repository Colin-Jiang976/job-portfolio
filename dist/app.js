// 页面文字从 content.js 读取；照片路径与顺序从 photos.js 读取。
(() => {
  const translations = window.PORTFOLIO_TEXT;
  const languageButtons = document.querySelectorAll('[data-lang]');
  const menuButton = document.querySelector('.menu-toggle');
  const mobileNav = document.querySelector('#mobile-nav');

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
    // 某些浏览器或本地文件模式会禁用存储；禁用时仍可正常切换。
    try { localStorage.setItem('cloud-nature-language', language); } catch {}
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
  document.querySelector('#print-page').addEventListener('click', () => window.print());

  let initialLanguage = 'ja';
  try { initialLanguage = localStorage.getItem('cloud-nature-language') || 'ja'; } catch {}
  setLanguage(Object.hasOwn(translations, initialLanguage) ? initialLanguage : 'ja');
})();
