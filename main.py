"""MiniHermes CLI 入口（源码运行快捷方式）。

优先走 src/ 下的包；若已 pip 安装（editable 或 wheel）则由安装路径提供。
"""

import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from minihermes.main import main  # noqa: E402

if __name__ == "__main__":
    main()
