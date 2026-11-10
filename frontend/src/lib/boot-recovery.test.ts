import source from "../../public/assets/startup-recovery-v3.js?raw";
import { afterEach, expect, it, vi } from "vitest";
afterEach(() => { document.getElementById('root')?.remove(); vi.runOnlyPendingTimers(); vi.useRealTimers(); });
function boot(url = 'https://example.test/applications?view=all#saved') {
  vi.useFakeTimers();
  document.body.innerHTML = '<div id="root"><main data-offerpath-startup role="status">Starting OfferPath</main></div>';
  const replace = vi.fn();
  new Function('window', 'document', 'location', source)(window, document, { href: url, replace });
  const fail = () => { const script = window.document.createElement('script'); window.document.body.append(script); script.dispatchEvent(new window.Event('error')); };
  return { window, replace, fail };
}
it('retries a missing module once with fresh HTML and preserves route, query and hash', () => {
  const { fail, replace } = boot(); fail(); fail();
  expect(replace).toHaveBeenCalledTimes(1);
  const url = new URL(replace.mock.calls[0][0]);
  expect(url.pathname).toBe('/applications'); expect(url.searchParams.get('view')).toBe('all'); expect(url.searchParams.has('_offerpath_boot')).toBe(true); expect(url.hash).toBe('#saved');
});
it('shows an accessible generic failure after retry, even with blocked storage', () => {
  const { window, fail, replace } = boot('https://example.test/applications?_offerpath_boot=1#saved');
  const storage = vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => { throw Error('blocked'); });
  window.dispatchEvent(new window.ErrorEvent('error', { message: 'secret token' })); fail();
  const alert = window.document.querySelector('[role="alert"]')!;
  expect(alert.textContent).toContain('OfferPath could not start'); expect(alert.textContent).not.toContain('secret token'); expect(replace).not.toHaveBeenCalled();
  const link = alert.querySelector('a')!; link.click(); link.click();
  expect(replace).toHaveBeenCalledTimes(1); expect(new URL(replace.mock.calls[0][0]).hash).toBe('#saved'); storage.mockRestore();
});
it('stops recovery as soon as React replaces the startup marker', async () => {
  const { window, fail, replace } = boot(); window.document.getElementById('root')!.textContent = 'An unsaved draft'; await Promise.resolve(); fail(); window.dispatchEvent(new window.Event('unhandledrejection')); vi.advanceTimersByTime(20000);
  expect(replace).not.toHaveBeenCalled(); expect(window.document.getElementById('root')!.textContent).toBe('An unsaved draft');
});
it('offers a manual retry after 15 seconds without an automatic reload loop', () => {
  const { window, replace } = boot(); vi.advanceTimersByTime(15000);
  expect(window.document.querySelector('[role="alert"]')!.textContent).toContain('taking longer'); expect(window.document.querySelector('[role="alert"] a')).not.toBeNull(); vi.advanceTimersByTime(60000); expect(replace).not.toHaveBeenCalled();
});
it('keeps one curtain through intermediate loaders and reveals only the ready page', async () => {
  boot();
  const root = document.getElementById('root')!;
  const curtain = document.querySelector('[data-offerpath-startup]')!;
  expect(curtain.parentElement).toBe(document.body);
  expect(root.hasAttribute('inert')).toBe(true);
  for (const html of ['<div class="login-pending">Sign in</div>', '<div class="loading-state">Workspace</div>', '<nav>Navigation</nav><div class="loading-state">Dashboard</div>']) {
    root.innerHTML = html;
    await Promise.resolve(); vi.advanceTimersByTime(300);
    expect(curtain.isConnected).toBe(true);
    expect(root.hasAttribute('inert')).toBe(true);
  }
  root.innerHTML = '<main>Dashboard ready</main>';
  await Promise.resolve(); vi.advanceTimersByTime(180);
  expect(root.hasAttribute('inert')).toBe(false);
  vi.advanceTimersByTime(220);
  expect(curtain.isConnected).toBe(false);
});
it('cancels reveal when another loading phase starts before the page settles', async () => {
  boot(); const root = document.getElementById('root')!;
  root.innerHTML = '<nav>Shell</nav>'; await Promise.resolve(); vi.advanceTimersByTime(100);
  root.innerHTML += '<div class="loading-state">Page query</div>'; await Promise.resolve(); vi.advanceTimersByTime(500);
  expect(root.hasAttribute('inert')).toBe(true);
  expect(document.querySelector('[data-offerpath-startup]')).not.toBeNull();
});
it('ignores HTML whitespace when deciding whether the app has mounted', async () => {
  const {fail,replace}=boot();
  document.getElementById('root')!.append(document.createTextNode('\n    \n'));
  await Promise.resolve();fail();
  expect(replace).toHaveBeenCalledTimes(1);
});
it('keeps a manual recovery available if React mounts but initial loading stalls', async () => {
  const {replace}=boot();
  document.getElementById('root')!.innerHTML='<div class="loading-state">Waiting for a page module</div>';
  await Promise.resolve();vi.advanceTimersByTime(15000);
  const alert=document.querySelector('[data-offerpath-startup][role="alert"]');
  expect(alert?.textContent).toContain('taking longer');
  alert!.querySelector('a')!.click();
  expect(replace).toHaveBeenCalledTimes(1);
});
it('reveals the ready page when loading finishes through a class change', async () => {
  boot();const root=document.getElementById('root')!;
  root.innerHTML='<div class="loading-state">Dashboard</div>';
  await Promise.resolve();root.firstElementChild!.className='ready';
  await Promise.resolve();vi.advanceTimersByTime(400);
  expect(root.hasAttribute('inert')).toBe(false);
  expect(document.querySelector('[data-offerpath-startup]')).toBeNull();
});
it('does not postpone reveal indefinitely when a ready page updates frequently', async () => {
  boot();const root=document.getElementById('root')!;
  root.innerHTML='<main>Dashboard ready</main>';
  await Promise.resolve();
  for(let n=0;n<6;n++){
    vi.advanceTimersByTime(70);root.firstElementChild!.textContent='Update '+n;await Promise.resolve();
  }
  expect(root.hasAttribute('inert')).toBe(false);
});
it('reveals a page that finishes after the slow-start warning without requiring a reload', async () => {
  const {replace}=boot();const root=document.getElementById('root')!;
  root.innerHTML='<div class="loading-state">Waiting</div>';
  await Promise.resolve();vi.advanceTimersByTime(15000);
  expect(document.querySelector('[data-offerpath-startup][role="alert"]')).not.toBeNull();
  root.innerHTML='<main>Finally ready</main>';
  await Promise.resolve();vi.advanceTimersByTime(400);
  expect(root.hasAttribute('inert')).toBe(false);
  expect(document.querySelector('[data-offerpath-startup]')).toBeNull();
  expect(replace).not.toHaveBeenCalled();
});
