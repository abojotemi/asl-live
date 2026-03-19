from __future__ import annotations

import base64
import json
import threading
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

import cv2
import mediapipe as mp
import numpy as np
from ai_edge_litert.interpreter import Interpreter
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

MAX_FRAMES = 40
CONFIDENCE_THRESHOLD = 0.40

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "model" / "asl_word_light.tflite"
LABEL_MAP_PATH = BASE_DIR / "label_map.json"


class PredictRequest(BaseModel):
    image_base64: str = Field(
        ..., description="JPEG/PNG image in base64, no data URL header"
    )
    session_id: str | None = Field(default=None, description="Client session id")


class PredictResponse(BaseModel):
    session_id: str
    prediction: str
    confidence: float
    ready: bool
    frames_collected: int


class ResetRequest(BaseModel):
    session_id: str


def load_label_map(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Label map not found: {path}")

    raw = json.loads(path.read_text())
    pairs = sorted(((int(k), v) for k, v in raw.items()), key=lambda x: x[0])
    return [v for _, v in pairs]


def decode_image(base64_str: str) -> np.ndarray:
    try:
        image_bytes = base64.b64decode(base64_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc

    np_buf = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Image decode failed")
    return frame


def empty_hand() -> np.ndarray:
    return np.zeros((21, 3), dtype=np.float32)


def extract_hand_vector_from_frame(
    frame_bgr: np.ndarray, hands_model: mp.solutions.hands.Hands
) -> np.ndarray:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    result = hands_model.process(frame_rgb)

    left = empty_hand()
    right = empty_hand()

    if result.multi_hand_landmarks and result.multi_handedness:
        for hand_lm, handedness in zip(
            result.multi_hand_landmarks, result.multi_handedness
        ):
            pts = np.array(
                [[lm.x, lm.y, lm.z] for lm in hand_lm.landmark], dtype=np.float32
            )
            side = handedness.classification[0].label.lower()
            if side == "left":
                left = pts
            else:
                right = pts

    return np.concatenate([left.reshape(-1), right.reshape(-1)], axis=0)


if not MODEL_PATH.exists():
    raise RuntimeError(f"TFLite model not found at {MODEL_PATH}")

CLASS_NAMES = load_label_map(LABEL_MAP_PATH)

interpreter = Interpreter(model_path=str(MODEL_PATH))
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

mp_hands = mp.solutions.hands
hands_model = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

session_buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_FRAMES))
inference_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing extra needed
    yield
    # Shutdown: release MediaPipe resources
    hands_model.close()


app = FastAPI(title="ASL Live Inference API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8000",
        "https://asl-live.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "classes": CLASS_NAMES,
        "model_path": str(MODEL_PATH),
        "max_frames": MAX_FRAMES,
    }


@app.post("/reset")
def reset_session(payload: ResetRequest) -> dict:
    if payload.session_id in session_buffers:
        session_buffers[payload.session_id].clear()
    return {"ok": True}


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    session_id = payload.session_id or str(uuid4())
    buffer = session_buffers[session_id]

    frame = decode_image(payload.image_base64)
    frame = cv2.resize(frame, (320, 240))
    with inference_lock:
        feature = extract_hand_vector_from_frame(frame, hands_model)
    buffer.append(feature)

    frames_collected = len(buffer)
    if frames_collected < MAX_FRAMES:
        return PredictResponse(
            session_id=session_id,
            prediction="collecting",
            confidence=0.0,
            ready=False,
            frames_collected=frames_collected,
        )

    x = np.array(buffer, dtype=np.float32)[None, ...]
    with inference_lock:
        interpreter.set_tensor(input_details[0]["index"], x)
        interpreter.invoke()
        probs = interpreter.get_tensor(output_details[0]["index"])[0]

    idx = int(np.argmax(probs))
    conf = float(probs[idx])
    pred = CLASS_NAMES[idx] if idx < len(CLASS_NAMES) else "unknown"

    if conf < CONFIDENCE_THRESHOLD:
        pred = "uncertain"

    return PredictResponse(
        session_id=session_id,
        prediction=pred,
        confidence=conf,
        ready=True,
        frames_collected=frames_collected,
    )
