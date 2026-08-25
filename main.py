"""
main.py - WayneBot Phase 10 生產環境統一啟動入口
"""

import sys
from main_runner import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[WayneBot] 收到使用者中斷信號，安全退出。")
        sys.exit(0)
