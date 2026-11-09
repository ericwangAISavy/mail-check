import source from "../../public/assets/startup-recovery-v1.js?raw";
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
