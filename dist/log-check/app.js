(() => {
  const texts = window.LOG_CHECK_TEXT;
  let language = 'ja', reports = [], generated = null, state = 'loading', controller;
  try { language = localStorage.getItem('cloud-nature-language') || 'ja'; } catch {}
  const requested = new URLSearchParams(location.search).get('lang');
  if (Object.hasOwn(texts, requested)) language = requested;
  if (!Object.hasOwn(texts, language)) language = 'ja';
  const t = (key) => texts[language][key];
  const list = document.querySelector('#reports');
  const status = document.querySelector('#status');
  const retry = document.querySelector('#retry');
  function date(value) { return new Date(value).toLocaleString({ ja: 'ja-JP', zh: 'zh-CN', en: 'en-GB' }[language], { timeZoneName: 'short' }); }
  const validDate = value => typeof value === 'string' && value.includes('T') && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
  function validReport(r) {
    const fields = ['id','source','scenario','engine','checked_at','status','counts','total_records','reason_category','notification'];
    if (!r || typeof r !== 'object' || Object.keys(r).sort().join() !== fields.sort().join() ||
        !/^\d{8}T\d{6}Z-[a-f0-9]{12}$/.test(r.id) || !validDate(r.checked_at) ||
        !['local','aws'].includes(r.engine) || !['OK','ALERT','INVALID'].includes(r.status)) return false;
    const sourceOK = r.scenario === 'normal' ? ['local-api','cloud-api'].includes(r.source) :
      r.scenario === 'read-failure' ? r.source === 'local-controlled' : r.scenario === 'invalid-format' && r.source === 'format-test';
    if (!sourceOK || r.status !== { normal: 'OK', 'read-failure': 'ALERT', 'invalid-format': 'INVALID' }[r.scenario]) return false;
    if (r.engine === 'local' || r.status === 'OK') {
      if (r.notification !== 'not-applicable') return false;
    } else if (!['unconfirmed','received'].includes(r.notification)) return false;
    if (r.status === 'INVALID') return r.counts === null && r.total_records === null && ['size','records','encoding','json','fields','empty'].includes(r.reason_category);
    return r.reason_category === null && r.counts && typeof r.counts === 'object' &&
      Object.keys(r.counts).sort().join() === 'ERROR,INFO,WARN' &&
      Object.values(r.counts).every(v => Number.isSafeInteger(v) && v >= 0) &&
      Number.isSafeInteger(r.total_records) && r.total_records > 0 && r.total_records <= 1000 &&
      r.total_records === r.counts.INFO + r.counts.WARN + r.counts.ERROR &&
      (r.status === 'OK' ? r.counts.ERROR === 0 : r.counts.ERROR > 0);
  }
  function node(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  function render() {
    document.documentElement.lang = language;
    document.title = t('pageTitle');
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-lang]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.lang === language)));
    document.querySelectorAll('.brand,#back').forEach(link => {
      link.href = '../index.html?lang=' + language + (link.id === 'back' ? '#work' : '');
    });
    status.textContent = state ? t(state) : '';
    retry.hidden = !['unavailable','empty'].includes(state);
    document.querySelector('#generated').textContent = generated ? t('generated').replace('{time}', date(generated)) : '';
    document.querySelector('#local-notice').hidden = !reports.length || !reports.every(r => r.engine === 'local');
    list.setAttribute('aria-busy', String(state === 'loading'));
    list.replaceChildren();
    for (const r of reports) {
      const card = node('article', undefined, 'report');
      card.dataset.status = r.status;
      card.append(node('span', r.status, 'badge'), node('h3', t(r.scenario)));
      const details = node('dl');
      const add = (label, value) => {
        const row = node('div'); row.append(node('dt', label), node('dd', value)); details.append(row);
      };
      add(t('source'), t(r.source)); add(t('engine'), t(r.engine)); add(t('checked'), date(r.checked_at));
      add(t('total'), r.total_records === null ? t('unknown') : String(r.total_records));
      add(t('notification'), t(r.notification));
      if (r.reason_category) add(t('reason'), t(r.reason_category === 'empty' ? 'emptyReason' : r.reason_category));
      card.append(details);
      if (r.counts) {
        const counts = node('div', undefined, 'counts');
        for (const level of ['INFO','WARN','ERROR']) counts.append(node('span', level + ' ' + r.counts[level]));
        card.append(counts);
      }
      card.append(node('p', t({ OK: 'okMeaning', ALERT: 'alertMeaning', INVALID: 'invalidMeaning' }[r.status]), 'meaning'));
      list.append(card);
    }
  }
  async function load() {
    controller?.abort(); controller = new AbortController();
    const request = controller;
    state = 'loading'; reports = []; generated = null; render();
    const timer = setTimeout(() => request.abort(), 15000);
    try {
      const response = await fetch('reports.json', { credentials: 'same-origin', cache: 'no-store', signal: request.signal });
      if (response.status === 401 || response.status === 403) throw new Error('invitation');
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (data?.schema_version !== '1.0' || !validDate(data.generated_at) || !Array.isArray(data.reports) ||
          data.reports.length > 30 || !data.reports.every(validReport) || new Set(data.reports.map(r => r.id)).size !== data.reports.length) throw new Error('unavailable');
      if (request !== controller) return;
      reports = data.reports; generated = data.generated_at; state = reports.length ? '' : 'empty';
    } catch (error) {
      if (request !== controller) return;
      state = error.message === 'invitation' ? 'invitation' : 'unavailable';
    } finally { clearTimeout(timer); if (request === controller) render(); }
  }
  document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => {
    language = button.dataset.lang;
    try { localStorage.setItem('cloud-nature-language', language); } catch {}
    const url = new URL(location.href); url.searchParams.set('lang', language); history.replaceState(null, '', url);
    render();
  }));
  retry.addEventListener('click', load);
  load();
})();
