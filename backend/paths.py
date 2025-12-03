import os
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    BASE_DIR = Path(
        os.path.expanduser("~/Library/Application Support/Democratized")
        if hasattr(sys, "_MEIPASS")
        else os.path.dirname(os.path.abspath(__file__))
    )
else:
    BASE_DIR = Path(
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Democratized")
        if hasattr(sys, "_MEIPASS")
        else os.path.dirname(os.path.abspath(__file__))
    )
