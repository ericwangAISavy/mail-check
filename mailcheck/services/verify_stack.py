"""Read-only verification of the isolated local foundation, never a cutover gate."""
import argparse
import json
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError


class VerificationFailed(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check_stack(base_url, *, fetch=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.port != 52500 or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use the isolated loopback foundation on port 52500.')
    if fetch is None:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        def fetch(path):
            try:
                response = opener.open(base_url.rstrip('/') + path, timeout=8)
            except HTTPError as error:
                response = error
            with response:
                body = response.read(16385)
                if len(body) > 16384:
                    raise VerificationFailed('Health response exceeds size limit.')
                return response.status, json.loads(body) if body else {}
    try:
        if fetch('/platform/live')[0] != 204:
            raise VerificationFailed('Edge liveness failed.')
        for role in ('core', 'mail', 'intelligence'):
            paths = [f'/platform/{role}/dependencies']
            if role == 'core':
                paths.append('/platform/core/live')
            for path in paths:
                status, body = fetch(path)
                if (status != 200 or body.get('service') != role
                        or body.get('phase') != 'foundation' or body.get('business_ready') is not False
                        or ('dependencies' in path and body.get('infrastructure_ready') is not True)):
                    raise VerificationFailed('Service health contract failed.')
        status, body = fetch('/api/bootstrap')
        if status != 503 or body.get('code') != 'migration_not_ready':
            raise VerificationFailed('Unmigrated route was incorrectly enabled.')
    except VerificationFailed:
        raise
    except Exception:
        raise VerificationFailed('Foundation is unavailable or returned an invalid response.') from None
    return {'infrastructure_ready': True, 'business_ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:52500')
    args = parser.parse_args()
    try:
        print(json.dumps(check_stack(args.base_url)))
    except (ValueError, VerificationFailed) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
