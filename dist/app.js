// 页面只需要三个交互：切换语言、手机导航和打印。
(() => {
  const translations = window.PORTFOLIO_TEXT;
  const languageButtons = document.querySelectorAll('[data-lang]');
  const menuButton = document.querySelector('.menu-toggle');
  const mobileNav = document.querySelector('#mobile-nav');

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
