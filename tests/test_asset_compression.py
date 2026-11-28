"""Text assets are gzip-compressed for slow tunnel hops; others pass through untouched."""
import gzip

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mailcheck.web.static_files import CompressedStaticFiles, PortableStaticFiles


def client_for(tmp_path):
    script = ('export const message = "' + 'x' * 5000 + '";\n').encode()
    (tmp_path / 'index-abc.js').write_bytes(script)
    (tmp_path / 'index-abc.css').write_text('body{color:red}' * 400)
    (tmp_path / 'mark.png').write_bytes(b'\x89PNG' + b'\0' * 4000)
    (tmp_path / 'tiny.js').write_text('1')
    app = FastAPI()
    app.mount('/assets', CompressedStaticFiles(PortableStaticFiles(directory=tmp_path)), name='assets')
    return TestClient(app), script


def test_scripts_and_styles_are_gzipped_and_intact(tmp_path):
    client, script = client_for(tmp_path)
    response = client.get('/assets/index-abc.js', headers={'Accept-Encoding': 'gzip'})
    assert response.status_code == 200
    assert response.headers['content-encoding'] == 'gzip'
    assert 'accept-encoding' in response.headers['vary'].lower()
    assert response.content == script  # the client decodes; bytes match the file exactly
    css = client.get('/assets/index-abc.css', headers={'Accept-Encoding': 'gzip'})
    assert css.headers['content-encoding'] == 'gzip'


def test_compression_actually_shrinks_the_transfer(tmp_path):
    client, script = client_for(tmp_path)
    with client.stream('GET', '/assets/index-abc.js', headers={'Accept-Encoding': 'gzip'}) as response:
        wire = b''.join(response.iter_raw())
    assert len(wire) < len(script) / 3
    assert gzip.decompress(wire) == script


def test_images_tiny_files_ranges_and_plain_clients_are_untouched(tmp_path):
    client, script = client_for(tmp_path)
    assert 'content-encoding' not in client.get('/assets/mark.png', headers={'Accept-Encoding': 'gzip'}).headers
    assert 'content-encoding' not in client.get('/assets/tiny.js', headers={'Accept-Encoding': 'gzip'}).headers
    ranged = client.get('/assets/index-abc.js', headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-9'})
    assert ranged.status_code == 206 and 'content-encoding' not in ranged.headers
    assert ranged.content == script[:10]
    plain = client.get('/assets/index-abc.js', headers={'Accept-Encoding': 'identity'})
    assert 'content-encoding' not in plain.headers and plain.content == script


def test_missing_assets_still_return_404(tmp_path):
    client, _ = client_for(tmp_path)
    assert client.get('/assets/missing.js', headers={'Accept-Encoding': 'gzip'}).status_code == 404
