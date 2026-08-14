# ProfilePicture-GitHub

a repository focused on setting profile picture for GitHub. 

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Usage](#usage)
- [Configuration](#Configuration)
- [Project-Structure](#Project-Structure)
- [Additional-Information](#Additional-Info)

## Introduction

This repository automates updating your GitHub profile picture on an interval (e.g., once every 24 hours). It can select images from a public Pinterest board or from a local directory, process them into the correct square format, and upload them to your GitHub account using the GitHub API.

## Features

- Scheduled updates via GitHub Actions (daily cron)
- Manual trigger via `workflow_dispatch`
- Random image selection from a public Pinterest board (using RSS feed)
- Fallback to local images when Pinterest is unavailable
- Automatic cropping and resizing to GitHub's avatar size (512×512)
- Environment variable configuration – no secrets in the repository

## Usage 

1. Clone repo & cd in (push locally to github)
   ```bash
   git clone https://github.com/notnatedavis/ProfilePicture-GitHub.git
   cd ProfilePicture-GitHub
   ```

2. Create a Personal Access Token (PAT)

   - Go to [GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)](https://github.com/settings/tokens)
   - Click `Generate new token (classic)`
   - Name it `ProfilePicture-Updater`
   - Set expiration as desired (long as possible)
   - Select `user` scope (IMPORTANT)
   - Generate and copy the token (save temporarily)

3. Add Secrets to Your Repository

   - Go to your repository → **Settings** → **Secrets and variables** → **Actions**
   - Add a new Repository secret named `GH_TOKEN` with the PAT value
   - (Optional) Add a secret named `PINTEREST_SOURCE_BOARD` with your public Pinterest board URL
  
   > The built-in `GITHUB_TOKEN` does not have the necessary `user` scope to update avatar so use custom PAT stored as `GH_TOKEN` to avoid confusion

4. Push and Enjoy

   Once the workflow file (`.github/workflows/update-profile-picture.yml`) is present and the secrets are set, GitHub Actions will automatically run the update daily at midnight UTC. You can also trigger it manually from the **Actions** tab → **All workflows** → (select) **repoWorkflow** → **Run workflow**

## Configuration

- `GH_TOKEN` – required. Personal access token with `user` scope
- `PINTEREST_SOURCE_BOARD` – optional. Must be a valid, public Pinterest board URL
- `PROFILE_PICTURE_DIR` – optional. Local directory for fallback images (default `assets/profile_pictures`)
- `IMAGE_SIZE` – optional. Target avatar size in pixels (default 512)

- **GitHub Actions** : Add the corresponding secrets or variables under repository settings

## Project-Structure

```bash
ProfilePicture-GitHub/
├── .github/
│   └── workflows/
│       └── update-profile-picture.yml
├── assets/
│   └── profile_pictures/
│       └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── github_client.py
│   ├── image_processor.py
│   ├── image_selector.py
│   ├── pinterest_api.py
│   └── main.py
├── .env.example
├── .gitignore
├── ReadMe.md
└── requirements.txt
```

## Additional-Info

This section can be used to log notes about the project scope, known limitations, or future enhancements
