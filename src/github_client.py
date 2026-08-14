#   src/github_client.py

# --- Imports ---
import base64
import logging
import requests
import config

logger = logging.getLogger(__name__)

def update_avatar(image_path) :
    # update authenticated GitHub user's avatar

    # uses the GitHub REST API (PATCH /user) with a base64-encoded image
    # requires a personal access token with `user` scope
    if not config.GH_TOKEN :
        raise ValueError("GH_TOKEN is not set. Check .env or GitHub Secrets.")

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

    logger.info("GitHub profile picture updated successfully")
    return resp.json()