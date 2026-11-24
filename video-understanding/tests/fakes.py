"""yt-dlp の YoutubeDL の代わり。"""

import io
import shutil
from pathlib import Path


class FakeYdl:
    def __init__(self, opts, *, info, video, captions, calls):
        self.opts, self.info, self.video, self.captions, self.calls = (
            opts,
            info,
            video,
            captions,
            calls,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        self.calls.append(("extract_info", url))
        return self.info

    def urlopen(self, url):
        self.calls.append(("urlopen", url))
        body = self.captions[url]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(body.encode())

    def download(self, urls):
        self.calls.append(("download", urls[0], self.opts["format"]))
        dest = Path(self.opts["outtmpl"].replace("%(ext)s", "mp4"))
        shutil.copy(self.video, dest)


def make_factory(*, info, video, captions=None, calls=None):
    calls = [] if calls is None else calls

    def factory(opts):
        return FakeYdl(opts, info=info, video=video, captions=captions or {}, calls=calls)

    factory.calls = calls
    return factory
