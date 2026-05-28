from __future__ import annotations

import base64
import io
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

import cv2
import mediapipe as mp
import numpy as np
import tensorflow as tf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from gtts import gTTS
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "model" / "asl_alphabet_mlp.tflite"
LABEL_MAP_PATH = BASE_DIR / "label_map.json"

FEATURE_DIM = 126
MIN_DETECTION_CONFIDENCE = 0.5
CONFIDENCE_THRESHOLD = 0.40


class PredictRequest(BaseModel):
    image_base64: str = Field(
        ..., description="JPEG/PNG image in base64, no data URL header"
    )


class PredictionCandidate(BaseModel):
    label: str
    confidence: float


class PredictResponse(BaseModel):
    prediction: str
    confidence: float
    hand_detected: bool
    detected_hands: int
    top_candidates: list[PredictionCandidate] = Field(default_factory=list)


def load_label_map(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Label map not found: {path}")

    raw = json.loads(path.read_text())
    pairs = sorted(((int(k), v) for k, v in raw.items()), key=lambda item: item[0])
    return [label for _, label in pairs]


def decode_image(base64_str: str) -> np.ndarray:
    cleaned = base64_str.split(",", 1)[-1]
    try:
        image_bytes = base64.b64decode(cleaned)
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
) -> tuple[np.ndarray, bool, int]:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    result = hands_model.process(frame_rgb)

    left = empty_hand()
    right = empty_hand()
    detected_hands = 0

    if result.multi_hand_landmarks and result.multi_handedness:
        detected_hands = len(result.multi_hand_landmarks)
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

    feature = np.concatenate([left.reshape(-1), right.reshape(-1)], axis=0)
    return feature, detected_hands > 0, detected_hands


if not MODEL_PATH.exists():
    raise RuntimeError(f"TFLite model not found at {MODEL_PATH}")

CLASS_NAMES = load_label_map(LABEL_MAP_PATH)

interpreter = tf.lite.Interpreter(model_path=str(MODEL_PATH))
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_dtype = input_details[0]["dtype"]

mp_hands = mp.solutions.hands
hands_model = mp_hands.Hands(
    static_image_mode=True,
    max_num_hands=2,
    min_detection_confidence=MIN_DETECTION_CONFIDENCE,
)

inference_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    hands_model.close()


app = FastAPI(title="ASL Alphabet MLP API", version="2.0.0", lifespan=lifespan)

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
async def health() -> dict:
    return {
        "status": "ok",
        "classes": CLASS_NAMES,
        "model_path": str(MODEL_PATH),
        "feature_dim": FEATURE_DIM,
        "inference_mode": "single-frame-landmarks",
        "min_detection_confidence": MIN_DETECTION_CONFIDENCE,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }


@app.post("/reset")
async def reset_session() -> dict:
    return {"ok": True, "message": "Single-frame model has no session buffer."}


@app.get("/tts")
async def text_to_speech(text: str = Query(..., description="Text to speak")):
    """Generate speech audio using Google TTS."""
    try:
        tts = gTTS(text=text, lang="en", tld="com")
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return Response(content=fp.getvalue(), media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail="TTS generation failed") from exc


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    frame = decode_image(payload.image_base64)
    frame = cv2.resize(frame, (320, 240))

    with inference_lock:
        feature, hand_detected, detected_hands = extract_hand_vector_from_frame(
            frame, hands_model
        )

    if not hand_detected:
        return PredictResponse(
            prediction="no_hand",
            confidence=0.0,
            hand_detected=False,
            detected_hands=0,
            top_candidates=[],
        )

    x = np.expand_dims(feature.astype(input_dtype, copy=False), axis=0)

    with inference_lock:
        interpreter.set_tensor(input_details[0]["index"], x)
        interpreter.invoke()
        probs = interpreter.get_tensor(output_details[0]["index"])[0]

    ranked = np.argsort(probs)[::-1]
    top_candidates = [
        PredictionCandidate(label=CLASS_NAMES[idx], confidence=float(probs[idx]))
        for idx in ranked[:3]
    ]

    best_idx = int(ranked[0])
    best_conf = float(probs[best_idx])
    prediction = CLASS_NAMES[best_idx]

    if best_conf < CONFIDENCE_THRESHOLD:
        prediction = "uncertain"

    return PredictResponse(
        prediction=prediction,
        confidence=best_conf,
        hand_detected=True,
        detected_hands=detected_hands,
        top_candidates=top_candidates,
    )
