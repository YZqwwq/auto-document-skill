#!/usr/bin/env python3
"""兼容入口：导出 analysis.scan_project_tree。"""

from analysis.scan_project_tree import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
