#   src/github_client.py

# --- Imports ---
import base64
import logging
import requests
import config

logger = logging.getLogger(__name__)

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

    new_avatar_url = get_current_avatar_url()
    logger.info("Avatar URL after update: %s", new_avatar_url)

    # verify the avatar actually changed
    if old_avatar_url == new_avatar_url :
        raise RuntimeError("Avatar update did not change the avatar URL. GitHub may have silently ignored the request.")

    logger.info("GitHub profile picture updated successfully")
    return resp.json()