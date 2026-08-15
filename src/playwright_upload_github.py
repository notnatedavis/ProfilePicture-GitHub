#   src/playwright_upload_github.py

# --- Imports ---
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import pyotp
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config
import image_processor
import image_selector

logger = logging.getLogger(__name__)

# ==============================
# UPLOAD PROCESS ORDER
# ==============================
# 
# 1. upload_avatar() starts the browser and calls the upload pipeline
#
# 2. _login(page) handles authentication :
#    a. fill GitHub username and password
#    b. complete two-factor authentication when challenged
#    c. dismiss security challenges when possible
#    d. wait briefly, then open the profile settings page directly
#
# 3. _upload_profile_picture(page, image_path) changes the avatar :
#    a. navigate to GitHub settings/profile
#    b. click the avatar edit button
#    c. click the "Upload a photo…" menu item
#    d. select the processed image file
#    e. click "Set new profile picture"
# 4. upload_avatar() closes the browser and cleans up
#
# ==============================

# --- URLs ---
GITHUB_LOGIN_URL = "https://github.com/login"
GITHUB_DASHBOARD_URL = "https://github.com/"
GITHUB_SETTINGS_PROFILE_URL = "https://github.com/settings/profile"
TWO_FACTOR_URL_PATTERN = "**/sessions/two-factor*"
CHALLENGE_URL_PATTERNS = [
    "**/sessions/verify*", # Verify your account
    "**/sessions/device*", # Device verification
    "**/sessions/phone*",  # Phone verification
]

# --- Post-login navigation ---
LOGIN_SETTLE_SECONDS = 4  # seconds to wait after login before navigating to settings

# --- Viewport and browser configuration ---
# Use the exact same viewport locally and in GitHub Actions so coordinate
# fallbacks remain reliable across environments
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
VIEWPORT = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
WINDOW_SIZE_ARG = f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}"

# --- Coordinate fallbacks (fill in manually if automatic selectors fail) ---
# These are (x, y) coordinates on the page. Use DEBUG_PW=1 to find them.
COORD_EDIT_BUTTON = (100, 200) # click on the avatar edit button
COORD_UPLOAD_MENU = (150, 300) # Click on "Upload a photo…" menu item
COORD_SAVE_BUTTON = (200, 400) # Click on "Set new profile picture"

# --- Avatar comparison ---
GITHUB_AVATAR_SIZE = 512
MAX_IDENTICAL_ATTEMPTS = 3
AVATAR_COMPARISON_CONFIDENCE = 0.95  # 95% similarity required to be considered identical


def _generate_totp_code() :
    # generate a time-based one-time password for GitHub 2FA
    # make sure a TOTP secret is configured
    if not config.GH_TOTP_SECRET:
        return None

    # try to generate the current code
    try:
        return pyotp.TOTP(config.GH_TOTP_SECRET).now()
    # if generation fails, log a warning and return None
    except Exception as err:
        logger.warning("Failed to generate TOTP code: %s", err)
        return None


def _is_debug_mode():
    # return True if DEBUG_PW environment variable is set to a truthy value
    # read the DEBUG_PW variable
    # compare against common truthy string values
    return os.getenv("DEBUG_PW", "").lower() in ("1", "true", "yes")


def _set_avatar_size(url, size=GITHUB_AVATAR_SIZE) :
    # add or replace the size query parameter on a GitHub avatar URL
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query["s"] = str(size)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment)
    )


def _scrape_current_avatar_url(page) :
    # read the current avatar URL from the settings/profile page
    try :
        page.wait_for_selector("img.avatar", timeout=15000)
        avatar_src = page.locator("img.avatar").first.get_attribute("src")
        if avatar_src :
            return _set_avatar_size(avatar_src)
    except PlaywrightTimeoutError :
        logger.warning("Avatar element not found, falling back to public profile URL")
    return f"https://github.com/{config.GH_USERNAME}.png?s={GITHUB_AVATAR_SIZE}"


def _load_current_avatar_image(page) :
    # fetch and load the current GitHub profile picture at 512x512
    avatar_url = _scrape_current_avatar_url(page)
    logger.info("Current avatar URL: %s", avatar_url)
    return image_processor.load_image(avatar_url)


def _save_debug_artifacts(page, prefix="failure"):
    # save a screenshot and the page HTML to the current working directory
    # useful for debugging both locally and in GitHub Actions

    # create timestamped file names
    timestamp = int(time.time())
    screenshot_path = f"{prefix}_{timestamp}.png"
    html_path = f"{prefix}_{timestamp}.html"

    # try to save the screenshot and page content
    try:
        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.info("Debug artifacts saved: %s and %s", screenshot_path, html_path)
    # if artifact saving fails, log a warning instead of crashing
    except Exception as e:
        logger.warning("Could not save debug artifacts: %s", e)


def _handle_challenges(page):
    # detect and attempt to dismiss common security challenges
    # returns True if we are successfully logged in and not stuck on a challenge page

    # wait for the page to settle
    page.wait_for_load_state("domcontentloaded")

    # if redirected back to login, authentication failed
    if "/login" in page.url:
        logger.error("Redirected back to login page – authentication failed.")
        return False

    # if on dashboard or settings, we are logged in
    if page.url.rstrip("/") in (GITHUB_DASHBOARD_URL.rstrip("/"), GITHUB_SETTINGS_PROFILE_URL.rstrip("/")):
        logger.debug("Logged in successfully (dashboard or settings).")
        return True

    # check known challenge pages
    for pattern in CHALLENGE_URL_PATTERNS:
        prefix = pattern.replace("**/", "/").replace("*", "")
        if urlparse(page.url).path.startswith(prefix):
            logger.info("Detected challenge page: %s", page.url)

            # try to click any button that may dismiss the challenge
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
                # wait for navigation away from challenge
                page.wait_for_url(
                    lambda url: "/login" not in url,
                    timeout=10000,
                )
                # re-check after navigation
                return _handle_challenges(page)
            except PlaywrightTimeoutError:
                logger.warning("Could not automatically dismiss challenge.")

            # if challenge cannot be dismissed, manual intervention is required
            logger.error("Manual intervention required for challenge: %s", page.url)
            return False

    # unknown page – treat as authenticated; _login will navigate to settings directly
    logger.debug("Unknown page after login: %s – treating as authenticated", page.url)
    return True


def _login(page) : # 2.  
    # sign in to GitHub using username/password, handle 2FA and security challenges

    # 2a. 
    # validate credentials are set
    if not config.GH_USERNAME or not config.GH_PASSWORD:
        raise RuntimeError("GH_USERNAME and GH_PASSWORD must be set for browser automation.")
    # go to the login page
    page.goto(GITHUB_LOGIN_URL, wait_until="domcontentloaded")
    # fill username &B password fields
    page.fill("#login_field", config.GH_USERNAME)
    page.fill("#password", config.GH_PASSWORD)
    # submit the login form
    page.click("input[type='submit']")

    # 2b. 
    # (if) 2FA , wait & solve (easier to disable)
    try :
        page.wait_for_url(TWO_FACTOR_URL_PATTERN, timeout=5000)
        # generate a TOTP code
        totp = _generate_totp_code()
        if not totp:
            raise RuntimeError("GitHub requires 2FA, but no GH_TOTP_SECRET was provided.")
        # fill and submit the TOTP form
        page.fill("#app_totp", totp)
        page.click("button[type='submit']")
        # wait for the page to settle after 2FA
        page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError :
        logger.debug("No 2FA challenge detected")

    # 2c. 
    # handle any post-login security challenges
    if not _handle_challenges(page) :
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(
            "Failed to complete login. A security challenge may require manual action. "
            "Check the saved debug artifacts (screenshot and HTML) for more details."
        )
    # final verification – we should not be on login page anymore
    if "/login" in page.url :
        _save_debug_artifacts(page, "login_failure")
        raise RuntimeError(f"Login failed. Current URL: {page.url}")

    logger.debug("Successfully authenticated and reached %s", page.url)

    # Wait a few seconds for the session/cookies to settle before page traversal.
    time.sleep(LOGIN_SETTLE_SECONDS)

    # Open the profile settings page directly now that credentials are stored.
    page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")
    logger.debug("Opened settings profile page after login: %s", page.url)


def _upload_profile_picture(page, image_path) : # 3. 
    # navigate directly to settings and upload the profile picture
    # uses role-based clicks first; falls back to manual coordinates if needed

    # 3a. 
    # go directly to the settings profile page – skip user menu entirely
    # _login already opens this page, so avoid reloading when we are already there.
    if page.url.rstrip("/") != GITHUB_SETTINGS_PROFILE_URL.rstrip("/"):
        page.goto(GITHUB_SETTINGS_PROFILE_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    # wait for the avatar element to ensure the page is fully rendered
    try :
        page.wait_for_selector("img.avatar", timeout=15000)
    except PlaywrightTimeoutError :
        _save_debug_artifacts(page, "settings_load_failure")
        raise RuntimeError(
            f"Settings page did not load properly. Current URL: {page.url}. "
            "Check debug artifacts for details."
        )

    # 3b. 
    # click the avatar edit button
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

    # 3c. 
    # click the "Upload a photo…" menu item
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

    # 3d. 
    # set the input file by label
    try:
        logger.debug(f"Setting input file: {image_path}")
        page.get_by_label("Upload a photo…").set_input_files(str(image_path))
    except Exception as e:
        _save_debug_artifacts(page, "file_input_failure")
        raise RuntimeError(f"Failed to set input file: {e}")

    # 3e. 
    # click the "Set new profile picture" button
    try:
        logger.debug("Clicking 'Set new profile picture' button")
        page.get_by_role("button", name="Set new profile picture").click(timeout=10000)
        page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError:
        logger.warning("Role-based click on save button failed – trying coordinate fallback.")
        try:
            x, y = COORD_SAVE_BUTTON
            page.mouse.click(x, y)
            logger.debug(f"Clicked save button at coordinates ({x}, {y})")
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            _save_debug_artifacts(page, "save_button_failure")
            raise RuntimeError(f"Failed to click 'Set new profile picture' button: {e}")

    logger.info("Profile picture uploaded through GitHub web UI")


def upload_avatar(image_path) : # 1. - 4.
    # launch a browser, sign in, and upload the avatar image

    # verify the image file exists
    if not Path(image_path).exists() :
        raise FileNotFoundError(f"Image not found: {image_path}")

    # determine whether to run in debug mode
    debug_mode = _is_debug_mode()

    # start Playwright and launch a Chromium browser
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not debug_mode,
            args=[
                "--disable-blink-features=AutomationControlled",
                WINDOW_SIZE_ARG,           # match browser window to viewport
                "--no-sandbox",            # required in many CI containers
                "--disable-dev-shm-usage", # avoids shared memory issues in CI
            ],
        )
        temporary_paths = []
        try:
            # create a new page with a fixed viewport
            page = browser.new_page(viewport=VIEWPORT)
            if debug_mode:
                logger.info("Running in debug mode – browser window will appear.")

            # log in to GitHub
            _login(page)

            # --- duplicate-avatar check and re-fetch loop ---
            # Load the current avatar image from GitHub and center-crop/resize it.
            current_avatar_img = _load_current_avatar_image(page)
            current_avatar_processed = image_processor.process_image(current_avatar_img)

            # Load the candidate image and center-crop/resize it for comparison.
            candidate_img_raw = image_processor.load_image(image_path)
            candidate_img = image_processor.process_image(candidate_img_raw)

            logger.info("Candidate image path: %s", image_path)

            attempts = 0
            while image_processor.images_equal(
                candidate_img, current_avatar_processed,
                confidence=AVATAR_COMPARISON_CONFIDENCE
            ) and attempts < MAX_IDENTICAL_ATTEMPTS :
                attempts += 1
                logger.info(
                    "Selected image is identical to the current avatar; fetching another image "
                    "(attempt %d/%d)", attempts, MAX_IDENTICAL_ATTEMPTS
                )

                source = image_selector.select_image()
                logger.info("Selected replacement candidate: %s", source)
                img = image_processor.load_image(source)
                processed = image_processor.process_image(img)

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp :
                    tmp_path = Path(tmp.name)
                    temporary_paths.append(tmp_path)
                image_processor.save_image(processed, tmp_path)

                # update the candidate path and image used for comparison
                image_path = tmp_path
                candidate_img = processed

            if image_processor.images_equal(
                candidate_img, current_avatar_processed,
                confidence=AVATAR_COMPARISON_CONFIDENCE
            ) :
                raise RuntimeError(
                    f"Unable to select a profile picture different from the current avatar "
                    f"after {MAX_IDENTICAL_ATTEMPTS} additional attempts."
                )

            # upload the profile picture
            _upload_profile_picture(page, image_path)

            # log success before cleanup and browser close
            logger.info("Profile picture update completed successfully")

        except Exception as e :
            # on any error, try to save debug artifacts
            try:
                _save_debug_artifacts(page, "error")
            except Exception :
                pass
            raise e
        finally :
            # clean up any temporary images created during re-fetch attempts
            for path in temporary_paths :
                try :
                    if path.exists() :
                        path.unlink()
                except Exception :
                    logger.warning("Could not clean up temporary file %s", path)

            # keep browser open briefly in debug mode, then close
            if debug_mode:
                logger.info("Debug mode: browser will close in 10 seconds. Press Ctrl+C to abort.")
                time.sleep(10)
            browser.close()
            logger.debug("Browser closed")