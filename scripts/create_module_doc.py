#!/usr/bin/env python3
"""兼容入口：导出 generation.create_module_doc。"""

from generation.create_module_doc import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
