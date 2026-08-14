#   src/github_client.py

# --- Imports ---
import base64
import logging
import os
import time
from urllib.parse import quote
import requests
import config

logger = logging.getLogger(__name__)

# --- retry configuration ---
AVATAR_CHANGE_POLL_ATTEMPTS = 5
AVATAR_CHANGE_POLL_DELAY = 5  # seconds


def get_current_user() :
    # fetch the authenticated user object
    if not config.GH_TOKEN :
        raise ValueError("GH_TOKEN is not set. Check .env or GitHub Secrets.")

    headers = {
        "Authorization": f"token {config.GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    resp = requests.get("https://api.github.com/user", headers=headers, timeout=20)
    if resp.status_code != 200 :
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text}")

    return resp.json()


def get_current_avatar_url() :
    # fetch the currently set avatar URL for the authenticated user
    return get_current_user().get("avatar_url")


def update_avatar(avatar_url) :
    # update authenticated GitHub user's avatar using a publicly reachable image URL

    # GitHub's PATCH /user endpoint expects `avatar_url` to be an http(s) URL
    # that GitHub can fetch. Data URIs are not accepted reliably.
    if not config.GH_TOKEN :
        raise ValueError("GH_TOKEN is not set. Check .env or GitHub Secrets.")

    if not avatar_url.startswith(("http://", "https://")) :
        raise ValueError("avatar_url must be an http(s) URL")

    before_updated_at = get_current_user().get("updated_at")
    logger.debug("Current user updated_at before update: %s", before_updated_at)

    headers = {
        "Authorization": f"token {config.GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"avatar_url": avatar_url}

    logger.debug("Sending avatar update request to GitHub API with URL: %s", avatar_url)
    resp = requests.patch("https://api.github.com/user", json=data, headers=headers, timeout=30)

    if resp.status_code != 200 :
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text}")

    after_updated_at = resp.json().get("updated_at")
    logger.debug("GitHub API response updated_at: %s", after_updated_at)

    # poll for the user record to reflect the avatar change – the CDN may not update immediately
    for attempt in range(1, AVATAR_CHANGE_POLL_ATTEMPTS + 1) :
        if after_updated_at != before_updated_at :
            break
        logger.debug("Polling for avatar update – attempt %d/%d", attempt, AVATAR_CHANGE_POLL_ATTEMPTS)
        time.sleep(AVATAR_CHANGE_POLL_DELAY)
        after_updated_at = get_current_user().get("updated_at")

    if after_updated_at == before_updated_at :
        logger.warning(
            "User updated_at did not change after avatar update. "
            "This may indicate the avatar URL could not be fetched or GitHub is still processing the upload."
        )
    else :
        logger.info("GitHub profile picture updated successfully")

    return resp.json()


def publish_image_to_repo(image_path, remote_path="assets/profile_pictures/current_avatar.png") :
    # publish a local image to the repository via the GitHub Contents API and return a public raw URL

    # This provides GitHub's avatar fetcher with a publicly reachable URL.
    # The repository must be public, or the raw URL must be accessible without auth.
    if not os.getenv("GITHUB_REPOSITORY") :
        raise RuntimeError("GITHUB_REPOSITORY is not set. The workflow must run inside GitHub Actions.")

    owner, repo = os.getenv("GITHUB_REPOSITORY").split("/", 1)
    token = os.getenv("GITHUB_TOKEN") or config.GH_TOKEN
    if not token :
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required to upload the image to the repository.")

    branch = os.getenv("GITHUB_REF_NAME") or "main"
    encoded_path = quote(remote_path, safe="/")
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # get the current file SHA if it already exists (required to update the file)
    existing_sha = None
    get_resp = requests.get(url, headers=headers, timeout=20)
    if get_resp.status_code == 200 :
        existing_sha = get_resp.json().get("sha")
    elif get_resp.status_code != 404 :
        logger.warning("Unexpected status %d while checking remote file: %s", get_resp.status_code, get_resp.text)

    with open(image_path, "rb") as f :
        content = base64.b64encode(f.read()).decode("utf-8")

    body = {
        "message": "Update profile picture image",
        "content": content,
        "branch": branch,
    }
    if existing_sha :
        body["sha"] = existing_sha

    put_resp = requests.put(url, json=body, headers=headers, timeout=30)
    if put_resp.status_code not in (200, 201) :
        raise RuntimeError(f"GitHub Contents API error {put_resp.status_code}: {put_resp.text}")

    commit_sha = put_resp.json().get("commit", {}).get("sha")
    if not commit_sha :
        raise RuntimeError("No commit SHA returned by GitHub Contents API")

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{encoded_path}"

    # verify the raw URL is publicly reachable before handing it to GitHub
    raw_resp = requests.get(raw_url, timeout=15)
    if raw_resp.status_code != 200 :
        raise RuntimeError(
            f"Raw image URL is not publicly reachable (status {raw_resp.status_code}). "
            "Make the repository public or use a public gist/alternative hosting."
        )

    logger.info("Published avatar image to %s", raw_url)
    return raw_url