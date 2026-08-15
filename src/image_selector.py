#   src/image_selector.py

# --- Imports ---
import random
import logging
from pathlib import Path
import config
import pinterest_api

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _get_local_images() :
    # return all local image files in the configured profile picture directory."""
    if not config.PROFILE_PICTURE_DIR.exists():
        return []
    return [
        p for p in config.PROFILE_PICTURE_DIR.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

def select_image() :
    # select a profile picture source

    # if PINTEREST_SOURCE_BOARD is set, fetch a random pin image from that board
    # else (or if Pinterest fails), fall back to local images
    
    # returns a URL string (for Pinterest) or a file path (for local)
    if config.PINTEREST_SOURCE_BOARD :
        try :
            board_data = pinterest_api.fetch_board_data(config.PINTEREST_SOURCE_BOARD)
            images = board_data.get("pinImages", [])
            if images :
                url = pinterest_api.get_random_pin_image(images)
                logger.info("Selected Pinterest image: %s", url)
                return url
        except Exception as err :
            logger.warning("Pinterest selection failed, falling back to local: %s", err)

    local_images = _get_local_images()
    if not local_images :
        raise RuntimeError(
            "No local profile pictures found in "
            f"{config.PROFILE_PICTURE_DIR} and Pinterest selection failed."
        )
    selected = random.choice(local_images)
    logger.info("Selected local image: %s", selected)
    return str(selected)