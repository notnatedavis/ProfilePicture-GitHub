#   src/image_selector.py

# --- Imports ---
import logging
import config
import pinterest_api
import logging_config

logger = logging.getLogger(__name__)


def select_image() :
    # select a profile picture source from the configured Pinterest board.
    # no longer falls back to local images; 
    # expected to use a public Pinterest board as only image source
    if not config.PINTEREST_SOURCE_BOARD :
        raise RuntimeError(
            "PINTEREST_SOURCE_BOARD is not set. "
            "Please configure it in GitHub Actions variables or in your local .env file."
        )

    board_data = pinterest_api.fetch_board_data(config.PINTEREST_SOURCE_BOARD)
    images = board_data.get("pinImages", [])
    if not images :
        raise RuntimeError("No pin images found in the Pinterest board.")

    url = pinterest_api.get_random_pin_image(images)
    logger.info(logging_config.label_value("Selected Pinterest image", url))
    return url