# ASL Prism Frontend

This Svelte app is a polished dashboard for the ASL alphabet landmark model.

## What it does

- streams camera frames to the backend for live one-frame inference
- supports still-image uploads for quick testing
- shows confidence, top candidates, and recent prediction history
- can optionally speak predictions through the backend TTS endpoint

## Develop

```sh
npm install
npm run dev
```

## Build

```sh
npm run build
```

## Notes

- Set `VITE_API_BASE_URL` if the backend is not running on `http://localhost:8000`
- The UI expects the backend to expose `/health`, `/predict`, `/reset`, and `/tts`
