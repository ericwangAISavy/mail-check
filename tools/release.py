"""Maintain OfferPath versions and readable release history (standard library only)."""
from __future__ import annotations
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def version_tuple(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError(f"Invalid release version: {value!r}")
    return tuple(map(int, value.split('.')))


def history(root):
    releases = json.loads((root/'releases.json').read_text(encoding='utf-8'))
    if not isinstance(releases, list) or not releases:
        raise ValueError('Release history must be a nonempty list.')
    previous = None
    for entry in releases:
        current = version_tuple(entry['version'])
        if previous is not None and current >= previous:
            raise ValueError('Release versions must be unique and newest first.')
        previous = current
        date.fromisoformat(entry['date'])
        if not isinstance(entry['title'], str) or not entry['title'].strip():
            raise ValueError('Every release needs a title.')
        if not isinstance(entry['changes'], list) or not entry['changes'] or any(not isinstance(note, str) or not note.strip() for note in entry['changes']):
            raise ValueError('Every release needs readable change notes.')
    return releases


def changelog(releases):
    text = '# OfferPath version history\n\nGenerated from releases.json. Use tools/release.py to add a release.\n'
    for entry in releases:
        text += f"\n## {entry['version']} — {entry['date']}\n\n{entry['title']}\n\n"
        text += ''.join(f'- {note}\n' for note in entry['changes'])
    return text


def git(root, *arguments):
    result = subprocess.run(['git', *arguments], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Git release comparison failed.')
    return result.stdout


def check(root=ROOT, base=None):
    releases = history(root)
    version = releases[0]['version']
    pyproject = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))
    runtime = re.search(r'^__version__ = "([^"]+)"', (root/'mailcheck/__init__.py').read_text(encoding='utf-8'), re.M)
    package = json.loads((root/'frontend/package.json').read_text(encoding='utf-8'))
    lock = json.loads((root/'frontend/package-lock.json').read_text(encoding='utf-8'))
    versions = [pyproject['project']['version'], runtime.group(1) if runtime else None,
                package['version'], lock['version'], lock['packages']['']['version']]
    if any(value != version for value in versions):
        raise ValueError('Release, Python, frontend, and lockfile versions must match.')
    if (root/'docs/CHANGELOG.md').read_text(encoding='utf-8') != changelog(releases):
        raise ValueError('docs/CHANGELOG.md is out of date. Regenerate it with the release tool.')
    if base and set(base) != {'0'}:
        git(root, 'rev-parse', '--verify', base+'^{commit}')
        exists = subprocess.run(['git','cat-file','-e',base+':releases.json'], cwd=root, capture_output=True)
        if not exists.returncode:
            before = json.loads(git(root, 'show', base+':releases.json'))
            changed = git(root, 'diff', '--name-only', base, '--').splitlines()
            runtime_changed = any(path.startswith(('mailcheck/','frontend/src/','tools/')) or path in (
                'pyproject.toml','frontend/package.json','frontend/package-lock.json') for path in changed)
            if runtime_changed and version_tuple(version) <= version_tuple(before[0]['version']):
                raise ValueError('Runtime changes require a version bump and release notes. Run tools/release.py patch or minor.')
            if any(entry not in releases for entry in before):
                raise ValueError('Previously published release notes must be retained unchanged.')


def bump(root, kind, title, notes, released_on=None):
    check(root)
    if not title or not title.strip() or not notes or any(not note.strip() for note in notes):
        raise ValueError('A release title and at least one change note are required.')
    releases = history(root)
    major, minor, patch = version_tuple(releases[0]['version'])
    if kind == 'major': major, minor, patch = major+1, 0, 0
    elif kind == 'minor': minor, patch = minor+1, 0
    elif kind == 'patch': patch += 1
    else: raise ValueError('Choose major, minor, or patch.')
    stamp = released_on or datetime.now(ZoneInfo('America/Chicago')).date().isoformat()
    date.fromisoformat(stamp)
    version = f'{major}.{minor}.{patch}'
    releases.insert(0, {'version':version, 'date':stamp, 'title':title.strip(), 'changes':[note.strip() for note in notes]})
    files = {'releases.json':json.dumps(releases, indent=2, ensure_ascii=False)+'\n', 'docs/CHANGELOG.md':changelog(releases)}
    files['pyproject.toml'] = re.sub(r'^version = "[^"]+"', f'version = "{version}"', (root/'pyproject.toml').read_text(encoding='utf-8'), count=1, flags=re.M)
    files['mailcheck/__init__.py'] = re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{version}"', (root/'mailcheck/__init__.py').read_text(encoding='utf-8'), count=1, flags=re.M)
    for name in ('frontend/package.json','frontend/package-lock.json'):
        data = json.loads((root/name).read_text(encoding='utf-8'))
        data['version'] = version
        if name.endswith('package-lock.json'): data['packages']['']['version'] = version
        files[name] = json.dumps(data, indent=2, ensure_ascii=False)+'\n'
    for name, content in files.items():
        (root/name).write_text(content, encoding='utf-8')
    check(root)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', nargs='?', choices=('patch','minor','major'))
    parser.add_argument('--title')
    parser.add_argument('--note', action='append', default=[])
    parser.add_argument('--date')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--base', help='Git revision to check for unversioned runtime changes')
    args = parser.parse_args()
    try:
        if args.check:
            check(ROOT, args.base)
            print('Release versions and update history are consistent.')
        elif args.kind:
            print('OfferPath '+bump(ROOT, args.kind, args.title, args.note, args.date))
        else:
            parser.error('Choose patch/minor/major or --check.')
    except (ValueError,KeyError,OSError) as exc:
        parser.exit(1, f'Release check failed: {exc}\n')


if __name__ == '__main__':
    main()
