#   src/image_processor.py

# --- Imports ---
import logging
from io import BytesIO
from pathlib import Path
import requests
from PIL import Image
import config

logger = logging.getLogger(__name__)

def load_image(source) :
    # load an image from either a URL or a local file path
    if source.startswith(("http://", "https://")):
        logger.debug("Downloading image from %s", source)
        resp = requests.get(source, timeout=15)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content))
    logger.debug("Opening local image %s", source)
    return Image.open(source)
 
def process_image(img) :
    # crop and resize the image to a square of config.IMAGE_SIZE
    img = img.convert("RGB")
    img.thumbnail((config.IMAGE_SIZE, config.IMAGE_SIZE))

    width, height = img.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    right = left + side
    bottom = top + side

    img = img.crop((left, top, right, bottom))
    img = img.resize((config.IMAGE_SIZE, config.IMAGE_SIZE))
    return img

def save_image(img, path) :
    # save the processed image as PNG
    img.save(path, format="PNG")