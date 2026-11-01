"""Do not discover ancestor .env files while importing bundled helper modules."""

import os
from pathlib import Path
import sys

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
# The portable runtime intentionally does not redistribute NVIDIA libraries.
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

node = Path(sys._MEIPASS) / "js" / "node.exe"
if node.is_file():
    import yt_dlp

    original_init = yt_dlp.YoutubeDL.__init__

    def portable_youtube_dl_init(self, params=None, *args, **kwargs):
        parameters = dict(params or {})
        parameters.setdefault("js_runtimes", {"node": {"path": str(node)}})
        original_init(self, parameters, *args, **kwargs)

    yt_dlp.YoutubeDL.__init__ = portable_youtube_dl_init
