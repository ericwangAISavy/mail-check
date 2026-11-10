(function () {
  var marker = document.querySelector('[data-offerpath-startup]');
  if (!marker) return;
  var root = document.getElementById('root');
  // Keep a single curtain outside React through authentication, bootstrap,
  // lazy route imports and the first page query. Never show intermediate shells.
  document.body.appendChild(marker);
  root.setAttribute('inert', '');
  var revealTimer;
  function hasAppContent() { return root.children.length > 0 || root.textContent.trim().length > 0; }
  function ready() { return hasAppContent() && !root.querySelector('.loading-state, .login-pending'); }
  var revealObserver = new MutationObserver(checkReady);
  function checkReady() {
    if (!root.isConnected) { clearTimeout(revealTimer); clearTimeout(timer); stop(); revealObserver.disconnect(); marker.remove(); return; }
    if (!ready()) { clearTimeout(revealTimer); revealTimer = null; return; }
    // Repeated status/chart updates must not continually restart the reveal.
    if (revealTimer) return;
    revealTimer = setTimeout(function () {
      if (!ready()) { revealTimer = null; return; }
      clearTimeout(timer);
      stop();
      root.removeAttribute('inert');
      marker.classList.add('startup-leaving');
      revealObserver.disconnect();
      setTimeout(function () { marker.remove(); }, 220);
    }, 180);
  }
  revealObserver.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'], characterData: true });
  var retried = new URL(location.href).searchParams.has('_offerpath_boot');
  var stopped = false;
  var retrying = false;
  var timer;
  var observer;
  function stop() {
    stopped = true;
    window.removeEventListener('error', failed, true);
    window.removeEventListener('unhandledrejection', failed);
    if (observer) observer.disconnect();
  }
  function active() {
    if (!marker.isConnected || hasAppContent()) stop();
    return !stopped;
  }
  function freshUrl() {
    var url = new URL(location.href);
    url.searchParams.set('_offerpath_boot', String(Date.now()));
    return url.href;
  }
  function retry() {
    if (!marker.isConnected || retrying) return;
    retrying = true;
    location.replace(freshUrl());
  }
  function showFailure(slow) {
    if (!marker.isConnected || !root.isConnected) return;
    clearTimeout(timer);
    marker.setAttribute('role', 'alert');
    marker.replaceChildren();
    var title = document.createElement('strong');
    title.textContent = slow ? 'OfferPath is taking longer to open' : 'OfferPath could not start';
    var detail = document.createElement('p');
    detail.textContent = 'Please check your connection and try again. If this continues, contact your administrator.';
    var link = document.createElement('a');
    link.textContent = 'Try loading OfferPath again';
    link.href = freshUrl();
    link.style.cssText = 'color:#66d9ef;text-decoration:underline;font-weight:600';
    link.addEventListener('click', function (event) { event.preventDefault(); retry(); });
    marker.append(title, detail, link);
  }
  function ownScript(raw) {
    if (!raw) return false;
    try {
      var url = new URL(raw, location.href);
      var origin = new URL(location.href).origin;
      return url.origin === origin && /^\/(?:assets|src)\//.test(url.pathname);
    } catch (_) { return false; }
  }
  function failed(event) {
    if (!active() || retrying) return;
    var downloadFailure = event.type === 'error' && event.target instanceof HTMLScriptElement;
    if (downloadFailure) {
      // Cloudflare can inject an optional cross-origin analytics beacon. Its
      // CSP failure (or an extension's script failure) must not abort startup.
      if (!ownScript(event.target.src)) return;
    } else if (event.type === 'error') {
      if (!ownScript(event.filename)) return;
    } else {
      var stack = event.reason && event.reason.stack;
      var urls = typeof stack === 'string' ? stack.match(/https?:\/\/[^\s)]+/g) || [] : [];
      if (!urls.some(ownScript)) return;
    }
    // Retrying a download can help; executing the same broken code cannot.
    if (downloadFailure && !retried) retry();
    else showFailure(false);
  }
  window.addEventListener('error', failed, true);
  window.addEventListener('unhandledrejection', failed);
  observer = new MutationObserver(active);
  observer.observe(document.getElementById('root'), { childList: true, subtree: true });
  timer = setTimeout(function () { showFailure(true); }, 15000);
})();
