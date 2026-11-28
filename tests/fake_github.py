"""A fake GitHub (releases API + asset downloads) for the update tests: no network."""
import hashlib
import io
import json
import os
import time
import zipfile

from gme import updater

CDN = "https://objects.githubusercontent.com/github-production-release-asset/"


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, delay=0.0, chunk=64 << 10):
        self.status_code, self.body, self.headers = status, body, headers or {}
        self.delay, self.chunk, self.closed = delay, chunk, False

    def iter_content(self, size=None):
        step = self.chunk
        for i in range(0, len(self.body), step):
            if self.delay:
                time.sleep(self.delay)
            yield self.body[i:i + step]

    def close(self):
        self.closed = True


class FakeGitHub:
    """Callable used in place of ``updater._get``."""

    def __init__(self, version="9.9.0", exe=None, sums=True, sums_text=None, zip_bytes=None,
                 notes="## Nouveautés\n- Mise à jour automatique\n- **Vidéo** de démo",
                 prerelease=False, delay=0.0, asset_urls=None, api_status=200):
        self.version, self.tag = version, "v" + version
        self.exe = exe if exe is not None else b"MZ" + os.urandom(400_000)
        self.zip = zip_bytes if zip_bytes is not None else make_zip({updater.EXE_NAME: self.exe, "README.txt": b"x"})
        name = updater.zip_name(version)
        digest = hashlib.sha256(self.zip).hexdigest()
        self.sums_text = sums_text if sums_text is not None else f"{digest}  {name}\n{'0' * 64}  other.zip\n"
        self.calls, self.delay, self.api_status = [], delay, api_status
        base = f"{updater.DOWNLOAD_PREFIX}{self.tag}/"
        urls = asset_urls or {}
        assets = [{"name": name, "size": len(self.zip), "browser_download_url": urls.get(name, base + name)}]
        if sums:
            assets.append({"name": updater.SUMS_NAME, "size": len(self.sums_text),
                           "browser_download_url": urls.get(updater.SUMS_NAME, base + updater.SUMS_NAME)})
        self.release = {"tag_name": self.tag, "name": "Gamelist Media Editor " + self.tag, "draft": False,
                        "prerelease": prerelease, "body": notes, "published_at": "2026-12-01T10:00:00Z",
                        "html_url": f"https://github.com/{updater.REPO}/releases/tag/{self.tag}",
                        "assets": assets}
        self.routes = {
            updater.API_LATEST: lambda: FakeResponse(self.api_status, json.dumps(self.release).encode()),
            base + name: lambda: FakeResponse(302, headers={"Location": CDN + "zip"}),
            CDN + "zip": lambda: FakeResponse(200, self.zip, delay=self.delay, chunk=16 << 10),
            base + updater.SUMS_NAME: lambda: FakeResponse(302, headers={"Location": CDN + "sums"}),
            CDN + "sums": lambda: FakeResponse(200, self.sums_text.encode()),
        }

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        assert kwargs.get("allow_redirects") is False and kwargs.get("timeout")
        route = self.routes.get(url)
        return route() if route else FakeResponse(404)
