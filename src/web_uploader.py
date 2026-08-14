#   src/web_uploader.py

# --- Imports ---
import logging
from pathlib import Path

import pyotp
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config

logger = logging.getLogger(__name__)

# --- selectors / URLs ---
GITHUB_LOGIN_URL = "https://github.com/login"
GITHUB_SETTINGS_PROFILE_URL = "https://github.com/settings/profile"
TWO_FACTOR_URL_PATTERN = "**/sessions/two-factor*"


def _generate_totp_code():
    """Generate a time-based one-time password for GitHub 2FA."""
    if not config.GH_TOTP_SECRET:
        return None
    try:
        return pyotp.TOTP(config.GH_TOTP_SECRET).now()
    except Exception as err:
        logger.warning("Failed to generate TOTP code: %s", err)
        return None


def _login(page):
    """Sign in to GitHub using username/password and optional TOTP."""
    if not config.GH_USERNAME or not config.GH_PASSWORD:
        raise RuntimeError("GH_USERNAME and GH_PASSWORD must be set for browser automation.")

    page.goto(GITHUB_LOGIN_URL, wait_until="domcontentloaded")
    page.fill("#login_field", config.GH_USERNAME)
    page.fill("#password", config.GH_PASSWORD)
    page.click("input[type='submit']")

    # Handle 2FA if present
    try:
        page.wait_for_url(TWO_FACTOR_URL_PATTERN, timeout=5000)
        totp = _generate_totp_code()
        if not totp:
            raise RuntimeError("GitHub requires 2FA, but no GH_TOTP_SECRET was provided.")
        page.fill("#app_totp", totp)
        page.click("button[type='submit']")
    except PlaywrightTimeoutError:
        logger.debug("No 2FA challenge detected")

    # Wait until we leave login pages
    page.wait_for_url(
        lambda url: "github.com/login" not in url and "sessions/two-factor" not in url,
        timeout=15000,
    )
    logger.debug("Successfully authenticated with GitHub")


def _is_file_input_visible(page):
    """Check if the file input for avatar upload is present and attached."""
    return page.locator("input[type='file']").count() > 0


def _wait_for_file_input(page, timeout=10000):
    """Wait for the file input to become available."""
    try:
        page.wait_for_selector("input[type='file']", state="attached", timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False


def _try_open_avatar_dialog(page):
    """
    Attempt to open the avatar upload dialog using multiple strategies.
    Returns True if the file input becomes available, False otherwise.
    """
    # Strategy 1: File input might already be present (e.g., after previous actions)
    if _is_file_input_visible(page):
        logger.debug("File input already present")
        return True

    # Strategy 2: Click on the avatar image (most direct)
    try:
        logger.debug("Attempting to click avatar image")
        page.locator("img.avatar").first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Avatar click opened file input")
            return True
    except PlaywrightTimeoutError:
        logger.debug("Avatar click did not open file input")

    # Strategy 3: Try explicit button selectors (aria-label, text, etc.)
    button_selectors = [
        "button[aria-label='Edit profile picture']",
        "button[aria-label='Edit']",
        "button[aria-label='Upload profile picture']",
        "a[aria-label='Edit profile picture']",
        "a[aria-label='Edit']",
        "button:has-text('Edit')",
        "a:has-text('Edit')",
        "button:has(svg)",  # any button with an SVG (likely the pencil icon)
    ]
    for selector in button_selectors:
        try:
            logger.debug(f"Trying button selector: {selector}")
            page.locator(selector).first.click(timeout=5000)
            if _wait_for_file_input(page):
                logger.debug(f"Button selector {selector} opened file input")
                return True
        except PlaywrightTimeoutError:
            continue

    # Strategy 4: Use role-based selector (more semantic)
    try:
        logger.debug("Trying role=button with name 'Edit'")
        page.get_by_role("button", name="Edit").first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Role button 'Edit' opened file input")
            return True
    except PlaywrightTimeoutError:
        pass

    # Strategy 5: Fallback to any element with text "Edit" (loose match)
    try:
        logger.debug("Trying get_by_text('Edit', exact=False)")
        page.get_by_text("Edit", exact=False).first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Text fallback opened file input")
            return True
    except PlaywrightTimeoutError:
        pass

    # If we reach here, we could not open the dialog
    return False


def _upload_profile_picture(page, image_path):
    """Navigate to profile settings and upload the processed image."""
    page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    # Ensure the settings page has loaded properly
    try:
        page.wait_for_selector("img.avatar", timeout=15000)
    except PlaywrightTimeoutError:
        logger.error("Profile settings page did not load. Current URL: %s", page.url)
        raise RuntimeError(f"Failed to load settings page: {page.url}")

    # Try to open the avatar dialog (file input)
    if not _try_open_avatar_dialog(page):
        # Log the current state for debugging
        logger.error("Could not locate avatar upload control on %s", page.url)
        logger.debug("Page HTML snippet: %s", page.content()[:500])
        raise RuntimeError("Unable to open GitHub avatar upload dialog")

    # Now the file input should be available
    file_input = page.locator("input[type='file']").first
    file_input.wait_for(state="attached", timeout=10000)
    file_input.set_input_files(str(image_path))

    # Wait for the crop/save dialog and confirm the upload
    page.wait_for_selector(
        "button:has-text('Set new picture'), button:has-text('Save')",
        timeout=15000,
    )
    save_button = page.locator(
        "button:has-text('Set new picture'), button:has-text('Save')"
    ).first
    save_button.click()

    # Wait for the page to settle after the avatar update
    page.wait_for_load_state("networkidle")
    logger.info("Profile picture uploaded through GitHub web UI")


def upload_avatar(image_path):
    """Launch a browser, sign in, and upload the avatar image."""
    if not Path(image_path).exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            _login(page)
            _upload_profile_picture(page, image_path)
        finally:
            browser.close()