#   src/github_client.py

# --- Imports ---
import base64
import logging
import time
import requests
import config

logger = logging.getLogger(__name__)

# --- retry configuration ---
AVATAR_CHANGE_POLL_ATTEMPTS = 5
AVATAR_CHANGE_POLL_DELAY = 5 # seconds


def get_current_avatar_url() :
    # fetch the currently set avatar URL for the authenticated user
    if not config.GH_TOKEN :
        raise ValueError("GH_TOKEN is not set. Check .env or GitHub Secrets.")

    headers = {
        "Authorization": f"token {config.GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    resp = requests.get("https://api.github.com/user", headers=headers, timeout=20)
    if resp.status_code != 200 :
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text}")

    return resp.json().get("avatar_url")


def update_avatar(image_path) :
    # update authenticated GitHub user's avatar

    # uses the GitHub REST API (PATCH /user) with a base64-encoded image
    # requires a personal access token with `user` scope
    if not config.GH_TOKEN :
        raise ValueError("GH_TOKEN is not set. Check .env or GitHub Secrets.")

    old_avatar_url = get_current_avatar_url()
    logger.info("Current avatar URL before update: %s", old_avatar_url)

    with open(image_path, "rb") as f :
        avatar_base64 = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "Authorization": f"token {config.GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"avatar_url": f"data:image/png;base64,{avatar_base64}"}

    logger.debug("Sending avatar update request to GitHub API")
    resp = requests.patch("https://api.github.com/user", json=data, headers=headers, timeout=20)

    if resp.status_code != 200 :
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text}")

    # poll for the avatar URL to change – GitHub's CDN may not update immediately
    new_avatar_url = old_avatar_url
    for attempt in range(1, AVATAR_CHANGE_POLL_ATTEMPTS + 1) :
        logger.debug("Polling avatar URL – attempt %d/%d", attempt, AVATAR_CHANGE_POLL_ATTEMPTS)
        time.sleep(AVATAR_CHANGE_POLL_DELAY)
        new_avatar_url = get_current_avatar_url()
        if new_avatar_url != old_avatar_url :
            break

    if new_avatar_url == old_avatar_url :
        logger.warning(
            "Avatar URL did not change after update. "
            "This may indicate the image was identical to the current avatar, "
            "or GitHub is still processing the upload."
        )
    else :
        logger.info("Avatar URL after update: %s", new_avatar_url)
        logger.info("GitHub profile picture updated successfully")

    return resp.json()