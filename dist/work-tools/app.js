(() => {
  const texts = window.WORK_TOOLS_TEXT;
  let language = 'ja';
  try { language = localStorage.getItem('cloud-nature-language') || 'ja'; } catch {}
  const requested = new URLSearchParams(location.search).get('lang');
  if (Object.hasOwn(texts, requested)) language = requested;
  if (!Object.hasOwn(texts, language)) language = 'ja';
  function render() {
    const text = texts[language];
    document.documentElement.lang = language;
    document.title = text.pageTitle;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = text[el.dataset.i18n]; });
    document.querySelectorAll('[data-lang]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.lang === language)));
    document.querySelectorAll('[data-home]').forEach(link => { link.href = '../index.html?lang=' + language + '#work'; });
    document.querySelector('[data-log-check]').href = '../log-check/index.html?lang=' + language;
    document.querySelectorAll('[data-architecture]').forEach(link => { link.href = '../architecture.html?lang=' + language; });
  }
  document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => {
    language = button.dataset.lang;
    try { localStorage.setItem('cloud-nature-language', language); } catch {}
    const url = new URL(location.href); url.searchParams.set('lang', language); history.replaceState(null, '', url);
    render();
  }));
  render();
})();
