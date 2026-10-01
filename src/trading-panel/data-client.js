/* Shared read-only requests: coalesce duplicate calls and pause in hidden tabs. */
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
  window.labFetch = async (url, options = {}) => {
    await visible();
    const key = String(url), now = performance.now();
    const prior = cache.get(key);
    if (prior && now - prior.time < 750) return prior.response.clone();
    if (!pending.has(key)) {
      // Start timeout after visibility resumes, not while Safari is suspended.
      const work = fetch(url, {...options, cache:'no-store', signal:AbortSignal.timeout(8000)})
        .then(response => {
          if (response.ok) cache.set(key, {time:performance.now(), response:response.clone()});
          return response;
        }).finally(() => pending.delete(key));
      pending.set(key, work);
    }
    return (await pending.get(key)).clone();
  };
})();
