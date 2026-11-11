"""A private diagnostic must never follow redirects to unvalidated destinations."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.error import HTTPError
import pytest
from mailcheck.services.preflight import _model_snapshot


@contextmanager
def redirecting_model():
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path=='/api/ps':
                self.send_response(302)
                self.send_header('Location','/unvalidated-destination')
                self.end_headers()
            else:
                self.send_response(200);self.end_headers();self.wfile.write(b'{"models":[]}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',requests
    finally:server.shutdown();server.server_close();thread.join(2)


def test_model_snapshot_does_not_follow_redirects():
    with redirecting_model() as (url,requests):
        with pytest.raises(HTTPError) as error:_model_snapshot(url)
        assert error.value.code==302
        assert requests==['/api/ps']


@pytest.mark.parametrize('url',['http://127.0.0.1/private','http://127.0.0.1:invalid','http://127.0.0.1:0'])
def test_model_snapshot_rejects_invalid_server_roots_before_connecting(url):
    with pytest.raises(ValueError):_model_snapshot(url)
