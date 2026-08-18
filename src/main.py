#   src/main.py

# --- Imports ---
import logging
import tempfile
from pathlib import Path
import config
import image_selector
import image_processor
import playwright_upload_github
import logging_config

def main() :
    logging_config.configure_logging()
    logger = logging.getLogger(__name__)

    logger.info(logging_config.block("Starting profile picture update"))

    tmp_path = None
    try :
        source = image_selector.select_image()
        logger.info(logging_config.label_value("Selected image source", source))

        img = image_processor.load_image(source)
        processed = image_processor.process_image(img)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp :
            tmp_path = Path(tmp.name)
        image_processor.save_image(processed, tmp_path)
        logger.info(logging_config.label_value("Processed image saved to", tmp_path, separator=""))

        playwright_upload_github.upload_avatar(tmp_path)
        logger.info("Profile picture update completed")

    except Exception as err :
        logger.exception(logging_config.label_value("Profile picture update failed", err))
        raise
    
    finally :
        if tmp_path and tmp_path.exists() :
            tmp_path.unlink()
            logger.debug(logging_config.label_value("Cleaned up temporary file", tmp_path))


if __name__ == "__main__" :
    main()