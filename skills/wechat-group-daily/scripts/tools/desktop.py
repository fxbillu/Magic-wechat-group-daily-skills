"""Install the Magic desktop shortcut or open its existing reader."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from wechat_data.desktop import main

if __name__ == '__main__':
    sys.exit(main())
