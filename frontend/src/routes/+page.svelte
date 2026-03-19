<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	// Use environment variable if set, otherwise detect production vs dev
	const API_BASE =
		(import.meta.env.VITE_API_BASE_URL as string) ||
		(typeof window !== 'undefined' && window.location.hostname !== 'localhost'
			? 'https://asl-live.onrender.com'
			: 'http://localhost:8000');
	const CAPTURE_INTERVAL_MS = 180;

	let videoEl: HTMLVideoElement;
	let canvasEl: HTMLCanvasElement;
	let stream: MediaStream | null = null;
	let timer: number | null = null;
	let healthTimer: number | null = null;

	let started = false;
	let busy = false;
	let sessionId = crypto.randomUUID();

	let prediction = 'idle';
	let confidence = 0;
	let framesCollected = 0;
	let errorMessage = '';
	let backendConnected = false;

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
		if (!imageBase64) {
			console.warn('Failed to capture frame');
			return;
		}

		busy = true;
		try {
			const payload = { image_base64: imageBase64, session_id: sessionId };
			console.log(`Sending frame ${framesCollected + 1}...`);
			
			const response = await fetch(`${API_BASE}/predict`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});

			if (!response.ok) {
				throw new Error(`API error ${response.status}: ${response.statusText}`);
			}

			const data = await response.json();
			sessionId = data.session_id;
			prediction = data.prediction;
			confidence = data.confidence;
			framesCollected = data.frames_collected;
			backendConnected = true;
			errorMessage = '';
			console.log(`Frame received: ${prediction} (${(confidence * 100).toFixed(1)}%)`);
		} catch (error) {
			const msg = error instanceof Error ? error.message : String(error);
			backendConnected = false;
			errorMessage = `Inference error: ${msg}`;
			console.error('sendFrame error:', msg);
		} finally {
			busy = false;
		}
	}

	function startLoop() {
		if (timer) window.clearInterval(timer);
		timer = window.setInterval(sendFrame, CAPTURE_INTERVAL_MS);
	}

	async function checkBackendHealth() {
		const controller = new AbortController();
		const timeoutId = window.setTimeout(() => controller.abort(), 10000);
		try {
			const response = await fetch(`${API_BASE}/health`, {
				method: 'GET',
				headers: { Accept: 'application/json' },
				signal: controller.signal,
				cache: 'no-store'
			});
			if (response.ok) {
				backendConnected = true;
				console.log('✓ Backend connected:', API_BASE);
				if (!started && errorMessage.startsWith('Cannot reach backend')) {
					errorMessage = '';
				}
				return true;
			} else {
				backendConnected = false;
				errorMessage = `Backend error: ${response.status}`;
				console.error('Backend health check failed:', response.status);
				return false;
			}
		} catch (error) {
			backendConnected = false;
			if (!started) {
				errorMessage = 'Warming backend... this can take up to a minute on Render cold starts.';
			} else {
				errorMessage = `Cannot reach backend: ${error instanceof Error ? error.message : String(error)}`;
			}
			console.error('Backend connection failed:', error);
			return false;
		} finally {
			window.clearTimeout(timeoutId);
		}
	}

	onMount(() => {
		console.log('App loaded. API_BASE:', API_BASE);
		void checkBackendHealth();
		healthTimer = window.setInterval(() => {
			void checkBackendHealth();
		}, 15000);
		return () => stopCamera();
	});

	onDestroy(() => {
		if (healthTimer) {
			window.clearInterval(healthTimer);
			healthTimer = null;
		}
		stopCamera();
	});
</script>

<main class="container">
	<h1>ASL Live Word Predictor</h1>
	<p class="subtitle">Shows live prediction for: hello, thankyou, yes, no, sorry.</p>

	<div class="status">
		<span class="status-indicator" class:connected={backendConnected}></span>
		<span class="status-text">
			{#if backendConnected}
				✓ Backend connected
			{:else}
				✗ Backend offline
			{/if}
		</span>
		<span class="api-url">{API_BASE}</span>
	</div>

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

	.status {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 1rem;
		padding: 0.5rem 0.75rem;
		background: #f0f0f0;
		border-radius: 8px;
		font-size: 0.9rem;
	}

	.status-indicator {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #dc2626;
		transition: background 0.3s;
	}

	.status-indicator.connected {
		background: #16a34a;
	}

	.status-text {
		font-weight: 600;
		flex: 1;
	}

	.api-url {
		font-size: 0.75rem;
		opacity: 0.6;
		font-family: monospace;
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
