# ProfilePicture-GitHub

a repository focused on setting profile picture for GitHub

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

1. Clone repo & cd in
   ```bash
   git clone https://github.com/your-username/ProfilePicture-GitHub.git
   cd ProfilePicture-GitHub
   ```

2. Create a `.env` file based on `.env.example`:
   ```bash
   cp .env.example .env
   # edit .env with GitHub token & Pinterest board URL (optional)
   ```

3. Add your local fallback images to `assets/profile_pictures/`

4. Run the script locally :
   ```bash
   pip install -r requirements.txt
   python src/main.py
   ```

5. To automate, push the repository to GitHub and configure the following secrets in the repository settings :
   - `GITHUB_TOKEN` – a personal access token with `user` scope
   - `PINTEREST_SOURCE_BOARD` – (optional) URL to a public Pinterest board

   GitHub Action will then run daily at midnight UTC

## Configuration

- `GITHUB_TOKEN` – required. Personal access token with `user` scope
- `PINTEREST_SOURCE_BOARD` – optional. Must be a valid, public Pinterest board URL
- `PROFILE_PICTURE_DIR` – optional. Local directory for fallback images (default `assets/profile_pictures`)
- `IMAGE_SIZE` – optional. Target avatar size in pixels (default 512)

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

This section can be used to log notes about the project scope, known limitations, or future enhancements.