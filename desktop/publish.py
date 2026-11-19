"""Publish the built desktop installer as a GitHub release that auto-update can see.

Usage (after `npm run dist`, with the version's commit pushed):
    python publish.py --note "What changed" [--note "..."]

Creates release desktop-v<version> at the pushed HEAD, marks it "Latest", and
uploads the installer, its blockmap and latest.yml. Installed apps read
latest.yml from the Latest release, so all three files are required.
Uses the GitHub sign-in already stored for git (git credential helper).
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "ericwangAISavy/mail-check"
API = f"https://api.github.com/repos/{REPO}"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def token():
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)["password"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--note", action="append", required=True, help="User-facing change (repeatable)")
    args = parser.parse_args()

    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    tag = f"desktop-v{version}"
    files = [ROOT / "dist" / name for name in
             (f"OfferPath-Setup-{version}.exe", f"OfferPath-Setup-{version}.exe.blockmap", "latest.yml")]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        sys.exit(f"Missing build output {missing}; run `npm run dist` first.")
    if f"version: {version}" not in (ROOT / "dist" / "latest.yml").read_text(encoding="utf-8"):
        sys.exit("dist/latest.yml is from another version; run `npm run dist` again.")
    if git("status", "--porcelain", "--", "."):
        sys.exit("desktop/ has uncommitted changes; commit and push them first.")
    head = git("rev-parse", "HEAD")
    git("fetch", "-q", "origin")
    if not git("branch", "-r", "--contains", head):
        sys.exit("HEAD is not pushed; push it first so the release tag points at published code.")

    headers = {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
               "User-Agent": "offerpath-desktop-release", "X-GitHub-Api-Version": "2022-11-28"}

    def call(method, url, body=None, content_type="application/json"):
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={**headers, "Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            if method == "GET" and error.code == 404:
                return None
            sys.exit(f"{method} {url} -> {error.code}: {error.read().decode()[:400]}")

    if call("GET", f"{API}/releases/tags/{tag}"):
        sys.exit(f"Release {tag} already exists; raise the version in package.json first.")
    notes = "\n".join(f"- {note}" for note in args.note) + f"""

**Install:** download `OfferPath-Setup-{version}.exe` and run it. Installed copies update automatically. \
The installer is not code-signed yet, so Windows SmartScreen may warn: choose **More info → Run anyway**."""
    release = call("POST", f"{API}/releases", {
        "tag_name": tag, "target_commitish": head, "name": f"OfferPath Desktop {version}",
        "body": notes, "draft": True, "prerelease": False})
    upload = release["upload_url"].split("{")[0]
    for file in files:
        asset = call("POST", f"{upload}?name={urllib.parse.quote(file.name)}", file.read_bytes(),
                     "application/octet-stream")
        print("uploaded", asset["name"], asset["size"])
    # Publish only once every file is attached, so no app sees a half-uploaded update.
    release = call("PATCH", f"{API}/releases/{release['id']}", {"draft": False, "make_latest": "true"})
    print(release["html_url"])


if __name__ == "__main__":
    main()
