#!/usr/bin/env python3
"""兼容入口：导出 maintenance.reconcile_project_docs。"""

from maintenance.reconcile_project_docs import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
