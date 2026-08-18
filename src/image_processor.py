#   src/image_processor.py

# --- Imports ---
import logging
from io import BytesIO
from pathlib import Path
import requests
from PIL import Image, ImageChops
import config
import logging_config

logger = logging.getLogger(__name__)

def load_image(source) :
    # load an image from either a URL or a local file path
    source = str(source)  # accept Path objects and strings
    if source.startswith(("http://", "https://")):
        logger.debug(logging_config.label_value("Downloading image from", source))
        resp = requests.get(source, timeout=15)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content))
    logger.debug(logging_config.label_value("Opening local image", source))
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

def image_similarity(img_a, img_b) :
    # return a similarity score between 0.0 and 1.0, where 1.0 means identical
    # the score is based on the percentage of pixels that differ
    # ensure both images have the same size for comparison
    if img_a.size != img_b.size :
        img_a = img_a.resize((config.IMAGE_SIZE, config.IMAGE_SIZE))
        img_b = img_b.resize((config.IMAGE_SIZE, config.IMAGE_SIZE))

    # convert both to RGB to avoid mode mismatches
    img_a_rgb = img_a.convert("RGB")
    img_b_rgb = img_b.convert("RGB")

    # fast path for exact pixel-identical images
    diff = ImageChops.difference(img_a_rgb, img_b_rgb)
    if diff.getbbox() is None :
        return 1.0

    # compute the percentage of pixels that differ
    diff_gray = diff.convert("L")  # any channel difference becomes non-zero
    total_pixels = img_a_rgb.width * img_a_rgb.height
    differing_pixels = sum(1 for p in diff_gray.getdata() if p != 0)
    differing_fraction = differing_pixels / total_pixels
    return 1.0 - differing_fraction

def images_equal(img_a, img_b, confidence=1.0) :
    # return True when two images are considered equal according to the confidence level
    # confidence=1.0 means exact pixel match; lower values allow more difference
    # the comparison uses the percentage of differing pixels
    if not 0.0 <= confidence <= 1.0 :
        raise ValueError("confidence must be between 0.0 and 1.0")

    # calculate similarity score between the two images
    similarity = image_similarity(img_a, img_b)

    # log the comparison metrics for live debugging
    logger.info(
        "Image comparison: similarity=%.2f%%, required=%.2f%%",
        similarity * 100,
        confidence * 100
    )

    return similarity >= confidence

def save_image(img, path) :
    # save the processed image as PNG
    img.save(path, format="PNG")