#   src/web_uploader.py

# --- Imports ---
import logging
import os
import time
from pathlib import Path

import pyotp
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config

logger = logging.getLogger(__name__)

# --- URLs ---
GITHUB_LOGIN_URL = "https://github.com/login"
GITHUB_DASHBOARD_URL = "https://github.com/"
GITHUB_SETTINGS_PROFILE_URL = "https://github.com/settings/profile"
TWO_FACTOR_URL_PATTERN = "**/sessions/two-factor*"
CHALLENGE_URL_PATTERNS = [
    "**/sessions/verify*",          # Verify your account
    "**/sessions/device*",          # Device verification
    "**/sessions/phone*",           # Phone verification
]

# --- Coordinate fallbacks (fill in manually if automatic selectors fail) ---
# These are (x, y) coordinates on the page. Use DEBUG_PW=1 to find them.
COORD_EDIT_BUTTON = (100, 200) # Click on the avatar edit button
COORD_UPLOAD_MENU = (150, 300) # Click on "Upload a photo…" menu item
COORD_SAVE_BUTTON = (200, 400) # Click on "Set new profile picture"


def _generate_totp_code():
    """Generate a time-based one-time password for GitHub 2FA."""
    if not config.GH_TOTP_SECRET:
        return None
    try:
        return pyotp.TOTP(config.GH_TOTP_SECRET).now()
    except Exception as err:
        logger.warning("Failed to generate TOTP code: %s", err)
        return None


def _is_debug_mode():
    """Return True if DEBUG_PW environment variable is set to a truthy value."""
    return os.getenv("DEBUG_PW", "").lower() in ("1", "true", "yes")


def _save_debug_artifacts(page, prefix="failure"):
    """
    Save a screenshot and the page HTML to the current working directory.
    Useful for debugging both locally and in GitHub Actions.
    """
    timestamp = int(time.time())
    screenshot_path = f"{prefix}_{timestamp}.png"
    html_path = f"{prefix}_{timestamp}.html"
    try:
        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.info("Debug artifacts saved: %s and %s", screenshot_path, html_path)
    except Exception as e:
        logger.warning("Could not save debug artifacts: %s", e)


def _handle_challenges(page):
    """
    Detect and attempt to dismiss common security challenges.
    Returns True if we are successfully logged in and not stuck on a challenge page.
    """
    # Wait for the page to settle
    page.wait_for_load_state("networkidle")

    # If we are back at login, authentication failed
    if "/login" in page.url:
        logger.error("Redirected back to login page – authentication failed.")
        return False

    # If we are on the dashboard or settings, we are good
    if page.url.rstrip("/") in (GITHUB_DASHBOARD_URL.rstrip("/"), GITHUB_SETTINGS_PROFILE_URL.rstrip("/")):
        logger.debug("Logged in successfully (dashboard or settings).")
        return True

    # Known challenge pages
    for pattern in CHALLENGE_URL_PATTERNS:
        if pattern.replace("**", "") in page.url:
            logger.info("Detected challenge page: %s", page.url)

            # Try to click any button with text "Skip", "Continue", "Verify", etc.
            buttons = page.locator(
                "button:has-text('Skip'), "
                "button:has-text('Continue'), "
                "button:has-text('Verify'), "
                "button:has-text('Next'), "
                "button:has-text('Send'), "
                "button:has-text('Confirm')"
            )
            try:
                buttons.first.click(timeout=5000)
                # Wait for navigation away from challenge
                page.wait_for_url(
                    lambda url: "/login" not in url,
                    timeout=10000,
                )
                # Re-check after navigation
                return _handle_challenges(page)
            except PlaywrightTimeoutError:
                logger.warning("Could not automatically dismiss challenge.")

            # If we couldn't dismiss, we cannot proceed.
            logger.error("Manual intervention required for challenge: %s", page.url)
            return False

    # Unknown page – try to navigate to dashboard as a fallback
    logger.warning("Unknown page after login: %s – attempting to go to dashboard", page.url)
    try:
        page.goto(GITHUB_DASHBOARD_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        return _handle_challenges(page)
    except Exception:
        return False


def _login(page):
    """Sign in to GitHub using username/password, handle 2FA and security challenges."""
    if not config.GH_USERNAME or not config.GH_PASSWORD:
        raise RuntimeError("GH_USERNAME and GH_PASSWORD must be set for browser automation.")

    # Go to login page
    page.goto(GITHUB_LOGIN_URL, wait_until="domcontentloaded")
    page.fill("#login_field", config.GH_USERNAME)
    page.fill("#password", config.GH_PASSWORD)
    page.click("input[type='submit']")

    # Wait for possible 2FA
    try:
        page.wait_for_url(TWO_FACTOR_URL_PATTERN, timeout=5000)
        totp = _generate_totp_code()
        if not totp:
            raise RuntimeError("GitHub requires 2FA, but no GH_TOTP_SECRET was provided.")
        page.fill("#app_totp", totp)
        page.click("button[type='submit']")
        # After 2FA, wait for the page to settle
        page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        logger.debug("No 2FA challenge detected")

    # Now handle any post-login challenges
    if not _handle_challenges(page):
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(
            "Failed to complete login. A security challenge may require manual action. "
            "Check the saved debug artifacts (screenshot and HTML) for more details."
        )

    # Final verification: we should be on dashboard or settings
    if "/login" in page.url:
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(f"Login failed. Current URL: {page.url}")

    logger.debug("Successfully authenticated and reached %s", page.url)


def _upload_profile_picture(page, image_path):
    """
    Navigate directly to settings and upload the profile picture.
    Uses role-based clicks first; falls back to manual coordinates if needed.
    """
    # Always go directly to the settings page – skip the user menu entirely
    page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    # Wait for the avatar element to ensure page is fully rendered
    try:
        page.wait_for_selector("img.avatar", timeout=15000)
    except PlaywrightTimeoutError:
        _save_debug_artifacts(page, "settings_load_failure")
        raise RuntimeError(
            f"Settings page did not load properly. Current URL: {page.url}. "
            "Check debug artifacts for details."
        )

    # --- Click the avatar edit button ---
    username = config.GH_USERNAME
    edit_button_name = f"@{username} Edit"
    try:
        logger.debug(f"Clicking avatar edit button: {edit_button_name}")
        page.get_by_role("button", name=edit_button_name).click(timeout=10000)
    except PlaywrightTimeoutError:
        logger.warning("Role-based click on edit button failed – trying coordinate fallback.")
        try:
            x, y = COORD_EDIT_BUTTON
            page.mouse.click(x, y)
            logger.debug(f"Clicked edit button at coordinates ({x}, {y})")
        except Exception as e:
            _save_debug_artifacts(page, "edit_button_failure")
            raise RuntimeError(f"Failed to click avatar edit button: {e}")

    # --- Click the "Upload a photo…" menu item ---
    try:
        logger.debug("Clicking 'Upload a photo…' menu item")
        page.get_by_role("menuitem", name="Upload a photo…").click(timeout=5000)
    except PlaywrightTimeoutError:
        logger.warning("Role-based click on upload menu failed – trying coordinate fallback.")
        try:
            x, y = COORD_UPLOAD_MENU
            page.mouse.click(x, y)
            logger.debug(f"Clicked upload menu at coordinates ({x}, {y})")
        except Exception as e:
            _save_debug_artifacts(page, "upload_menu_failure")
            raise RuntimeError(f"Failed to click 'Upload a photo…' menu item: {e}")

    # --- Set the input file (using label) ---
    try:
        logger.debug(f"Setting input file: {image_path}")
        page.get_by_label("Upload a photo…").set_input_files(str(image_path))
    except Exception as e:
        _save_debug_artifacts(page, "file_input_failure")
        raise RuntimeError(f"Failed to set input file: {e}")

    # --- Click the "Set new profile picture" button ---
    try:
        logger.debug("Clicking 'Set new profile picture' button")
        page.get_by_role("button", name="Set new profile picture").click(timeout=10000)
        page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        logger.warning("Role-based click on save button failed – trying coordinate fallback.")
        try:
            x, y = COORD_SAVE_BUTTON
            page.mouse.click(x, y)
            logger.debug(f"Clicked save button at coordinates ({x}, {y})")
            page.wait_for_load_state("networkidle")
        except Exception as e:
            _save_debug_artifacts(page, "save_button_failure")
            raise RuntimeError(f"Failed to click 'Set new profile picture' button: {e}")

    logger.info("Profile picture uploaded through GitHub web UI")


def upload_avatar(image_path):
    """Launch a browser, sign in, and upload the avatar image."""
    if not Path(image_path).exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    debug_mode = _is_debug_mode()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not debug_mode,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            if debug_mode:
                logger.info("Running in debug mode – browser window will appear.")
            _login(page)
            _upload_profile_picture(page, image_path)
        except Exception as e:
            try:
                _save_debug_artifacts(page, "error")
            except Exception:
                pass
            raise e
        finally:
            if debug_mode:
                logger.info("Debug mode: browser will close in 30 seconds. Press Ctrl+C to abort.")
                time.sleep(30)
            browser.close()