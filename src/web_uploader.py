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


def _generate_totp_code() :
    # generate a time-based one-time password for GitHub 2FA, when configured
    if not config.GH_TOTP_SECRET :
        return None

    try :
        return pyotp.TOTP(config.GH_TOTP_SECRET).now()
    except Exception as err :
        logger.warning("Failed to generate TOTP code: %s", err)
        return None


def _login(page) :
    # sign in to GitHub using username/password and optional TOTP 2FA
    if not config.GH_USERNAME or not config.GH_PASSWORD :
        raise RuntimeError("GH_USERNAME and GH_PASSWORD must be set for browser automation.")

    page.goto(GITHUB_LOGIN_URL, wait_until="domcontentloaded")
    page.fill("#login_field", config.GH_USERNAME)
    page.fill("#password", config.GH_PASSWORD)
    page.click("input[type='submit']")

    # GitHub may require a 2FA challenge after login
    try :
        page.wait_for_url(TWO_FACTOR_URL_PATTERN, timeout=5000)
        totp = _generate_totp_code()
        if not totp :
            raise RuntimeError("GitHub requires 2FA, but no GH_TOTP_SECRET was provided.")

        page.fill("#app_totp", totp)
        page.click("button[type='submit']")
    except PlaywrightTimeoutError :
        logger.debug("No 2FA challenge detected")

    # wait until we leave the login/two-factor pages
    page.wait_for_url(
        lambda url: "github.com/login" not in url and "sessions/two-factor" not in url,
        timeout=15000,
    )
    logger.debug("Successfully authenticated with GitHub")


def _upload_profile_picture(page, image_path) :
    # navigate to profile settings and upload the processed image
    page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")

    # the file input is often hidden on the settings page
    try :
        page.wait_for_selector("input[type='file']", timeout=5000)
    except PlaywrightTimeoutError :
        # if the input is not present, click the first available Edit button
        # on the profile page to open the avatar selection dialog
        page.get_by_text("Edit", exact=True).first.click()
        page.wait_for_selector("input[type='file']", timeout=5000)

    file_input = page.locator("input[type='file']").first
    file_input.set_input_files(str(image_path))

    # wait for the crop/save dialog and confirm the upload
    page.wait_for_selector(
        "button:has-text('Set new picture'), button:has-text('Save')",
        timeout=10000,
    )
    save_button = page.locator(
        "button:has-text('Set new picture'), button:has-text('Save')"
    ).first
    save_button.click()

    # wait for the page to settle after the avatar update
    page.wait_for_load_state("networkidle")
    logger.info("Profile picture uploaded through GitHub web UI")


def upload_avatar(image_path) :
    # launch a browser, sign in, and upload the avatar image
    if not Path(image_path).exists() :
        raise FileNotFoundError(f"Image not found: {image_path}")

    with sync_playwright() as p :
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try :
            page = browser.new_page()
            _login(page)
            _upload_profile_picture(page, image_path)
        finally :
            browser.close()