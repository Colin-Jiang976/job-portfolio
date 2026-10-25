(() => {
  'use strict';
  const translations = window.INVITATION_TEXT;
  const expectedKeyId = 'KCCXWBSABUX95';
  const cookieNames = ['CloudFront-Policy', 'CloudFront-Signature', 'CloudFront-Key-Pair-Id', 'CloudFront-Hash-Algorithm'];
  let language = 'ja';
  let state = 'checking';
  try {
    const saved = localStorage.getItem('cloud-nature-language');
    if (Object.hasOwn(translations, saved)) language = saved;
  } catch {}

  function render() {
    const text = translations[language];
    document.documentElement.lang = language;
    document.title = text.pageTitle;
    document.querySelector('#title').textContent = text.title;
    document.querySelector('#message').textContent = text[state];
    document.querySelectorAll('[data-lang]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.lang === language));
    });
  }
  function show(next) { state = next; render(); }
  document.querySelectorAll('[data-lang]').forEach(button => {
    button.addEventListener('click', () => {
      language = button.dataset.lang;
      try { localStorage.setItem('cloud-nature-language', language); } catch {}
      render();
    });
  });
  render();

  function clearCredentials() {
    for (const name of cookieNames) document.cookie = `${name}=; Path=/; Secure; SameSite=Lax; Max-Age=0`;
  }
  async function enter() {
    const fragment = location.hash.slice(1);
    // 尽早清除地址栏和当前历史项中的凭证，不写日志、不请求外站。
    if (fragment) history.replaceState(null, '', location.pathname + location.search);
    if (!fragment) { show('missing'); return; }
    if (location.protocol !== 'https:') { show('secure'); return; }
    let credentials;
    let expires;
    try {
      if (fragment.length > 8192) throw new Error('invalid');
      const params = new URLSearchParams(fragment);
      if ([...params.keys()].length !== 4 || params.get('v') !== '1') throw new Error('invalid');
      const policy = params.get('p');
      const signature = params.get('s');
      const keyId = params.get('k');
      if (keyId !== expectedKeyId || !/^[A-Za-z0-9_~\-]{1,4096}$/.test(policy || '') ||
          !/^[A-Za-z0-9_~\-]{344}$/.test(signature || '')) throw new Error('invalid');
      const raw = atob(policy.replace(/-/g, '+').replace(/_/g, '=').replace(/~/g, '/'));
      const parsed = JSON.parse(new TextDecoder().decode(Uint8Array.from(raw, c => c.charCodeAt(0))));
      if (!Array.isArray(parsed.Statement) || parsed.Statement.length !== 1) throw new Error('invalid');
      const statement = parsed.Statement[0];
      expires = statement.Condition?.DateLessThan?.['AWS:EpochTime'];
      if (statement.Resource !== location.origin + '/*' || !Number.isSafeInteger(expires)) throw new Error('invalid');
      if (expires <= Math.floor(Date.now() / 1000)) { show('expired'); return; }
      credentials = [policy, signature, keyId, 'SHA256'];
    } catch { show('invalid'); return; }

    try {
      clearCredentials();
      const remaining = expires - Math.floor(Date.now() / 1000);
      cookieNames.forEach((name, index) => {
        document.cookie = `${name}=${credentials[index]}; Path=/; Secure; SameSite=Lax; Max-Age=${remaining}`;
      });
      const stored = new Map(document.cookie.split(';').map(pair => {
        const trimmed = pair.trim();
        const separator = trimmed.indexOf('=');
        return [trimmed.slice(0, separator), trimmed.slice(separator + 1)];
      }));
      if (!cookieNames.every((name, index) => stored.get(name) === credentials[index])) {
        clearCredentials(); show('cookies'); return;
      }
      // 客户端只作格式检查；签名真实性与授权由 CloudFront 检查。
      const response = await fetch('/index.html', {
        method: 'HEAD', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        signal: AbortSignal.timeout(15000)
      });
      if (!response.ok) {
        clearCredentials(); show(response.status === 403 ? 'denied' : 'network'); return;
      }
      show('ready');
      location.replace('/');
    } catch { clearCredentials(); show('network'); }
  }
  enter();
})();
