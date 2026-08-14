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
GITHUB_SETTINGS_PROFILE_URL = "https://github.com/settings/profile"
TWO_FACTOR_URL_PATTERN = "**/sessions/two-factor*"
CHALLENGE_URL_PATTERNS = [
    "**/sessions/verify*",          # Verify your account
    "**/sessions/device*",          # Device verification
    "**/sessions/phone*",           # Phone verification
]


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


def _handle_post_login_challenges(page):
    """
    Detect and attempt to dismiss common security challenges after login.
    Returns True if we successfully reached the settings page, False otherwise.
    """
    # Wait for the page to settle after login
    page.wait_for_load_state("networkidle")

    # Check if we are already on the settings page (success)
    if "/settings/profile" in page.url:
        return True

    # Check if we are back at login (failure)
    if "/login" in page.url:
        logger.error("Redirected back to login page – authentication failed.")
        return False

    # Handle 2FA (already handled in _login, but we check again)
    if "two-factor" in page.url:
        logger.warning("2FA page detected after login – possibly not handled.")
        return False

    # Handle known challenge URLs
    for pattern in CHALLENGE_URL_PATTERNS:
        if pattern.replace("**", "") in page.url:
            logger.info("Detected challenge page: %s", page.url)

            # Try to click any button with text "Skip", "Continue", "Verify", etc.
            # These are common for device verification and "new sign-in" prompts.
            buttons = page.locator(
                "button:has-text('Skip'), "
                "button:has-text('Continue'), "
                "button:has-text('Verify'), "
                "button:has-text('Next'), "
                "button:has-text('Send'), "
                "button:has-text('Confirm')"
            )
            try:
                # Click the first visible button
                buttons.first.click(timeout=5000)
                # Wait for navigation away from challenge
                page.wait_for_url(
                    lambda url: "/settings/profile" in url or "/login" not in url,
                    timeout=10000,
                )
                if "/settings/profile" in page.url:
                    return True
            except PlaywrightTimeoutError:
                logger.warning("Could not automatically dismiss challenge.")

            # If we couldn't dismiss, we cannot proceed.
            logger.error("Manual intervention required for challenge: %s", page.url)
            return False

    # If we are on an unknown page, log it and try to navigate to settings directly
    logger.warning("Unknown page after login: %s – attempting to go to settings", page.url)
    try:
        page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        if "/settings/profile" in page.url:
            return True
    except Exception:
        pass

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

    # Now handle any post-login challenges (device verification, skip, etc.)
    if not _handle_post_login_challenges(page):
        # If we couldn't get to settings, save debug artifacts and raise
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(
            "Failed to complete login. A security challenge may require manual action. "
            "Check the saved debug artifacts (screenshot and HTML) for more details."
        )

    # Final verification: we should be on settings
    if "/settings/profile" not in page.url:
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(f"Login did not reach settings page. Current URL: {page.url}")

    logger.debug("Successfully authenticated and reached settings page")


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
    # Strategy 1: File input might already be present
    if _is_file_input_visible(page):
        logger.debug("File input already present")
        return True

    # Strategy 2: Click on the avatar image
    try:
        logger.debug("Attempting to click avatar image")
        page.locator("img.avatar").first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Avatar click opened file input")
            return True
    except PlaywrightTimeoutError:
        logger.debug("Avatar click did not open file input")

    # Strategy 3: Button selectors
    button_selectors = [
        "button[aria-label='Edit profile picture']",
        "button[aria-label='Edit']",
        "button[aria-label='Upload profile picture']",
        "a[aria-label='Edit profile picture']",
        "a[aria-label='Edit']",
        "button:has-text('Edit')",
        "a:has-text('Edit')",
        "button:has(svg)",
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

    # Strategy 4: Role-based
    try:
        logger.debug("Trying role=button with name 'Edit'")
        page.get_by_role("button", name="Edit").first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Role button 'Edit' opened file input")
            return True
    except PlaywrightTimeoutError:
        pass

    # Strategy 5: Text fallback
    try:
        logger.debug("Trying get_by_text('Edit', exact=False)")
        page.get_by_text("Edit", exact=False).first.click(timeout=5000)
        if _wait_for_file_input(page):
            logger.debug("Text fallback opened file input")
            return True
    except PlaywrightTimeoutError:
        pass

    return False


def _upload_profile_picture(page, image_path):
    """Navigate to profile settings and upload the processed image."""
    # Ensure we are on the settings page (if not already)
    if "/settings/profile" not in page.url:
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

    # Open the upload dialog
    if not _try_open_avatar_dialog(page):
        _save_debug_artifacts(page, "upload_dialog_failure")
        raise RuntimeError(
            "Unable to open avatar upload dialog. The 'Edit' button may be hidden or "
            "the page structure has changed. Check the saved screenshot and HTML."
        )

    # Upload the file
    file_input = page.locator("input[type='file']").first
    file_input.wait_for(state="attached", timeout=10000)
    file_input.set_input_files(str(image_path))

    # Confirm upload
    page.wait_for_selector(
        "button:has-text('Set new picture'), button:has-text('Save')",
        timeout=15000,
    )
    save_button = page.locator(
        "button:has-text('Set new picture'), button:has-text('Save')"
    ).first
    save_button.click()
    page.wait_for_load_state("networkidle")
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
            # On any exception, save debug artifacts before re-raising
            try:
                _save_debug_artifacts(page, "error")
            except Exception:
                pass
            raise e
        finally:
            if debug_mode:
                # Keep browser open for a moment to inspect
                logger.info("Debug mode: browser will close in 30 seconds. Press Ctrl+C to abort.")
                time.sleep(30)
            browser.close()