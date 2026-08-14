#   src/config.py

# --- Imports ---
import os
from pathlib import Path
from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()

GH_TOKEN = os.getenv("GH_TOKEN")
GH_USERNAME = os.getenv("GH_USERNAME")
GH_PASSWORD = os.getenv("GH_PASSWORD")
GH_TOTP_SECRET = os.getenv("GH_TOTP_SECRET")
PINTEREST_SOURCE_BOARD = os.getenv("PINTEREST_SOURCE_BOARD")
PROFILE_PICTURE_DIR = Path(os.getenv("PROFILE_PICTURE_DIR") or "assets/profile_pictures")
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE") or "512")