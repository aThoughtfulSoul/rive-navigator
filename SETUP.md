# Rive Navigator — Setup Guide

## Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **Google Chrome** browser
- **A Google Cloud account** with a project (you said you have one)
- **A Gemini API key** (free, takes 30 seconds)

---

## Step 1: Get Your Gemini API Key

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **"Create API key"**
3. Select your existing GCP project
4. Copy the key — you'll need it in Step 3

---

## Step 2: Install Python Dependencies

Open Terminal and run:

```bash
cd /Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator

# Create a virtual environment (keeps deps isolated from your system Python)
python3 -m venv venv

# Activate it — you'll see (venv) appear in your terminal prompt
source venv/bin/activate

# Install the dependencies
pip install -r requirements.txt
```

> **What's a virtual environment?** It's like a sandbox for Python packages.
> Instead of installing globally (which can conflict with other projects),
> `venv` creates a local folder with its own Python and packages.
> You need to run `source venv/bin/activate` every time you open a new
> terminal window to work on this project.

---

## Step 3: Configure Your API Key

Open the `.env` file and paste your key:

```bash
# Open in any text editor — or use nano in terminal:
nano agent/.env
```

Change this line:
```
GOOGLE_API_KEY=YOUR_API_KEY_HERE
```
To:
```
GOOGLE_API_KEY=AIzaSy...your_actual_key...
```

Save and close (`Ctrl+X`, then `Y`, then `Enter` in nano).

> **Security note:** The `.env` file is in `.gitignore` so it won't be
> committed to git. Never share your API key publicly.

---

## Step 4: Start the Backend Server

```bash
# Make sure you're in the project root and venv is activated
cd /Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator
source venv/bin/activate

# Start the server
python -m uvicorn agent.server:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

> **What is uvicorn?** It's a web server for Python. It hosts your FastAPI
> backend so the Chrome extension can talk to it. The `--reload` flag means
> it auto-restarts when you change code (like live reload in Xcode).

**Test it:** Open [http://localhost:8000/api/health](http://localhost:8000/api/health) in your browser. You should see:
```json
{"status": "ok", "agent": "rive_navigator", "model": "gemini-3.0-flash"}
```

**Leave this terminal running.** Open a new terminal tab/window for other work.

---

## Step 5: Load the Chrome Extension

Chrome extensions don't need to be "compiled" — they're just HTML/CSS/JS files
that Chrome loads directly. No build step needed.

1. Open Chrome
2. Navigate to `chrome://extensions`
3. Toggle **"Developer mode"** ON (top-right switch)
4. Click **"Load unpacked"** (top-left button)
5. Navigate to and select the folder:
   ```
   /Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/chrome-extension
   ```
6. The extension appears in your list with the purple "RN" icon

> **No build step?** Unlike Xcode or Unreal where you compile C++ into a
> binary, Chrome extensions are interpreted at runtime. Chrome reads the
> `manifest.json` and loads the JS/HTML/CSS directly. When you edit a file,
> just click the refresh icon on the extension card in `chrome://extensions`.

---

## Step 6: Test It

1. Make sure the backend is running (Step 4)
2. Open [https://rive.app](https://rive.app) and open a file in the editor
3. Click the **Rive Navigator extension icon** in Chrome's toolbar
   - If you don't see it, click the puzzle piece icon → pin "Rive UI Navigator"
4. The sidebar panel opens to the right of the Rive editor
5. Try clicking **"What's on screen?"** or type a question

---

## Troubleshooting

### "Cannot read properties of null" or sidebar won't open
The `sidePanel` API requires Chrome 114+. Update Chrome if needed.

### Extension shows "Disconnected"
- Is the backend running? Check the terminal from Step 4
- Try [http://localhost:8000/api/health](http://localhost:8000/api/health) in your browser
- If it says "connection refused", restart the backend

### "GOOGLE_API_KEY not set" or 401 errors
- Check `agent/.env` has your actual key (not the placeholder)
- Make sure there are no extra spaces or quotes around the key

### Extension not appearing on rive.app
- Check `chrome://extensions` — is the extension enabled?
- Click the refresh icon on the extension card
- Check the "Errors" button on the extension card for details

### Changes to extension code not taking effect
After editing any file in `chrome-extension/`:
1. Go to `chrome://extensions`
2. Click the circular refresh arrow on the Rive Navigator card
3. Reload the Rive tab

### Changes to Python code not taking effect
The `--reload` flag should auto-detect changes. If not, `Ctrl+C` the
server and restart it.

---

## Project Structure (What Everything Does)

```
rive-navigator/
│
├── agent/                        # Python backend (the "brain")
│   ├── __init__.py               # Makes this a Python package, exports root_agent
│   ├── agent.py                  # The AI agent definition + system prompt
│   ├── server.py                 # REST API server (like a web endpoint)
│   ├── .env                      # Your API key (secret, not committed)
│   └── tools/                    # Functions the AI can call
│       ├── screenshot_analyzer.py  # Records what the AI sees
│       ├── rive_docs_lookup.py     # Searches Rive docs (source of truth)
│       ├── task_manager.py         # Task mode: start, advance, verify steps
│       └── guidance.py             # Suggests next steps
│
├── chrome-extension/             # The Chrome sidebar (the "eyes + UI")
│   ├── manifest.json             # Extension config (like Info.plist in Xcode)
│   ├── background.js             # Runs in background, handles screenshots
│   ├── content.js                # Injected into rive.app, reads DOM state
│   ├── icons/                    # Extension icons
│   └── sidebar/
│       ├── sidebar.html          # Chat UI layout
│       ├── sidebar-glass.css     # Default glass theme styling
│       └── sidebar.js            # Chat logic + task mode controls
│
├── rive-docs/                    # Cloned Rive documentation (285 files)
├── requirements.txt              # Python package list
├── Dockerfile                    # For deploying to Google Cloud Run
└── .gitignore                    # Files to exclude from git
```

### How the pieces connect:

```
┌─────────────────────────────────────────────────────┐
│ Chrome Browser                                       │
│                                                      │
│  ┌────────────────┐    ┌──────────────────────────┐ │
│  │ Rive Editor Tab │    │ Extension Sidebar        │ │
│  │ (rive.app)      │    │ (sidebar.html/js/css)    │ │
│  │                 │    │                          │ │
│  │  content.js     │◄──►│  Sends questions +       │ │
│  │  (reads DOM)    │    │  screenshots to backend  │ │
│  └────────────────┘    └───────────┬──────────────┘ │
│                                    │                 │
│  background.js captures screenshots│                 │
│  via chrome.tabs.captureVisibleTab │                 │
└────────────────────────────────────┼─────────────────┘
                                     │ HTTP POST
                                     ▼
                          ┌──────────────────────┐
                          │ Python Backend        │
                          │ (localhost:8000)       │
                          │                       │
                          │  server.py             │
                          │    ↓                   │
                          │  ADK Agent             │
                          │    ↓                   │
                          │  Gemini 3.0 Flash API  │
                          │  (Google Cloud)        │
                          └──────────────────────┘
```

---

## Daily Development Workflow

Every time you sit down to work:

```bash
# Terminal 1: Start the backend
cd /Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator
source venv/bin/activate
python -m uvicorn agent.server:app --reload --port 8000

# Terminal 2: Your working terminal for editing files, git, etc.
cd /Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator
```

After editing Python files → backend auto-reloads (thanks to `--reload`).
After editing extension files → refresh the extension in `chrome://extensions`.

---

## Deploying to Google Cloud (When Ready)

This is for the hackathon submission. Do this last, once everything works locally.

```bash
# Make sure gcloud CLI is installed and authenticated
# https://cloud.google.com/sdk/docs/install

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Deploy to Cloud Run
gcloud run deploy rive-navigator \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=your_key_here"
```

After deploying, you'll get a URL like `https://rive-navigator-xxxxx.run.app`.
Open the extension options page and set **Backend API URL** to that Cloud Run URL.

1. Go to `chrome://extensions`
2. Find **Rive UI Navigator**
3. Click **Details**
4. Click **Extension options**
5. Paste your Cloud Run URL, for example:
   ```
   https://rive-navigator-xxxxx.run.app
   ```

Notes:
- The extension still defaults to `http://localhost:8000` for local development.
- Cloud updates are still pretty fast, but not "local fast" — expect build + deploy time in minutes, not seconds.
- Generated SVG tracing assets are stored under `/tmp` automatically on Cloud Run, which is the correct temporary filesystem for this app.
