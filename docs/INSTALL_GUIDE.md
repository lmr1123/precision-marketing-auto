# Precision Marketing Auto - Installation Guide

## Step 1: Download and Extract

1. Go to **https://pm-auto.dslyy.com** in your browser
2. Click "Download for Windows" (or "Download for macOS" if using Mac)
3. Extract the downloaded zip file to a convenient location (e.g., Desktop or D:\)

After extraction, you should see a folder called `PrecisionMarketingAuto` containing:
- `start.bat` (Windows) or `start.command` (Mac)
- `app/` folder
- `data/` folder

## Step 2: First Launch

**Windows:** Double-click `start.bat`

**Mac:** Double-click `start.command` (if blocked by Gatekeeper, right-click > Open)

The first launch will:
1. Download and install required dependencies (takes 1-2 minutes)
2. Start Chrome with remote debugging enabled
3. Open the Precision Marketing UI in your browser

## Step 3: Create Desktop Shortcut (Optional)

**Windows:** Right-click `start.bat` > Send to > Desktop (create shortcut)

**Mac:** Drag `start.command` to Dock or create an alias on Desktop

## Daily Usage

Just double-click the desktop shortcut. The app will:
- **Automatically check for updates** and install them if available
- Start the UI service
- Open the browser interface

You always have the latest version - no manual update needed.

## Chrome Extension (Optional)

For field-level review of marketing plans:
1. Go to **https://pm-auto.dslyy.com/extension/**
2. Download the extension zip file
3. In Chrome, go to `chrome://extensions/`
4. Enable "Developer mode" (top right)
5. Click "Load unpacked" and select the extracted extension folder

## Troubleshooting

**"Port 8790 already in use"**
- Another instance is already running. Check your browser tabs.

**Chrome doesn't open automatically**
- Open Chrome manually and navigate to http://127.0.0.1:8790

**Update fails / No internet**
- The app will still work with the current version
- Updates will be applied next time you have internet access

**Need help?**
Contact the development team or check the task logs in `data/logs/`
