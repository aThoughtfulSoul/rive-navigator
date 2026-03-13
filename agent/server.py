"""
API Server for Rive Navigator
Bridges the Chrome extension to the ADK agent.
Provides a REST endpoint that accepts screenshots + messages and returns agent responses.
"""

import asyncio
import base64
import io
import logging
import os
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types
from google.genai.errors import ClientError, ServerError

from agent import DEFAULT_MODEL, SUPPORTED_MODELS, build_agent, root_agent
from agent.asset_pipeline import (
    AssetNotFoundError,
    AssetPipelineError,
    DEFAULT_ASSET_PREVIEW_MODEL,
    create_asset_preview,
    vectorize_asset,
)
from agent.output_parser import parse_agent_output
from agent.prompting import build_runtime_package

# ============ Logging ============

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rive-navigator")
log.setLevel(logging.DEBUG)

# ============ FastAPI App ============

app = FastAPI(
    title="Rive Navigator API",
    description="AI-powered Rive editor assistant backend",
    version="1.0.0",
)

# Allow CORS for Chrome extension and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to extension ID
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ ADK Setup ============

session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()

runner = Runner(
    agent=root_agent,
    app_name="rive_navigator",
    session_service=session_service,
    artifact_service=artifact_service,
)
runners: dict[str, Runner] = {DEFAULT_MODEL: runner}

# ============ Gemini TTS Setup ============

try:
    from google import genai
    from google.genai import types as genai_types
    tts_client = genai.Client()
    gemini_client = tts_client
    tts_available = True
    log.info("Gemini TTS client initialized (using GOOGLE_API_KEY)")
except Exception as e:
    tts_client = None
    gemini_client = None
    tts_available = False
    log.warning(f"Gemini TTS not available: {e}")

# Track active sessions
active_sessions: dict[str, bool] = {}
save_debug_screenshots = os.getenv("SAVE_DEBUG_SCREENSHOTS", "0") == "1"
attach_rive_doc_images = os.getenv("ATTACH_RIVE_DOC_IMAGES", "1") == "1"
asset_preview_timeout_seconds = float(os.getenv("ASSET_PREVIEW_TIMEOUT_SECONDS", "75"))


# ============ Request/Response Models ============

class ChatRequest(BaseModel):
    message: str
    screenshot: Optional[str] = None  # base64 data URL
    dom_context: Optional[dict] = None
    session_id: Optional[str] = None
    user_id: str = "default_user"
    task_mode: str = "collaborative"  # "collaborative" or "agentic"
    model: Optional[str] = None


class TaskState(BaseModel):
    active: bool = False
    name: str = ""
    current_step: int = 0
    total_steps: int = 0
    current_step_name: str = ""
    completed: bool = False


class CursorTarget(BaseModel):
    x: float = 0
    y: float = 0
    label: str = ""


class ActionCommand(BaseModel):
    type: str = ""          # click, doubleclick, key, type, drag, wait
    x: Optional[float] = None
    y: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    key: Optional[str] = None
    modifiers: Optional[str] = None
    text: Optional[str] = None
    label: str = ""
    duration: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    step_count: int = 0
    task_state: Optional[TaskState] = None
    cursor_target: Optional[CursorTarget] = None
    action: Optional[ActionCommand] = None
    warnings: list[str] = []
    needs_retry: bool = False


class AssetPreviewRequest(BaseModel):
    prompt: str
    style: str = "sticker"


class AssetPreviewResponse(BaseModel):
    asset_id: str
    preview_data_url: str
    revised_prompt: str = ""
    model: str = DEFAULT_ASSET_PREVIEW_MODEL


class AssetVectorizeRequest(BaseModel):
    asset_id: str


class AssetVectorizeResponse(BaseModel):
    asset_id: str
    sanitized_svg: str
    stats: dict[str, object] = {}


# ============ Endpoints ============

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Accepts a message, optional screenshot, and optional DOM context.
    Returns the agent's response.
    """
    request_start = time.time()
    log.info("=" * 60)
    log.info(f"📩 INCOMING REQUEST")
    log.info(f"   Message: {request.message[:100]}{'...' if len(request.message) > 100 else ''}")
    log.info(f"   Screenshot: {'YES (' + str(len(request.screenshot) // 1024) + ' KB)' if request.screenshot else 'NO'}")
    log.info(f"   Task mode: {request.task_mode}")
    log.info(f"   Requested model: {request.model or DEFAULT_MODEL}")
    log.info(f"   Session: {request.session_id or 'new'}")

    try:
        request_task_mode = _normalize_task_mode(request.task_mode)

        # Get or create session
        session_id = request.session_id or str(uuid.uuid4())
        user_id = request.user_id
        session_state: dict | None = None

        if session_id not in active_sessions:
            log.info(f"🆕 Creating new session: {session_id[:20]}...")
            session_state = _default_session_state(request_task_mode)
            await session_service.create_session(
                app_name="rive_navigator",
                user_id=user_id,
                session_id=session_id,
                state=session_state,
            )
            active_sessions[session_id] = True
        else:
            log.info(f"♻️  Reusing session: {session_id[:20]}...")
            # Update task_mode in session state (user can switch mid-task)
            session = await session_service.get_session(
                app_name="rive_navigator",
                user_id=user_id,
                session_id=session_id,
            )
            if session:
                session.state["task_mode"] = request_task_mode
                session_state = session.state
            else:
                session_state = _default_session_state(request_task_mode)
                await session_service.create_session(
                    app_name="rive_navigator",
                    user_id=user_id,
                    session_id=session_id,
                    state=session_state,
                )
                active_sessions[session_id] = True
        if session_state is not None:
            session_state["task_mode"] = request_task_mode

        request_model = _normalize_model_name(
            request.model or (session_state or {}).get("model_name", DEFAULT_MODEL)
        )
        log.info(f"   Model: {request_model}")
        if session_state is not None:
            session_state["model_name"] = request_model

        # Build message parts
        parts = []
        runtime_package = build_runtime_package(
            user_message=request.message,
            task_mode=request_task_mode,
            session_state=session_state,
        )
        runtime_context = runtime_package["text"]
        doc_visuals = runtime_package["doc_visuals"] if attach_rive_doc_images else []

        if runtime_context:
            parts.append(types.Part.from_text(text=runtime_context))

        # Add the user's text message
        parts.append(types.Part.from_text(text=f"[USER REQUEST]\n{request.message}"))

        # Add screenshot if provided
        if request.screenshot:
            image_bytes = _decode_screenshot(request.screenshot)
            if image_bytes:
                log.info(f"🖼️  Screenshot decoded: {len(image_bytes) // 1024} KB")

                if save_debug_screenshots:
                    debug_dir = os.path.join(os.path.dirname(__file__), "..", "debug_screenshots")
                    os.makedirs(debug_dir, exist_ok=True)
                    timestamp = time.strftime("%H%M%S")
                    debug_path = os.path.join(debug_dir, f"{timestamp}.png")
                    with open(debug_path, "wb") as f:
                        f.write(image_bytes)
                    log.info(f"💾 Screenshot saved: debug_screenshots/{timestamp}.png")

                parts.append(
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/png",
                    )
                )
            else:
                log.warning("⚠️  Screenshot decode FAILED")

        attached_doc_visuals = 0
        for doc_visual in doc_visuals:
            image_part = _build_doc_visual_part(doc_visual)
            if image_part is None:
                continue
            parts.append(image_part)
            attached_doc_visuals += 1
        if attached_doc_visuals:
            log.info(f"📚 Attached {attached_doc_visuals} Rive doc visual reference image(s)")

        # Add DOM context as structured text
        if request.dom_context:
            dom_text = _format_dom_context(request.dom_context)
            log.info(f"🌳 DOM context: {dom_text[:150]}...")
            parts.append(
                types.Part.from_text(
                    text=f"\n\n[DOM CONTEXT from Chrome extension]\n{dom_text}"
                )
            )

        # Create the content message
        content = types.Content(role="user", parts=parts)
        doc_visual_suffix = (
            f" + {attached_doc_visuals} doc visual{'s' if attached_doc_visuals != 1 else ''}"
            if attached_doc_visuals
            else ""
        )
        log.info(
            f"📤 Sending to Gemini ({len(parts)} parts: text{' + image' if request.screenshot else ''}"
            f"{doc_visual_suffix}{' + DOM' if request.dom_context else ''})..."
        )

        # Run the agent
        agent_response = ""
        event_count = 0
        gemini_start = time.time()

        active_runner = _get_runner_for_model(request_model)

        async for event in active_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            event_count += 1
            # Log every event so you can see the agent working
            event_type = type(event).__name__
            if hasattr(event, 'actions') and event.actions:
                for action in event.actions:
                    if hasattr(action, 'tool_name'):
                        log.info(f"   🔧 Tool call: {action.tool_name}()")
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            agent_response += part.text

        gemini_elapsed = time.time() - gemini_start
        log.info(f"📥 Gemini responded in {gemini_elapsed:.1f}s ({event_count} events)")
        log.info(f"   Response preview: {agent_response[:150]}{'...' if len(agent_response) > 150 else ''}")

        # Get session state (step count + task state)
        session = await session_service.get_session(
            app_name="rive_navigator",
            user_id=user_id,
            session_id=session_id,
        )

        step_count = session.state.get("step_count", 0) if session else 0

        # Build task state for the frontend
        task_state = None
        if session:
            session.state["task_mode"] = request_task_mode
            task_active = session.state.get("task:active", False)
            task_state = TaskState(
                active=task_active,
                name=session.state.get("task:name", ""),
                current_step=session.state.get("task:current_step", 0),
                total_steps=session.state.get("task:total_steps", 0),
                current_step_name=session.state.get("task:current_step_name", ""),
                completed=not task_active and session.state.get("task:name", "") != "",
            )
            if task_active:
                log.info(f"   📋 Task mode: step {task_state.current_step}/{task_state.total_steps} — {task_state.current_step_name}")

        # Parse and validate structured output
        cursor_target = None
        action_cmd = None
        task_active = task_state.active if task_state else False
        parsed_output = parse_agent_output(
            text=agent_response,
            task_mode=request_task_mode,
            task_active=task_active,
        )
        agent_response = parsed_output.cleaned_text
        for warning in parsed_output.warnings:
            log.warning(f"⚠️  {warning}")

        if parsed_output.cursor:
            cursor_target = CursorTarget(**parsed_output.cursor)
        if parsed_output.action:
            action_cmd = ActionCommand(**parsed_output.action)

        if session:
            session.state["last_validation_error"] = parsed_output.warnings[-1] if parsed_output.warnings else ""
            session.state["last_agent_response_preview"] = (agent_response or "")[:300]
            if parsed_output.action:
                session.state["last_action_label"] = parsed_output.action.get("label", "")
                session.state["last_action_type"] = parsed_output.action.get("type", "")

        needs_retry = bool(
            parsed_output.warnings
            and task_active
            and request_task_mode == "agentic"
            and action_cmd is None
        )

        total_elapsed = time.time() - request_start
        log.info(f"✅ DONE — total: {total_elapsed:.1f}s (Gemini: {gemini_elapsed:.1f}s)")
        log.info("=" * 60)

        return ChatResponse(
            response=agent_response or _fallback_response(request_task_mode, task_active, parsed_output.warnings),
            session_id=session_id,
            step_count=step_count,
            task_state=task_state,
            cursor_target=cursor_target,
            action=action_cmd,
            warnings=parsed_output.warnings,
            needs_retry=needs_retry,
        )

    except Exception as e:
        elapsed = time.time() - request_start
        log.error(f"❌ ERROR after {elapsed:.1f}s: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    log.info("💚 Health check OK")
    return {
        "status": "ok",
        "agent": "rive_navigator",
        "default_model": DEFAULT_MODEL,
        "supported_models": sorted(SUPPORTED_MODELS),
    }


@app.post("/api/assets/preview", response_model=AssetPreviewResponse)
async def asset_preview(request: AssetPreviewRequest):
    prompt = " ".join((request.prompt or "").split())
    if not prompt:
        raise HTTPException(status_code=400, detail="Asset prompt cannot be empty.")
    if gemini_client is None:
        raise HTTPException(status_code=503, detail="Gemini image generation is not configured on the backend.")

    log.info("🖼️  ASSET PREVIEW REQUEST")
    log.info(f"   Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    log.info(f"   Style: {request.style}")
    log.info(f"   Model: {DEFAULT_ASSET_PREVIEW_MODEL}")

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                create_asset_preview,
                prompt=prompt,
                style=request.style,
                image_client=gemini_client,
            ),
            timeout=asset_preview_timeout_seconds,
        )
        return AssetPreviewResponse(**result)
    except asyncio.TimeoutError as exc:
        log.warning(f"⚠️  Asset preview timed out after {asset_preview_timeout_seconds:.0f}s")
        raise HTTPException(
            status_code=504,
            detail=f"Image generation timed out after {asset_preview_timeout_seconds:.0f}s. Please try again.",
        ) from exc
    except AssetPipelineError as exc:
        log.warning(f"⚠️  Asset preview failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServerError as exc:
        status_code = getattr(exc, "status_code", None) or 503
        if status_code == 503:
            log.warning("⚠️  Asset preview upstream overload: Gemini image model unavailable")
            raise HTTPException(
                status_code=503,
                detail="Gemini image generation is temporarily overloaded. Please try again in a moment.",
            ) from exc
        log.error(f"❌ Asset preview upstream server error: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail="Gemini image generation failed upstream.") from exc
    except Exception as exc:
        log.error(f"❌ Asset preview generation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Asset preview generation failed.") from exc


@app.post("/api/assets/vectorize", response_model=AssetVectorizeResponse)
async def asset_vectorize(request: AssetVectorizeRequest):
    try:
        result = vectorize_asset(request.asset_id)
        return AssetVectorizeResponse(**result)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AssetPipelineError as exc:
        log.warning(f"⚠️  Asset vectorization failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.error(f"❌ Asset vectorization failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Asset vectorization failed.") from exc


@app.post("/api/session/reset")
async def reset_session(session_id: str, user_id: str = "default_user"):
    """Resets a session, clearing all state."""
    try:
        log.info(f"🔄 Resetting session: {session_id[:20]}...")
        if session_id in active_sessions:
            del active_sessions[session_id]

        await session_service.create_session(
            app_name="rive_navigator",
            user_id=user_id,
            session_id=session_id,
            state=_default_session_state("collaborative"),
        )
        active_sessions[session_id] = True

        return {"status": "ok", "session_id": session_id}
    except Exception as e:
        log.error(f"❌ Session reset failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ TTS Endpoint ============

class TTSRequest(BaseModel):
    text: str
    voice: str = "Kore"  # Prebuilt voice name (Kore, Puck, Leda, Charon, etc.)


class TTSResponse(BaseModel):
    audio_base64: str      # base64-encoded WAV audio
    duration_estimate: float  # rough estimate in seconds


def _build_tts_prompt(text: str, strict: bool = False) -> str:
    if strict:
        return (
            "Generate speech audio only. Do not answer the user, do not add text, and do not paraphrase.\n"
            "Read the following transcript exactly as written.\n\n"
            f"Transcript:\n{text}"
        )

    return (
        "Read aloud the following transcript and return audio only.\n\n"
        f"Transcript:\n{text}"
    )


def _pcm_to_wav_base64(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> str:
    """Wraps raw PCM bytes in a WAV header and returns base64-encoded WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


@app.post("/api/tts", response_model=TTSResponse)
async def text_to_speech(request: TTSRequest):
    """
    Converts text to speech using Gemini's native TTS model.
    Returns base64-encoded WAV audio.
    """
    if not tts_available or not tts_client:
        raise HTTPException(status_code=503, detail="TTS not available (check GOOGLE_API_KEY)")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    # Safety cap per sentence (client sends individual sentences via pipelining)
    if len(text) > 500:
        text = text[:500]

    try:
        tts_start = time.time()
        last_error: Exception | None = None

        for strict_prompt in (False, True):
            try:
                response = tts_client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts",
                    contents=_build_tts_prompt(text, strict=strict_prompt),
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=genai_types.SpeechConfig(
                            voice_config=genai_types.VoiceConfig(
                                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                    voice_name=request.voice,
                                )
                            )
                        )
                    ),
                )

                candidate = response.candidates[0]
                raw_data = candidate.content.parts[0].inline_data.data

                if isinstance(raw_data, str):
                    pcm_bytes = base64.b64decode(raw_data)
                else:
                    pcm_bytes = raw_data

                wav_b64 = _pcm_to_wav_base64(pcm_bytes)
                duration_estimate = len(pcm_bytes) / (24000 * 2 * 1)
                tts_elapsed = time.time() - tts_start
                log.info(
                    f"🔊 TTS: {len(text)} chars → {len(pcm_bytes)//1024}KB PCM → {tts_elapsed:.1f}s ({request.voice})"
                )

                return TTSResponse(
                    audio_base64=wav_b64,
                    duration_estimate=round(duration_estimate, 1),
                )
            except ClientError as e:
                last_error = e
                error_message = str(e)
                is_tts_prompt_error = "should only be used for TTS" in error_message or "INVALID_ARGUMENT" in error_message
                if strict_prompt or not is_tts_prompt_error:
                    raise
                log.warning("TTS prompt was rejected; retrying with stricter audio-only instructions.")
            except Exception as e:
                last_error = e
                raise

        if last_error:
            raise last_error

    except Exception as e:
        log.error(f"❌ TTS failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")


# ============ Helper Functions ============

def _default_session_state(task_mode: str) -> dict:
    return {
        "step_count": 0,
        "last_observation": "none yet",
        "last_action_label": "",
        "last_action_type": "",
        "last_validation_error": "",
        "last_agent_response_preview": "",
        "user:skill_level": "intermediate",
        "model_name": DEFAULT_MODEL,
        "task_mode": task_mode,
        "task:last_direction": "none",
        "task:last_feedback": "",
        "task:last_verification": "not_started",
        "task:last_verification_feedback": "",
    }


def _normalize_task_mode(task_mode: str) -> str:
    normalized = (task_mode or "").strip().lower()
    if normalized in {"agentic", "collaborative"}:
        return normalized
    return "collaborative"


def _normalize_model_name(model_name: str | None) -> str:
    normalized = (model_name or "").strip()
    if normalized in SUPPORTED_MODELS:
        return normalized
    return DEFAULT_MODEL


def _get_runner_for_model(model_name: str) -> Runner:
    runner_for_model = runners.get(model_name)
    if runner_for_model is not None:
        return runner_for_model

    runner_for_model = Runner(
        agent=build_agent(model_name),
        app_name="rive_navigator",
        session_service=session_service,
        artifact_service=artifact_service,
    )
    runners[model_name] = runner_for_model
    return runner_for_model


def _fallback_response(task_mode: str, task_active: bool, warnings: list[str]) -> str:
    if warnings and task_active and task_mode == "agentic":
        return "I need to reassess the editor state before taking another action."
    if warnings and task_active and task_mode == "collaborative":
        return "I need to refine the next step before pointing you at the UI."
    return "I couldn't generate a response. Try rephrasing your question."


def _build_doc_visual_part(doc_visual: dict) -> Optional[types.Part]:
    local_path = str(doc_visual.get("local_path", "")).strip()
    mime_type = str(doc_visual.get("mime_type", "")).strip()
    if not local_path or not mime_type.startswith("image/"):
        return None

    image_path = Path(local_path)
    if not image_path.exists() or not image_path.is_file():
        return None

    try:
        file_size = image_path.stat().st_size
        if file_size <= 0 or file_size > 2_500_000:
            return None
        return types.Part.from_bytes(
            data=image_path.read_bytes(),
            mime_type=mime_type,
        )
    except Exception as exc:
        log.warning(f"⚠️  Failed to attach doc visual {image_path.name}: {exc}")
        return None


def _decode_screenshot(data_url: str) -> Optional[bytes]:
    """Decodes a base64 data URL to raw bytes."""
    try:
        if data_url.startswith("data:"):
            # Strip the data URL prefix (e.g., "data:image/png;base64,")
            header, b64_data = data_url.split(",", 1)
            return base64.b64decode(b64_data)
        else:
            # Assume raw base64
            return base64.b64decode(data_url)
    except Exception as e:
        log.error(f"Failed to decode screenshot: {e}")
        return None


def _format_dom_context(dom_context: dict) -> str:
    """Formats DOM context dict into a readable string for the agent."""
    lines = []

    if dom_context.get("panels"):
        lines.append(f"Visible panels: {', '.join(dom_context['panels'])}")

    if dom_context.get("selectedTool") and dom_context["selectedTool"] != "unknown":
        lines.append(f"Active tool: {dom_context['selectedTool']}")

    if dom_context.get("hierarchy"):
        hierarchy = dom_context["hierarchy"]
        if isinstance(hierarchy, list) and len(hierarchy) > 0:
            items = []
            for item in hierarchy[:15]:  # Limit
                prefix = "  " * item.get("depth", 0)
                marker = " [SELECTED]" if item.get("selected") else ""
                items.append(f"{prefix}{item.get('name', '?')}{marker}")
            lines.append(f"Hierarchy:\n" + "\n".join(items))

    if dom_context.get("inspector"):
        inspector = dom_context["inspector"]
        if isinstance(inspector, dict) and len(inspector) > 0:
            props = [f"  {k}: {v}" for k, v in list(inspector.items())[:10]]
            lines.append(f"Inspector properties:\n" + "\n".join(props))

    if dom_context.get("timeline", {}).get("visible"):
        tl = dom_context["timeline"]
        lines.append(f"Timeline: frame {tl.get('currentFrame', '?')}, "
                      f"{len(tl.get('keyframes', []))} keyframes visible")

    if dom_context.get("stateMachine", {}).get("visible"):
        sm = dom_context["stateMachine"]
        states = [s.get("name", "?") for s in sm.get("states", [])]
        lines.append(f"State Machine: states=[{', '.join(states)}], "
                      f"inputs={len(sm.get('inputs', []))}")

    if dom_context.get("viewport"):
        vp = dom_context["viewport"]
        lines.append(f"Viewport: {vp.get('windowWidth')}x{vp.get('windowHeight')}")

    return "\n".join(lines) if lines else "No DOM context available."


# ============ Run ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
