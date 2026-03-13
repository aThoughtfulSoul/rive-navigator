# Rive Navigator

Rive Navigator is a multimodal AI copilot for the Rive editor. It sees the editor through screenshots, answers questions about the current UI, guides users step by step, executes trusted browser actions inside Rive, narrates its responses, and can generate prompt-based SVG assets that are traced, sanitized, and pasted directly into the editor for animation.

## Project Summary

Rive is powerful, but it has a steep learning curve and a dense editor interface. Rive Navigator is built to reduce that friction. Instead of making users leave the editor to search docs or guess through complex panels, the agent stays inside the workflow. It can explain what is on screen, walk a user through a task, take over repetitive editor actions in agentic mode, and even bootstrap new visual assets through a prompt-to-SVG pipeline.

The project is designed around the `UI Navigator` challenge category: the product understands a live professional UI, reasons over screenshots, and produces executable actions inside that UI in real time.

## Core Features

- Screenshot-based understanding of the live Rive editor
- Collaborative mode for guided, step-by-step help
- Agentic mode for trusted action execution inside Rive
- Keyboard-shortcut-first action strategy where possible
- Voice narration with Gemini TTS plus subtitle overlays
- Local Rive docs grounding with targeted retrieval and reference visuals
- Prompt-to-SVG asset generation workflow:
  - generate preview image
  - trace with `vtracer`
  - sanitize for Rive
  - paste SVG directly into the editor

## Technologies Used

- Chrome Extension (Manifest V3)
- FastAPI
- Google ADK
- Gemini models
  - `gemini-3-flash-preview`
  - `gemini-3.1-pro-preview`
  - `gemini-3-pro-image-preview`
  - `gemini-2.5-flash-preview-tts`
- Google Cloud Run
- Cloud Build / Artifact Registry
- `vtracer` for raster-to-SVG conversion
- Local Rive documentation corpus for grounding

## Data Sources

The project uses the following data sources:

- Live screenshots captured from the Rive editor tab
- A local copy of Rive documentation under `rive-docs/`
- Image references extracted from relevant Rive docs when useful
- User prompts and live task state stored in the current session

No external database is required for the current version.

## Key Learnings

- Smaller models like Flash improve a lot when prompt mass is reduced and runtime context is more targeted.
- UI agents need strict output validation and recovery handling; otherwise small formatting mismatches break the loop.
- Some basic editor operations should always be available as core guidance rather than relying entirely on retrieval.
- Prompt-to-SVG generation is much more reliable when constrained to simple, flat, vector-friendly assets.
- Trusted browser input via Chrome DevTools Protocol is critical for reliable Rive editor automation.

## Repo Structure

- `agent/`
  - FastAPI backend, Gemini agent, action parsing, task state, docs lookup, asset pipeline
- `chrome-extension/`
  - sidebar UI, screenshot capture, CDP action execution, SVG paste import, extension options
- `rive-docs/`
  - local Rive documentation corpus used for grounding
- `rive-navigator-architecture.html`
  - architecture and data-flow documentation
- `SETUP.md`
  - expanded local setup and deployment notes

## Local Setup

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

For the fuller setup walkthrough, see [SETUP.md](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/SETUP.md).

## Google Cloud Deployment

The backend is deployed on Google Cloud Run.

Deploy command:

```bash
gcloud run deploy rive-navigator \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=YOUR_API_KEY"
```

The current deployed service URL is:

`https://rive-navigator-443266620050.us-central1.run.app`

The extension defaults to `http://localhost:8000` for local development. To use the deployed backend instead:

1. Open `chrome://extensions`
2. Find `Rive UI Navigator`
3. Open `Details`
4. Open `Extension options`
5. Set `Backend API URL` to the deployed Cloud Run URL

## Judge Setup

For judges or reviewers reproducing the project:

1. Load the unpacked extension from `chrome-extension/`
2. Open the extension options page
3. Set `Backend API URL` to the deployed Cloud Run backend URL provided above
4. Open the Rive editor in Chrome
5. Launch the side panel and test chat, guidance, or agentic tasks

If a local backend is preferred instead, use the Local Setup section and leave the extension backend URL on `http://localhost:8000`.

## Proof of Google Cloud Usage

This project uses Google Cloud in two ways:

- the backend is deployed on Google Cloud Run
- the product uses Gemini models via Google's SDKs and APIs

For the submission package, the recommended proof artifact is:

- a short screen recording showing the `rive-navigator` Cloud Run service in the Google Cloud Console or its logs while the app is running

## Architecture

Architecture and system diagrams are documented in:

- [rive-navigator-architecture.html](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/rive-navigator-architecture.html)

This file is intended to be included in the submission materials and image carousel.

## Known Limitations

- The agent is strongest on clear editor states and repeatable workflows.
- Very complex traced SVGs may be rejected before import for reliability reasons.
- Some long-horizon or ambiguous Rive tasks still perform better on `Gemini 3.1 Pro` than on Flash.
- The current version uses in-memory session state rather than durable persistence.

## Extra Docs

- Setup guide: [SETUP.md](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/SETUP.md)
- Architecture doc: [rive-navigator-architecture.html](/Users/devonbulgin/Documents/ForClaude/GeminiHackathon/rive-navigator/rive-navigator-architecture.html)

