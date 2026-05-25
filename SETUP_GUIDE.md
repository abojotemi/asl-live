# ASL Live Project - Complete Setup Guide

## Project Overview

**ASL Live** is a real-time American Sign Language (ASL) recognition system that:
- Captures sign gestures via webcam
- Uses MediaPipe for hand tracking
- Classifies gestures with a lightweight TensorFlow model
- Provides real-time text output with confidence scores
- Supports audio output via Text-to-Speech (TTS)

**Supported Words:** hello, thankyou, yes, no, sorry

**GitHub Repository:** https://github.com/abojotemi/asl-live.git

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Frontend (SvelteKit)                   │
│         - Webcam access via getUserMedia API            │
│         - Real-time video feed display                  │
│         - Live prediction & confidence display          │
└─────────────────┬──────────────────────────────────────┘
                  │ HTTP/REST API
┌─────────────────▼──────────────────────────────────────┐
│              Backend (FastAPI)                          │
│  - Hand tracking with MediaPipe                         │
│  - TensorFlow Lite inference engine                     │
│  - Frame buffering (40-frame sequences)                 │
│  - CORS-enabled endpoints                              │
└─────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### System Requirements
- **OS:** Windows, macOS, or Linux
- **Python:** 3.9 or higher
- **Node.js:** 18.x or higher (for frontend)
- **npm:** 9.x or higher
- **Webcam:** Required for real-time sign capture
- **RAM:** Minimum 4GB (8GB recommended)
- **Disk Space:** 2GB for dependencies and model

### Software Tools
- Git
- A code editor (VS Code, PyCharm, etc.)
- Docker (optional, for containerized deployment)

---

## Installation & Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/abojotemi/asl-live.git
cd asl-live
```

---

### Step 2: Backend Setup

#### 2.1 Create Python Virtual Environment

```bash
cd backend

# On macOS/Linux:
python3 -m venv venv
source venv/bin/activate

# On Windows:
python -m venv venv
venv\Scripts\activate
```

#### 2.2 Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies Include:**
- `fastapi[standard]` - Web framework
- `numpy` - Numerical computations
- `opencv-python-headless` - Computer vision
- `mediapipe` - Hand tracking (v0.10.14)
- `tensorflow-cpu` - ML inference (v2.18.0)
- `gTTS` - Text-to-Speech

#### 2.3 Verify Backend Setup

```bash
cd backend
python -c "import tensorflow, mediapipe; print('Backend dependencies OK')"
```

#### 2.4 Start Backend Server

```bash
# From the backend directory with venv activated:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

**Backend API Endpoints:**
- `GET /health` - Health check and available classes
- `POST /predict` - Submit frame for prediction
- `POST /reset` - Clear session buffer

---

### Step 3: Frontend Setup

#### 3.1 Navigate to Frontend Directory

```bash
cd ../frontend
```

#### 3.2 Install Node Dependencies

```bash
npm install
```

#### 3.3 Start Development Server

```bash
npm run dev
```

**Expected Output:**
```
  VITE v7.3.1  ready in XXX ms

  ➜  Local:   http://localhost:5173/
  ➜  press h to show help
```

#### 3.4 Access the Application

Open your browser and navigate to:
```
http://localhost:5173
```

---

## Running the Complete System

### Startup Sequence

1. **Start Backend** (Terminal 1):
   ```bash
   cd backend
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Start Frontend** (Terminal 2):
   ```bash
   cd frontend
   npm run dev
   ```

3. **Open Browser:**
   Navigate to `http://localhost:5173`

4. **Grant Permissions:**
   - Browser will request webcam access
   - Click "Allow" to enable camera capture

### Using the Application

1. Point your webcam at the camera feed
2. Perform ASL signs from the supported vocabulary
3. The system will collect 40 frames and make predictions
4. View real-time results and confidence scores
5. Optional: Click to generate audio output of predicted text

---

## Backend API Reference

### Health Check

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "ok",
  "classes": ["hello", "thankyou", "yes", "no", "sorry"]
}
```

### Make Prediction

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "image_base64": "...",
    "session_id": "user-123"
  }'
```

**Response:**
```json
{
  "session_id": "user-123",
  "prediction": "hello",
  "confidence": 0.87,
  "ready": true,
  "frames_collected": 40
}
```

### Reset Session

```bash
curl -X POST http://localhost:8000/reset \
  -H "Content-Type: application/json" \
  -d '{"session_id": "user-123"}'
```

---

## Docker Deployment (Optional)

### Build and Run with Docker

```bash
# From project root directory:
docker build -f backend/Dockerfile -t asl-backend .
docker run -p 8000:8000 asl-backend
```

### Docker Compose (if available)

```bash
docker-compose up
```

---

## Configuration

### Backend Configuration (main.py)

```python
MAX_FRAMES = 40              # Sequence length for predictions
CONFIDENCE_THRESHOLD = 0.40  # Minimum confidence to return prediction
```

### Model Location
- **TFLite Model:** `backend/model/asl_word_light.tflite`
- **Label Mapping:** `backend/label_map.json`
- **Keras Model (optional):** `backend/model/best_asl_word_model.keras`

### Frontend Configuration

- **Backend URL:** Update in frontend if not localhost:8000
- **Port:** Default `5173` (Vite dev server)

---

## Troubleshooting

### Backend Issues

| Issue | Solution |
|-------|----------|
| ModuleNotFoundError: tensorflow | Ensure venv is activated and dependencies installed: `pip install -r requirements.txt` |
| Port 8000 already in use | Change port: `uvicorn main:app --port 8001` |
| CORS errors | Backend has CORS middleware enabled for all origins |
| Slow inference | Use CPU-optimized model; consider GPU version for faster inference |

### Frontend Issues

| Issue | Solution |
|-------|----------|
| Cannot connect to backend | Verify backend running on port 8000; check `CORS policy` |
| Webcam not detected | Check browser permissions (Settings → Privacy → Camera) |
| VITE dev server won't start | Ensure port 5173 is free: `npm run dev -- --port 5174` |
| Blank page | Check browser console for errors (F12 → Console tab) |

### General

| Issue | Solution |
|-------|----------|
| Predictions always "uncertain" | Ensure good lighting; hold sign steady for full 40 frames |
| Connection refused | Verify both services are running in separate terminals |
| High latency | Check system resources; close other applications |

---

## Development Workflow

### Training New Models

Notebooks included for model experimentation:
- `asl_sign_words_lightweight_kaggle.ipynb` - Primary training notebook
- `asl-tf.ipynb` - Additional TensorFlow experiments

### Making Code Changes

**Backend:**
```bash
cd backend
source venv/bin/activate
# Edit main.py
# Changes auto-reload with --reload flag
```

**Frontend:**
```bash
cd frontend
npm run dev
# Vite automatically hot-reloads on save
```

### Building for Production

**Frontend:**
```bash
npm run build
# Outputs to build/ directory
```

**Backend:**
- Use production-grade server (Gunicorn + Uvicorn)
- Set environment variables for secrets
- Deploy with Docker for consistency

---

## Project Structure

```
asl-live/
├── backend/                    # FastAPI backend
│   ├── main.py                # FastAPI app & inference logic
│   ├── requirements.txt        # Python dependencies
│   ├── label_map.json         # Class label mapping
│   ├── Dockerfile             # Container configuration
│   ├── model/
│   │   ├── asl_word_light.tflite
│   │   └── best_asl_word_model.keras
│   └── asl_saved_model/       # SavedModel format
│
├── frontend/                   # SvelteKit frontend
│   ├── src/
│   │   ├── routes/            # Page components
│   │   └── lib/               # Shared components
│   ├── package.json           # Node dependencies
│   └── vite.config.ts         # Vite configuration
│
├── README.md                  # Project documentation
└── *.ipynb                    # Jupyter notebooks for training

```

---

## Performance Tips

### Optimize Backend
- Use CPU-optimized TensorFlow: `tensorflow-cpu` (already configured)
- For GPU acceleration: Install `tensorflow-gpu` and CUDA drivers
- Monitor frame buffer size with `CONFIDENCE_THRESHOLD`

### Optimize Frontend
- Reduce video resolution if performance is poor
- Use browser DevTools to profile performance

### Network Optimization
- Both services on same machine = minimal latency
- For distributed setup, minimize frame compression loss

---

## Support & Resources

### Useful Links
- **FastAPI Documentation:** https://fastapi.tiangolo.com/
- **MediaPipe Hands:** https://developers.google.com/mediapipe/solutions/vision/hand_landmarker
- **TensorFlow Lite:** https://www.tensorflow.org/lite
- **SvelteKit:** https://kit.svelte.dev/

### Common Questions

**Q: How do I add new words to the vocabulary?**
A: Retrain the model using `asl_sign_words_lightweight_kaggle.ipynb` with new word data, then replace the model files.

**Q: Can this work on mobile?**
A: Frontend works on mobile browsers with camera access. Backend requires server deployment.

**Q: How accurate is the model?**
A: Current model achieves high accuracy on trained vocabulary. Performance depends on video quality and sign clarity.

**Q: Can I use this offline?**
A: Yes! Both frontend and backend can run locally without internet (after initial installation).

---

## Version Information

- **Python:** 3.9+
- **Node.js:** 18.x+
- **FastAPI:** Latest (included in fastapi[standard])
- **TensorFlow:** 2.18.0 (CPU)
- **MediaPipe:** 0.10.14
- **SvelteKit:** 2.50.2+

---

## Next Steps

1. ✅ Clone repository and follow setup steps
2. ✅ Start backend service
3. ✅ Start frontend service
4. ✅ Access application in browser
5. 📝 Grant webcam permissions
6. 🎯 Test with ASL signs
7. 🔄 Iterate and improve

---

## License & Attribution

This project is part of the ASL recognition research initiative. See repository for license details.

**Repository:** https://github.com/abojotemi/asl-live.git

---

*Setup Guide Generated: May 2026*
*For latest updates, visit the GitHub repository*
