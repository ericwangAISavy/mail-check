(function () {
  var marker = document.querySelector('[data-offerpath-startup]');
  if (!marker) return;
  var retried = new URL(location.href).searchParams.has('_offerpath_boot');
  var stopped = false;
  var retrying = false;
  var timer;
  var observer;
  function stop() {
    stopped = true;
    clearTimeout(timer);
    window.removeEventListener('error', failed, true);
    window.removeEventListener('unhandledrejection', failed);
    if (observer) observer.disconnect();
  }
  function active() {
    if (!marker.isConnected) stop();
    return !stopped;
  }
  function freshUrl() {
    var url = new URL(location.href);
    url.searchParams.set('_offerpath_boot', String(Date.now()));
    return url.href;
  }
  function retry() {
    if (!active() || retrying) return;
    retrying = true;
    location.replace(freshUrl());
  }
  function showFailure(slow) {
    if (!active()) return;
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
    link.style.cssText = 'color:#075985;text-decoration:underline;font-weight:600';
    link.addEventListener('click', function (event) { event.preventDefault(); retry(); });
    marker.append(title, detail, link);
  }
  function failed(event) {
    if (!active() || retrying) return;
    // Ignore unrelated image/style failures: only scripts and runtime errors block boot.
    if (event.type === 'error' && event.target !== window && !(event.target instanceof HTMLScriptElement)) return;
    if (!retried) retry();
    else showFailure(false);
  }
  window.addEventListener('error', failed, true);
  window.addEventListener('unhandledrejection', failed);
  observer = new MutationObserver(active);
  observer.observe(document.getElementById('root'), { childList: true, subtree: true });
  timer = setTimeout(function () { showFailure(true); }, 15000);
})();
