# ASL Backend (FastAPI)

This backend serves live sign-word inference for:

- `hello`
- `thankyou`
- `yes`
- `no`
- `sorry`

## Run

Install dependencies (pick one flow):

- `pip install -r requirements.txt`
- or your `uv`/`pyproject.toml` flow

Start server:

- `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

## Endpoints

- `GET /health` – sanity check and class list
- `POST /predict` – accepts base64 frame and session id
- `POST /reset` – clears a session frame buffer

`/predict` request body:

```json
{
	"image_base64": "...",
	"session_id": "optional-session-id"
}
```

`/predict` response includes:

- `prediction`
- `confidence`
- `ready` (false until 40 frames are collected)
- `frames_collected`

