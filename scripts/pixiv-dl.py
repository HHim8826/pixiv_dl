"""PyInstaller 的進入點。

不能直接把 src/pixiv_dl/__main__.py 餵給 PyInstaller——它用的是相對匯入
（`from .cli import main`），被當成頂層腳本執行時會 ImportError。
"""

import sys

from pixiv_dl.cli import main

if __name__ == '__main__':
    sys.exit(main())
