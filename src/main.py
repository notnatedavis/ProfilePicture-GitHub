#   src/main.py

# --- Imports ---
import logging
import tempfile
from pathlib import Path
import config
import image_selector
import image_processor
import github_client

def main() :
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting profile picture update")

    tmp_path = None
    try :
        source = image_selector.select_image()
        logger.info("Selected image source: %s", source)

        img = image_processor.load_image(source)
        processed = image_processor.process_image(img)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp :
            tmp_path = Path(tmp.name)
        image_processor.save_image(processed, tmp_path)
        logger.info("Processed image saved to %s", tmp_path)

        github_client.update_avatar(tmp_path)
        logger.info("Profile picture update completed")

    except Exception as err :
        logger.exception("Profile picture update failed: %s", err)
        raise
    finally :
        if tmp_path and tmp_path.exists() :
            tmp_path.unlink()
            logger.debug("Cleaned up temporary file %s", tmp_path)


if __name__ == "__main__" :
    main()