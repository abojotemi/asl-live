# ASL Live — Sign Language to Text/Audio Recognition System

This project is a real-time **American Sign Language (ASL)** word recognition system that captures sign gestures from a webcam, classifies them with a lightweight deep learning model, and provides text output suitable for audio rendering.

---

## 1) Input Layer (Capturing Sign Language)

### Hardware
- **Standard computer webcam** (via browser camera access using `getUserMedia`).
- No specialized gloves or depth sensors are required.

### Scope
- Target language: **American Sign Language (ASL)**.

### Complexity Level
- The system performs **dynamic gesture recognition at the word level**, not static alphabet classification.
- Current vocabulary contains 5 words:
	- `hello`
	- `thankyou`
	- `yes`
	- `no`
	- `sorry`

---

## 2) Processing Layer (System Analysis & Methodology)

### Computer Vision / Hand Tracking
- **MediaPipe Hands** is used for real-time landmark detection.
- For each frame:
	- Up to 2 hands are tracked.
	- Each hand provides 21 landmarks.
	- Each landmark has 3 coordinates (`x`, `y`, `z`).
- Feature size per frame:
	- $2 \times 21 \times 3 = 126$ features.

### Machine Learning Model (The Brain)
- A **custom-trained lightweight sequence model** was built in TensorFlow/Keras.
- Core architecture (training notebook):
	- Layer Normalization
	- Conv1D + MaxPooling
	- Conv1D
	- GRU
	- Dense layers + Softmax output
- The model is exported for deployment as **TensorFlow Lite** (`asl_word_light.tflite`) for efficient inference.

### Inference Strategy
- Real-time backend accumulates landmark frames into a sequence buffer.
- Sequence length is fixed at **40 frames** (`MAX_FRAMES = 40`).
- Prediction runs once enough temporal frames are collected.
- Confidence gating is used (`CONFIDENCE_THRESHOLD = 0.40`) to return `uncertain` when confidence is low.

### Dataset Source and Preparation
- Dataset workflow is notebook-driven (`asl_sign_words_lightweight_kaggle.ipynb`).
- Supports both:
	- raw videos (`.avi`, `.mp4`, etc.)
	- pre-extracted frame folders
- Includes preprocessing and balancing steps:
	- frame resizing / sampling
	- stratified train/val/test splitting
	- class weighting
	- minority oversampling with landmark jitter

---

## 3) Output Layer (Audio Conversion)

- The current backend returns **predicted text labels** through API responses.
- Frontend displays live prediction + confidence.
- For audio rendering, the intended flow is to pass predicted text into a TTS layer (e.g., browser SpeechSynthesis or server-side TTS library).

> Note: The present backend implementation focuses on robust sign-to-text prediction. TTS can be integrated as a straightforward extension.

---

## 4) Software Development Methodology

This project follows an **iterative, Agile-style prototyping approach**:

- Rapid experimentation in notebooks for model development and tuning.
- Incremental backend API integration (FastAPI) for live inference.
- Continuous frontend iteration (SvelteKit) for real-time UX.
- Deployment readiness through containerization and lightweight inference artifacts.

This approach supports quick feedback loops between:
1. model accuracy,
2. inference speed,
3. user interaction quality.

---

## System Stack Summary

- **Frontend:** SvelteKit + TypeScript
- **Backend:** FastAPI
- **Computer Vision:** OpenCV + MediaPipe Hands
- **ML Training/Inference:** TensorFlow / TensorFlow Lite
- **Data Processing:** NumPy, Pandas, scikit-learn

---

## Current API Endpoints

- `GET /health` — service/model status
- `POST /predict` — frame inference endpoint
- `POST /reset` — reset session buffer

---

## Project Goal

To provide an accessible, low-latency sign-language recognition pipeline that can be used in assistive communication scenarios and extended with speech synthesis for full sign-to-audio interaction.
