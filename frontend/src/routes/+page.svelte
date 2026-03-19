<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';
	const CAPTURE_INTERVAL_MS = 180;

	let videoEl: HTMLVideoElement;
	let canvasEl: HTMLCanvasElement;
	let stream: MediaStream | null = null;
	let timer: number | null = null;

	let started = false;
	let busy = false;
	let sessionId = crypto.randomUUID();

	let prediction = 'idle';
	let confidence = 0;
	let framesCollected = 0;
	let errorMessage = '';

	const confidencePct = () => `${(confidence * 100).toFixed(1)}%`;

	async function startCamera() {
		errorMessage = '';
		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: { width: 640, height: 480 }
			});
			videoEl.srcObject = stream;
			await videoEl.play();
			started = true;
			startLoop();
		} catch (error) {
			errorMessage = `Camera error: ${error instanceof Error ? error.message : String(error)}`;
		}
	}

	function stopCamera() {
		if (timer) {
			window.clearInterval(timer);
			timer = null;
		}

		if (stream) {
			for (const track of stream.getTracks()) {
				track.stop();
			}
		}

		stream = null;
		started = false;
		busy = false;
	}

	async function resetSession() {
		const oldSession = sessionId;
		sessionId = crypto.randomUUID();
		prediction = 'idle';
		confidence = 0;
		framesCollected = 0;
		try {
			await fetch(`${API_BASE}/reset`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_id: oldSession })
			});
		} catch {
			// Non-blocking: local state reset is enough for UX
		}
	}

	function captureBase64(): string | null {
		if (!videoEl || !canvasEl || videoEl.videoWidth === 0 || videoEl.videoHeight === 0) return null;

		const ctx = canvasEl.getContext('2d');
		if (!ctx) return null;

		canvasEl.width = 320;
		canvasEl.height = 240;
		ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);
		const dataUrl = canvasEl.toDataURL('image/jpeg', 0.75);
		return dataUrl.split(',')[1] ?? null;
	}

	async function sendFrame() {
		if (!started || busy) return;
		const imageBase64 = captureBase64();
		if (!imageBase64) return;

		busy = true;
		try {
			const response = await fetch(`${API_BASE}/predict`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ image_base64: imageBase64, session_id: sessionId })
			});

			if (!response.ok) {
				throw new Error(`API ${response.status}`);
			}

			const data = await response.json();
			sessionId = data.session_id;
			prediction = data.prediction;
			confidence = data.confidence;
			framesCollected = data.frames_collected;
			errorMessage = '';
		} catch (error) {
			errorMessage = `Inference error: ${error instanceof Error ? error.message : String(error)}`;
		} finally {
			busy = false;
		}
	}

	function startLoop() {
		if (timer) window.clearInterval(timer);
		timer = window.setInterval(sendFrame, CAPTURE_INTERVAL_MS);
	}

	onMount(() => {
		return () => stopCamera();
	});

	onDestroy(() => {
		stopCamera();
	});
</script>

<main class="container">
	<h1>ASL Live Word Predictor</h1>
	<p class="subtitle">Shows live prediction for: hello, thankyou, yes, no, sorry.</p>

	<div class="panel">
		<video bind:this={videoEl} playsinline muted></video>
		<canvas bind:this={canvasEl} class="hidden-canvas"></canvas>

		<div class="results">
			<div><strong>Prediction:</strong> {prediction}</div>
			<div><strong>Confidence:</strong> {confidencePct()}</div>
			<div><strong>Frames:</strong> {framesCollected}/40</div>
		</div>

		<div class="buttons">
			<button on:click={startCamera} disabled={started}>Start camera</button>
			<button on:click={stopCamera} disabled={!started}>Stop</button>
			<button on:click={resetSession}>Reset session</button>
		</div>

		{#if errorMessage}
			<p class="error">{errorMessage}</p>
		{/if}
	</div>
</main>

<style>
	.container {
		max-width: 760px;
		margin: 2rem auto;
		padding: 1rem;
		font-family: system-ui, sans-serif;
	}

	h1 {
		font-size: 1.8rem;
		margin-bottom: 0.25rem;
	}

	.subtitle {
		opacity: 0.8;
		margin-bottom: 1rem;
	}

	.panel {
		display: grid;
		gap: 0.9rem;
		padding: 1rem;
		border: 1px solid #ddd;
		border-radius: 14px;
		background: #fff;
	}

	video {
		width: 100%;
		max-height: 420px;
		border-radius: 12px;
		background: #111;
	}

	.results {
		display: grid;
		gap: 0.35rem;
	}

	.buttons {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	button {
		border: none;
		padding: 0.6rem 0.9rem;
		border-radius: 10px;
		background: #1e3a8a;
		color: white;
		cursor: pointer;
	}

	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error {
		color: #b91c1c;
		font-weight: 600;
	}

	.hidden-canvas {
		display: none;
	}
</style>
