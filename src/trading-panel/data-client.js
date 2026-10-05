/* Shared reads: coalesce duplicates; only the alert monitor can opt into background polling. */
(() => {
  const pending = new Map(), cache = new Map();
  let visibleWait;
  async function visible() {
    if (!document.hidden) return;
    if (!visibleWait) visibleWait = new Promise(resolve => {
      const resume = () => {
        if (document.hidden) return;
        document.removeEventListener('visibilitychange', resume);
        visibleWait = null; cache.clear(); resolve();
      };
      document.addEventListener('visibilitychange', resume);
    });
    await visibleWait;
  }
  document.addEventListener('visibilitychange', () => cache.clear());
  const timeoutFor = options => options.signal || AbortSignal.timeout(8000);
  const isHtml = (text, type) => /text\/html/i.test(type || '') || /^\s*<(?:!doctype|html|head|body)\b/i.test(text);

  async function parseJson(response, context = 'Сервер') {
    const type = response.headers.get('content-type') || '';
    const text = await response.text();
    let value;
    try { value = JSON.parse(text); }
    catch (_) {
      const message = isHtml(text, type)
        ? context + ': вместо ответа API получена HTML-страница. Откройте панель через SSH-туннель по адресу http://127.0.0.1:8787 и обновите страницу.'
        : context + ': сервер вернул некорректный ответ.';
      throw new Error(message);
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(context + ': сервер вернул ответ неверного формата.');
    }
    if (!response.ok) {
      throw new Error(value.error || context + ': HTTP ' + response.status);
    }
    return value;
  }

  window.labFetch = async (url, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase();
    const {background, ...requestOptions} = options;
    if (!(background === true && method === 'GET' && /^\/api\/market-alerts(?:\?|$)/.test(String(url)))) await visible();
    // Only safe, body-less reads can share a response. Commands must never
    // accidentally reuse a pending GET or another command to the same URL.
    const key = method === 'GET' && !options.body ? method + ' ' + String(url) : '';
    const request = () => fetch(url, {...requestOptions, cache:'no-store', signal:timeoutFor(requestOptions)});
    if (!key) return request();
    const now = performance.now();
    const prior = cache.get(key);
    if (prior && now - prior.time < 750) return prior.response.clone();
    if (!pending.has(key)) {
      // Start timeout after visibility resumes, not while Safari is suspended.
      const work = request()
        .then(response => {
          if (response.ok) cache.set(key, {time:performance.now(), response:response.clone()});
          return response;
        }).finally(() => pending.delete(key));
      pending.set(key, work);
    }
    return (await pending.get(key)).clone();
  };
  // A single friendly JSON parser keeps proxy/login HTML from leaking as the
  // browser's unhelpful "Unexpected token <" message into a trading screen.
  window.labParseJson = parseJson;
  window.labJson = async (url, options = {}, context = 'Сервер') =>
    parseJson(await window.labFetch(url, options), context);
})();
