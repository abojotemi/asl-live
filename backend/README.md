# ASL Backend (FastAPI)

This backend now serves the ASL alphabet notebook model:

- MediaPipe extracts 126 landmark features from each frame
- the Dense MLP classifies the frame as one of `A`–`Z`
- inference is instant per frame, not sequence-based

## Run

Install dependencies (pick one flow):

- `pip install -r requirements.txt`
- or your `uv`/`pyproject.toml` flow

Start server:

- `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

## Endpoints

- `GET /health` – sanity check, class list, and model metadata
- `POST /predict` – accepts a base64 frame and returns the top prediction
- `POST /reset` – kept for compatibility; no session buffer is used now

`/predict` request body:

```json
{
	"image_base64": "...",
	"image_base64": "..."
}
```

`/predict` response includes:

- `prediction`
- `confidence`
- `hand_detected`
- `detected_hands`
- `top_candidates`

The frontend is now designed around this single-frame inference flow, with live camera snapshots and still-image uploads instead of a multi-frame buffer.

