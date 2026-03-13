# Rive Navigator

Rive Navigator is an AI copilot for the Rive editor. It can see the editor through screenshots, explain what is on screen, guide multi-step tasks, execute trusted browser actions inside Rive, narrate its responses, and generate prompt-based SVG assets for import.

## What It Does

- Understands the current Rive editor state from screenshots
- Supports collaborative guidance and fully agentic task execution
- Uses trusted Chrome DevTools Protocol input for clicks, drags, typing, and shortcuts
- Grounds responses with a local corpus of Rive documentation
- Generates image previews, traces them to SVG, sanitizes them, and pastes them into Rive
- Supports optional voice narration with Gemini TTS

## Main Components

- `chrome-extension/`
  - Chrome side panel UI, screenshot capture, CDP action execution, SVG paste import
- `agent/`
  - FastAPI backend, Gemini-powered agent, task state, docs lookup, asset pipeline
- `rive-docs/`
  - Local Rive documentation corpus used for grounding
- `rive-navigator-architecture.html`
  - Architecture and system overview document

## Quick Start

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Add your Gemini API key in `agent/.env`:

```env
GOOGLE_API_KEY=YOUR_API_KEY_HERE
```

3. Start the backend:

```bash
python -m uvicorn agent.server:app --reload --port 8000
```

4. Load the unpacked extension from `chrome-extension/` in `chrome://extensions`

5. Open the Rive editor and launch the side panel

For the full local setup walkthrough, see [SETUP.md](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/SETUP.md).

## Cloud Run Deployment

The backend is containerized and ready for Google Cloud Run.

```bash
gcloud run deploy rive-navigator \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=YOUR_API_KEY"
```

After deployment:

1. Copy the Cloud Run service URL
2. Open the extension's Options page
3. Set `Backend API URL` to your deployed service

The extension still defaults to `http://localhost:8000` for local development.

## Extra Docs

- Setup guide: [SETUP.md](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/SETUP.md)
- Architecture doc: [rive-navigator-architecture.html](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/rive-navigator-architecture.html)

