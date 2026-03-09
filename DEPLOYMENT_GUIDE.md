# Voice-to-CRM Pipeline - Deployment Guide

**For Daniel @ Sideline Group**
**Estimated setup time: 2-3 hours**

This guide walks you through every step to deploy the Voice-to-CRM pipeline. You'll set up accounts, configure API keys, and deploy the app to Railway. Each step tells you exactly where to go, what to click, and what to paste.

---

## Prerequisites

Before you start, make sure you have:
- Your `daniel@sidelinegroup.co` Google account
- Access to Sideline's Slack workspace (admin or ability to add integrations)
- A credit card for Anthropic API and Deepgram signups (costs will be under $20/month)
- The codebase folder (the files you downloaded from Claude)

---

## Step 1: Set Up Google Cloud OAuth (30-45 min)

This lets the app read your Google Calendar and write to Google Sheets.

### 1a. Open Your Existing Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with `daniel@sidelinegroup.co`
3. Click the project dropdown at the top of the page
4. Select **"Gmail Affinity Automation"** (your existing project)

### 1b. Enable Required APIs

1. In the left sidebar, click **"APIs & Services"** → **"Library"**
2. Search for **"Google Calendar API"**. Click it, then click **"Enable"**
3. Go back to the Library. Search for **"Google Sheets API"**. Click it, then click **"Enable"**

### 1c. Create OAuth Credentials

1. In the left sidebar, click **"APIs & Services"** → **"Credentials"**
2. Click **"+ CREATE CREDENTIALS"** at the top → **"OAuth client ID"**
3. If it asks you to configure a consent screen first:
   - Choose **"Internal"** (since you're on Google Workspace)
   - App name: "Voice CRM Pipeline"
   - User support email: your email
   - Developer contact email: your email
   - Click **Save and Continue** through the remaining screens (no scopes or test users needed for Internal apps)
4. Back on Create OAuth client ID:
   - Application type: **"Web application"**
   - Name: "Voice CRM Pipeline"
   - Under **"Authorized redirect URIs"**, click **"+ ADD URI"** and enter: `https://developers.google.com/oauthplayground`
   - Click **"Create"**
5. A popup shows your **Client ID** and **Client Secret**. **Copy both and save them somewhere safe.** You'll need them in Step 6.

### 1d. Get a Refresh Token

1. Go to [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
2. Click the **gear icon** (Settings) in the top right
3. Check **"Use your own OAuth credentials"**
4. Paste in your **Client ID** and **Client Secret** from step 1c
5. Close the settings panel
6. In the left sidebar under "Step 1 - Select & authorize APIs":
   - Scroll down and find **"Google Calendar API v3"** → check `https://www.googleapis.com/auth/calendar.readonly`
   - Find **"Google Sheets API v4"** → check `https://www.googleapis.com/auth/spreadsheets`
7. Click **"Authorize APIs"**
8. Sign in with your Google account and grant access
9. On "Step 2", click **"Exchange authorization code for tokens"**
10. Copy the **Refresh Token** from the response. **Save this.** You'll need it in Step 6.

---

## Step 2: Set Up Deepgram (5 min)

1. Go to [console.deepgram.com](https://console.deepgram.com)
2. Create an account (you get $200 in free credits)
3. Once in the dashboard, go to **"API Keys"** in the left sidebar
4. Click **"Create a New API Key"**
   - Name: "Voice CRM"
   - Permissions: "Member" is fine
5. **Copy the API key.** Save it. You'll need it in Step 6.

---

## Step 3: Set Up Anthropic API (5 min)

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account or sign in (this is separate from your Claude Max subscription)
3. Add a payment method under **Billing**
4. Go to **"API Keys"** and click **"Create Key"**
   - Name: "Voice CRM"
5. **Copy the API key.** Save it. You'll need it in Step 6.

---

## Step 4: Set Up Slack Webhooks (15 min)

You need to create "Incoming Webhooks" that let the app post messages to Slack channels.

### 4a. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. App Name: "Voice CRM Bot"
4. Pick your Sideline workspace
5. Click **"Create App"**

### 4b. Enable Incoming Webhooks

1. In the left sidebar, click **"Incoming Webhooks"**
2. Toggle the switch to **"On"**
3. Click **"Add New Webhook to Workspace"** at the bottom
4. Select the **#greg-meeting-notes** channel you created
5. Click **"Allow"**
6. **Copy the Webhook URL.** This is your `SLACK_WEBHOOK_GREG_PROMPT`. Save it.

7. Repeat: Click **"Add New Webhook to Workspace"** again
8. Select or create a channel for Daniel's outputs (e.g., **#greg-meeting-notes** again, or a separate channel)
9. **Copy this URL.** This is your `SLACK_WEBHOOK_DANIEL_OUTPUT`.

10. (Optional) Repeat one more time for Justine's channel if you want her outputs in a separate channel. Otherwise, use the same webhook URL for both Daniel and Justine.

---

## Step 5: Create a Google Sheet (2 min)

1. Go to [sheets.google.com](https://sheets.google.com)
2. Create a new blank spreadsheet
3. Name it **"Voice CRM Meeting Log"**
4. Look at the URL. It looks like: `https://docs.google.com/spreadsheets/d/ABC123XYZ/edit`
5. Copy the **ID** part (the `ABC123XYZ` between `/d/` and `/edit`). Save it.

---

## Step 6: Deploy to Railway (30-45 min)

### 6a. Create a Railway Account

1. Go to [railway.app](https://railway.app)
2. Sign up or sign in (you can use your GitHub account)

### 6b. Push Code to GitHub

The app needs to be in a GitHub repository for Railway to deploy it.

1. Go to [github.com](https://github.com) and sign in (create an account if needed)
2. Click **"+"** in the top right → **"New repository"**
3. Name: `voice-crm-pipeline`
4. Make it **Private**
5. Click **"Create repository"**
6. Upload the codebase files. You can either:
   - **Option A (easiest):** On the repository page, click **"uploading an existing file"**, then drag and drop all the files from the voice-crm folder. Make sure the folder structure is flat (main.py at the root, not inside a subfolder). Include the `templates/` folder with `recorder.html` inside it.
   - **Option B (if you have git/Claude Code):** Use Claude Code to push the files. It will walk you through the git commands.

### 6c. Deploy on Railway

1. In Railway, click **"New Project"** → **"Deploy from GitHub Repo"**
2. Select your `voice-crm-pipeline` repository
3. Railway will detect the Python project and start building

### 6d. Add a Postgres Database

1. In your Railway project, click **"+ New"** → **"Database"** → **"Add PostgreSQL"**
2. Railway automatically creates the database and sets a `DATABASE_URL` variable
3. Click on your web service, go to **"Variables"**, and verify `DATABASE_URL` is there (Railway may auto-link it, or you may need to copy it from the Postgres service's "Connect" tab)

### 6e. Set Environment Variables

1. Click on your web service in Railway
2. Go to the **"Variables"** tab
3. Add each of these variables (use the values you saved in Steps 1-5):

```
GOOGLE_CLIENT_ID=          (from Step 1c)
GOOGLE_CLIENT_SECRET=      (from Step 1c)
GOOGLE_REFRESH_TOKEN=      (from Step 1d)
GOOGLE_CALENDAR_ID=primary
TARGET_USER_EMAIL=daniel@sidelinegroup.co
TARGET_TIMEZONE=America/New_York
INTERNAL_DOMAIN=sidelinegroup.co
EXCLUDED_EMAILS=           (leave blank for now, add later)
DEEPGRAM_API_KEY=          (from Step 2)
ANTHROPIC_API_KEY=         (from Step 3)
SLACK_WEBHOOK_GREG_PROMPT= (from Step 4b, first webhook)
SLACK_WEBHOOK_DANIEL_OUTPUT= (from Step 4b, second webhook)
SLACK_WEBHOOK_JUSTINE_OUTPUT= (from Step 4b, third webhook or same as Daniel's)
GOOGLE_SHEETS_SPREADSHEET_ID= (from Step 5)
APP_BASE_URL=              (see step 6f below)
POLL_INTERVAL_MINUTES=3
POST_MEETING_DELAY_MINUTES=3
BATCH_REMINDER_HOUR=18
AUDIO_UPLOAD_DIR=uploads/audio
```

### 6f. Get Your Railway URL

1. Click on your web service in Railway
2. Go to **"Settings"** → **"Networking"**
3. Under **"Public Networking"**, click **"Generate Domain"**
4. Railway will give you a URL like `voice-crm-pipeline-production.up.railway.app`
5. Go back to **Variables** and set `APP_BASE_URL` to this URL (with `https://`, no trailing slash)

### 6g. Redeploy

1. After setting all variables, Railway will automatically redeploy
2. Wait for the build to complete (check the **"Deployments"** tab)
3. Visit your Railway URL in a browser. You should see: `{"app": "Voice-to-CRM Pipeline", "org": "Sideline Group", "status": "running"}`
4. Visit `https://your-url.railway.app/health` to verify the health check

---

## Step 7: Test It (15 min)

### 7a. Create a Test Calendar Event

1. Create a Google Calendar event for 5 minutes from now
2. Set the duration to 5 minutes
3. Add an **external** attendee (use a personal email or a colleague's non-sidelinegroup.co email)
4. Give it a title like "Test Meeting - Voice CRM"

### 7b. Wait for the Prompt

1. After the meeting's end time passes (plus 3 minutes for the delay), check your **#greg-meeting-notes** Slack channel
2. You should see a message with the meeting details and a "Record Voice Note" button

### 7c. Record a Test Note

1. Tap the "Record Voice Note" button in Slack
2. Your browser opens the recording page with the meeting context
3. Allow microphone access when prompted
4. Tap the red circle to record
5. Say something like: "Just had a great call with [test name]. They're interested in learning more about the fund. Probably a $500K check. They know John Smith at ABC Capital. Follow up in two weeks."
6. Tap the square to stop recording
7. Wait for the "uploaded and processing" confirmation

### 7d. Check the Outputs

1. Check your Slack channel for the processed output (should arrive within 15-30 seconds)
2. Check your Google Sheet for the logged row
3. Verify the summary, action items, and proposed tags look reasonable

---

## Troubleshooting

**Slack prompt never arrives:**
- Check Railway logs (Deployments tab → click latest deployment → View Logs)
- Most likely: Google OAuth token issue. Make sure the refresh token is correct.
- Try visiting `https://your-url.railway.app/health` to confirm the app is running.

**Recording page shows "Meeting not found":**
- The meeting ID in the URL doesn't exist in the database. The calendar poll may not have run yet. Wait 3 minutes and check Slack again.

**Microphone permission denied:**
- On iPhone: Go to Settings → Safari → Microphone → Allow
- Make sure you're accessing via HTTPS (Railway provides this automatically)

**Audio uploads but no Slack output:**
- Check Railway logs for errors in the processing pipeline
- Most likely: Anthropic or Deepgram API key issue

**Google Sheets not updating:**
- Verify the Spreadsheet ID is correct
- Make sure the Google Sheets API is enabled in your Google Cloud project
- The sheet must be named "Sheet1" (the default)

---

## What's Next

Once this is running and you've validated it works with your calendar:

1. **Switch to Greg's calendar:** Change `TARGET_USER_EMAIL` to Greg's email. You'll need to re-do the OAuth flow (Step 1d) with Greg's Google account to get his refresh token.

2. **Add excluded emails:** Set `EXCLUDED_EMAILS` to a comma-separated list of Greg's personal contacts (wife, coach, etc.)

3. **Set up Justine's channel:** Create a separate Slack channel and webhook for Justine's action items if you want them separated from your tag proposals.

4. **V2 enhancements:** Affinity API integration for enriching prompts with existing tags and writing approved tags back to the CRM. This is the next engineering sprint.
