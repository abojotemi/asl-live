<script lang="ts">
	import { onDestroy, onMount } from "svelte";
	import { fade } from "svelte/transition";

	type BackendHealth = {
		status: string;
		classes: string[];
		model_path: string;
		feature_dim: number;
		inference_mode: string;
		min_detection_confidence: number;
		confidence_threshold: number;
	};

	type PredictionCandidate = {
		label: string;
		confidence: number;
	};

	type PredictionResponse = {
		prediction: string;
		confidence: number;
		hand_detected: boolean;
		detected_hands: number;
		top_candidates: PredictionCandidate[];
	};

	const API_BASE =
		(import.meta.env.VITE_API_BASE_URL as string) ||
		(typeof window !== "undefined" && window.location.hostname !== "localhost"
			? "https://asl-live.onrender.com"
			: "http://localhost:8000");

	const CAMERA_WIDTH = 640;
	const CAMERA_HEIGHT = 480;
	const DEFAULT_CAPTURE_INTERVAL = 240;
	const SPEAK_THRESHOLD = 0.76;
	const TOP_HISTORY_COUNT = 6;

	let videoEl = $state<HTMLVideoElement | null>(null);
	let canvasEl = $state<HTMLCanvasElement | null>(null);
	let fileInputEl = $state<HTMLInputElement | null>(null);

	let stream = $state<MediaStream | null>(null);
	let cameraState = $state<"idle" | "starting" | "live">("idle");
	let backendStatus = $state<"connecting" | "connected" | "offline">(
		"connecting",
	);
	let errorMessage = $state("");
	let isProcessing = $state(false);
	let liveInferenceEnabled = $state(true);
	let captureIntervalMs = $state(DEFAULT_CAPTURE_INTERVAL);
	let speechEnabled = $state(false);

	let prediction = $state("waiting");
	let confidence = $state(0);
	let handDetected = $state(false);
	let detectedHands = $state(0);
	let topCandidates = $state<PredictionCandidate[]>([]);
	let lastUpdated = $state("");

	let backendInfo = $state<BackendHealth | null>(null);
	let classNames = $state<string[]>([]);
	let uploadedImageUrl = $state<string | null>(null);
	let uploadedImageName = $state("");
	let recentPredictions = $state<Array<{ label: string; confidence: number; at: string }>>([]);
	let statusTimer: ReturnType<typeof setInterval> | null = null;
	let captureTimer: ReturnType<typeof setInterval> | null = null;
	let abortController: AbortController | null = null;
	let currentAudio: HTMLAudioElement | null = null;
	let lastSpoken = "";
	let isSpeaking = false;

	const confidencePct = $derived(`${Math.round(confidence * 100)}%`);
	const confidenceBar = $derived(`${Math.max(0, Math.min(100, confidence * 100))}%`);
	const cameraStatusLabel = $derived(
		cameraState === "live"
			? "Camera active"
			: cameraState === "starting"
				? "Starting camera"
				: "Camera idle",
	);
	async function checkBackendHealth() {
		try {
			const res = await fetch(`${API_BASE}/health`, {
				method: "GET",
				headers: { Accept: "application/json" },
				signal: AbortSignal.timeout(5000),
				cache: "no-store",
			});
			if (!res.ok) {
				backendStatus = "offline";
				return;
			}

			backendStatus = "connected";
			const data = (await res.json()) as BackendHealth;
			backendInfo = data;
			classNames = data.classes ?? [];
			if (errorMessage.includes("backend") || errorMessage.includes("offline")) {
				errorMessage = "";
			}
		} catch {
			backendStatus = "offline";
			if (!stream && !uploadedImageUrl && !errorMessage) {
				errorMessage = "Backend is offline or still waking up.";
			}
		}
	}

	function clearCaptureTimer() {
		if (captureTimer) {
			clearInterval(captureTimer);
			captureTimer = null;
		}
	}

	function updateCaptureTimer() {
		clearCaptureTimer();
		if (stream && cameraState === "live" && liveInferenceEnabled) {
			captureTimer = setInterval(() => {
				void captureAndPredict();
			}, captureIntervalMs);
		}
	}

	function captureBase64(): string | null {
		if (
			!videoEl ||
			!canvasEl ||
			videoEl.videoWidth === 0 ||
			videoEl.videoHeight === 0
		) {
			return null;
		}

		canvasEl.width = CAMERA_WIDTH;
		canvasEl.height = CAMERA_HEIGHT;
		const ctx = canvasEl.getContext("2d");
		if (!ctx) return null;

		ctx.drawImage(videoEl, 0, 0, CAMERA_WIDTH, CAMERA_HEIGHT);
		const dataUrl = canvasEl.toDataURL("image/jpeg", 0.8);
		return dataUrl.split(",")[1] ?? null;
	}

	function captureUploadedBase64(): string | null {
		if (!uploadedImageUrl) return null;
		return uploadedImageUrl.split(",")[1] ?? null;
	}

	function pushRecentPrediction(label: string, value: number) {
		recentPredictions = [
			{ label, confidence: value, at: new Date().toLocaleTimeString() },
			...recentPredictions,
		].slice(0, TOP_HISTORY_COUNT);
	}

	async function speakPrediction(text: string) {
		if (currentAudio) {
			currentAudio.pause();
			currentAudio.currentTime = 0;
		}

		isSpeaking = true;
		try {
			const res = await fetch(`${API_BASE}/tts?text=${encodeURIComponent(text)}`);
			if (!res.ok) throw new Error(`TTS failed with ${res.status}`);
			const blob = await res.blob();
			const audioUrl = URL.createObjectURL(blob);
			currentAudio = new Audio(audioUrl);
			currentAudio.onended = () => {
				isSpeaking = false;
				URL.revokeObjectURL(audioUrl);
			};
			currentAudio.onerror = () => {
				isSpeaking = false;
				URL.revokeObjectURL(audioUrl);
			};
			await currentAudio.play();
		} catch (error) {
			console.error("TTS error:", error);
			isSpeaking = false;
		}
	}

	async function predictFromBase64(imageBase64: string) {
		if (!imageBase64 || isProcessing || backendStatus === "offline") return;

		isProcessing = true;
		errorMessage = "";
		try {
			abortController?.abort();
			abortController = new AbortController();

			const response = await fetch(`${API_BASE}/predict`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ image_base64: imageBase64 }),
				signal: abortController.signal,
			});

			if (!response.ok) {
				throw new Error(`Predict failed with ${response.status}`);
			}

			const data = (await response.json()) as PredictionResponse;
			prediction = data.prediction;
			confidence = data.confidence;
			handDetected = data.hand_detected;
			detectedHands = data.detected_hands;
			topCandidates = data.top_candidates ?? [];
			lastUpdated = new Date().toLocaleTimeString();

			if (data.prediction !== "no_hand" && data.prediction !== "uncertain") {
				pushRecentPrediction(data.prediction, data.confidence);
				if (
					speechEnabled &&
					data.confidence >= SPEAK_THRESHOLD &&
					data.prediction !== lastSpoken &&
					!isSpeaking
				) {
					lastSpoken = data.prediction;
					void speakPrediction(data.prediction);
				}
			}

			if (data.prediction === "no_hand") {
				errorMessage = "No hand landmarks were detected. Try moving closer to the camera.";
			}
		} catch (error) {
			if ((error as { name?: string }).name !== "AbortError") {
				console.error("Inference error:", error);
				errorMessage = "Inference failed. Check the backend and camera permissions.";
			}
		} finally {
			isProcessing = false;
		}
	}

	async function captureAndPredict() {
		if (cameraState !== "live") return;
		const imageBase64 = captureBase64();
		if (imageBase64) {
			await predictFromBase64(imageBase64);
		}
	}

	async function analyzeUploadedImage() {
		const imageBase64 = captureUploadedBase64();
		if (!imageBase64) {
			errorMessage = "Upload a photo first, then try again.";
			return;
		}
		await predictFromBase64(imageBase64);
	}

	async function readFileAsDataUrl(file: File) {
		return await new Promise<string>((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(String(reader.result));
			reader.onerror = () => reject(reader.error);
			reader.readAsDataURL(file);
		});
	}

	async function onUploadImage(event: Event) {
		const input = event.currentTarget as HTMLInputElement | null;
		const file = input?.files?.[0];
		if (!file) return;

		if (!file.type.startsWith("image/")) {
			errorMessage = "Please upload an image file.";
			return;
		}

		try {
			uploadedImageUrl = await readFileAsDataUrl(file);
			uploadedImageName = file.name;
			errorMessage = "";
		} catch {
			errorMessage = "Could not read the uploaded file.";
		}
	}

	async function startCamera() {
		errorMessage = "";
		cameraState = "starting";
		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: {
					width: { ideal: CAMERA_WIDTH },
					height: { ideal: CAMERA_HEIGHT },
					facingMode: "user",
				},
				audio: false,
			});

			if (videoEl) {
				videoEl.srcObject = stream;
				await videoEl.play();
			}

			cameraState = "live";
			updateCaptureTimer();
			lastSpoken = "";
		} catch (error) {
			cameraState = "idle";
			stream = null;
			errorMessage = `Camera access failed: ${error instanceof Error ? error.message : String(error)}`;
		}
	}

	function stopCamera() {
		abortController?.abort();
		abortController = null;
		clearCaptureTimer();

		if (stream) {
			for (const track of stream.getTracks()) {
				track.stop();
			}
		}

		if (videoEl) {
			videoEl.srcObject = null;
		}

		stream = null;
		cameraState = "idle";
		prediction = "waiting";
		confidence = 0;
		handDetected = false;
		detectedHands = 0;
		topCandidates = [];
		lastSpoken = "";
	}

	async function resetView() {
		stopCamera();
		uploadedImageUrl = null;
		uploadedImageName = "";
		recentPredictions = [];
		lastUpdated = "";
		errorMessage = "";
		await checkBackendHealth();
	}

	function syncControls() {
		updateCaptureTimer();
	}

	onMount(() => {
		void checkBackendHealth();
		statusTimer = setInterval(() => void checkBackendHealth(), 10000);
	});

	onDestroy(() => {
		if (statusTimer) clearInterval(statusTimer);
		clearCaptureTimer();
		stopCamera();
		currentAudio?.pause();
	});
</script>

<svelte:head>
	<title>ASL Prism • Landmark MLP Inference</title>
	<meta
		name="description"
		content="A polished ASL alphabet app powered by a single-frame MediaPipe landmark MLP."
	/>
</svelte:head>

<div class="min-h-screen overflow-hidden bg-slate-950 text-slate-100">
	<div class="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(99,102,241,0.20),transparent_32%),radial-gradient(circle_at_right,rgba(16,185,129,0.10),transparent_20%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]"></div>
	<div class="absolute inset-0 opacity-40 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:52px_52px]"></div>

	<div class="relative z-10 mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8">
		<header class="flex flex-col gap-4 rounded-3xl border border-white/10 bg-white/5 p-5 shadow-2xl shadow-slate-950/40 backdrop-blur-xl md:flex-row md:items-center md:justify-between">
			<div class="flex items-center gap-4">
				<div class="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 via-cyan-500 to-emerald-500 shadow-lg shadow-cyan-500/20">
					<svg class="h-7 w-7 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M7 11.5V14m0-2.5v-6a1.5 1.5 0 113 0m-3 6a1.5 1.5 0 00-3 0v2a7.5 7.5 0 0015 0v-5a1.5 1.5 0 00-3 0m-6-3V11m0-5.5v-1a1.5 1.5 0 013 0v1m0 0V11m0-5.5a1.5 1.5 0 013 0v3m0 0V11" />
					</svg>
				</div>
				<div>
					<p class="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">ASL Prism</p>
					<h1 class="mt-1 text-3xl font-black tracking-tight text-white sm:text-4xl">Single-frame landmark inference</h1>
					<p class="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
						The app now mirrors the notebook model: MediaPipe extracts 126 hand-landmark features and the MLP classifies each frame instantly.
					</p>
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-3">
				<div class="rounded-full border border-white/10 bg-slate-900/70 px-4 py-2 text-sm font-medium text-slate-300">
					<span class="mr-2 inline-block h-2 w-2 rounded-full {backendStatus === 'connected' ? 'bg-emerald-400' : backendStatus === 'offline' ? 'bg-rose-400' : 'bg-amber-400'}"></span>
					{backendStatus === "connected" ? "Backend ready" : backendStatus === "offline" ? "Backend offline" : "Connecting..."}
				</div>
				<div class="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-slate-300">
					{backendInfo ? `${backendInfo.inference_mode} • ${backendInfo.feature_dim} dims` : "Landmark model"}
				</div>
			</div>
		</header>

		<main class="grid gap-6 xl:grid-cols-[1.35fr_0.85fr]">
			<section class="space-y-6">
				<div class="rounded-[2rem] border border-white/10 bg-slate-900/55 p-4 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-5">
					<div class="mb-4 flex items-center justify-between gap-3">
						<div>
							<h2 class="text-lg font-bold text-white">Live camera</h2>
							<p class="text-sm text-slate-400">Capture a frame, extract landmarks, and classify instantly.</p>
						</div>
						<div class="rounded-full border border-white/10 bg-slate-950/70 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.24em] text-slate-300">
							{cameraStatusLabel}
						</div>
					</div>

					<div class="relative aspect-[4/3] overflow-hidden rounded-[1.75rem] border border-white/10 bg-slate-950/90 shadow-inner shadow-black/30">
						{#if cameraState !== "live" && !uploadedImageUrl}
							<div class="absolute inset-0 flex flex-col items-center justify-center px-8 text-center" in:fade>
								<div class="mb-4 flex h-20 w-20 items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
									<svg class="h-9 w-9" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
									</svg>
								</div>
								<p class="text-2xl font-black text-white">Camera idle</p>
								<p class="mt-2 max-w-lg text-sm leading-6 text-slate-400">
									Start the camera for live inference, or upload a still image below to run a one-frame prediction.
								</p>
							</div>
						{/if}

						{#if uploadedImageUrl && cameraState !== "live"}
							<img src={uploadedImageUrl} alt="Uploaded preview" class="h-full w-full bg-slate-950 object-contain" />
						{/if}

						<video
							bind:this={videoEl}
							playsinline
							muted
							class="mirror-video h-full w-full object-cover {cameraState === 'live' ? 'opacity-100' : 'opacity-0'}"
						></video>

						<div class="pointer-events-none absolute inset-0 border border-cyan-400/15"></div>
						<div class="pointer-events-none absolute left-4 top-4 rounded-full border border-white/10 bg-slate-950/70 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.25em] text-cyan-200">
							MLP • 126-dim landmarks
						</div>
						{#if handDetected}
							<div class="pointer-events-none absolute right-4 top-4 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.25em] text-emerald-200">
								{detectedHands} hand{detectedHands === 1 ? "" : "s"} detected
							</div>
						{/if}
						<div class="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-slate-950 via-slate-950/45 to-transparent"></div>
					</div>

					<canvas bind:this={canvasEl} class="hidden"></canvas>

					<div class="mt-4 grid gap-3 sm:grid-cols-3">
						<button
							onclick={startCamera}
							disabled={backendStatus === "offline" || cameraState === "starting"}
							class="rounded-2xl bg-gradient-to-r from-indigo-500 to-cyan-500 px-4 py-3 text-sm font-bold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{cameraState === "starting" ? "Opening camera…" : "Start camera"}
						</button>
						<button
							onclick={stopCamera}
							disabled={cameraState !== "live" && cameraState !== "starting"}
							class="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm font-bold text-rose-300 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
						>
							Stop camera
						</button>
						<button
							onclick={() => void (uploadedImageUrl ? analyzeUploadedImage() : captureAndPredict())}
							disabled={backendStatus === "offline" || isProcessing || (!uploadedImageUrl && cameraState !== "live")}
							class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-bold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isProcessing ? "Analyzing…" : uploadedImageUrl ? "Analyze image" : "Capture now"}
						</button>
					</div>

					<div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
						<label class="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<span>Live inference</span>
							<input type="checkbox" bind:checked={liveInferenceEnabled} onchange={syncControls} class="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-500" />
						</label>
						<label class="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<span>Voice cues</span>
							<input type="checkbox" bind:checked={speechEnabled} class="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-500" />
						</label>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Capture interval</span>
								<span class="font-semibold text-cyan-200">{captureIntervalMs} ms</span>
							</div>
							<input type="range" min="120" max="1000" step="20" bind:value={captureIntervalMs} oninput={syncControls} class="mt-2 w-full accent-cyan-400" />
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Threshold</span>
								<span class="font-semibold text-emerald-200">{backendInfo ? `${Math.round(backendInfo.confidence_threshold * 100)}%` : "40%"}</span>
							</div>
							<p class="mt-2 text-xs text-slate-400">The backend keeps low-confidence frames as uncertain.</p>
						</div>
					</div>
				</div>

				<div class="rounded-[2rem] border border-white/10 bg-slate-900/55 p-4 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-5">
					<div class="mb-4 flex items-center justify-between gap-3">
						<div>
							<h2 class="text-lg font-bold text-white">Upload a still image</h2>
							<p class="text-sm text-slate-400">Great for testing the notebook-style single-frame pipeline.</p>
						</div>
						<div class="flex items-center gap-3">
							<button onclick={() => fileInputEl?.click()} class="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-white/10">Choose image</button>
							<input bind:this={fileInputEl} type="file" accept="image/*" class="hidden" onchange={onUploadImage} />
						</div>
					</div>

					<div class="grid gap-4 md:grid-cols-[0.9fr_1.1fr]">
						<div class="rounded-3xl border border-dashed border-white/10 bg-slate-950/40 p-5">
							<p class="text-sm font-semibold text-slate-300">Selected file</p>
							<p class="mt-2 text-sm text-slate-400">{uploadedImageName || "No file chosen yet."}</p>
							<div class="mt-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs leading-6 text-slate-400">
								Upload a clear image with one or two hands. The backend will extract MediaPipe landmarks and classify the pose immediately.
							</div>
						</div>
						<div class="rounded-3xl border border-white/10 bg-slate-950/40 p-5">
							<p class="text-sm font-semibold text-slate-300">Model notes</p>
							<div class="mt-3 grid gap-3 sm:grid-cols-2">
								<div class="rounded-2xl bg-white/5 p-4">
									<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Feature shape</p>
									<p class="mt-2 text-lg font-black text-white">126</p>
								</div>
								<div class="rounded-2xl bg-white/5 p-4">
									<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Inference mode</p>
									<p class="mt-2 text-lg font-black text-white">Single frame</p>
								</div>
							</div>
						</div>
					</div>
				</div>
			</section>

			<aside class="space-y-6">
				<div class="rounded-[2rem] border border-white/10 bg-slate-900/60 p-5 shadow-2xl shadow-slate-950/40 backdrop-blur-xl" in:fade={{ duration: 180 }}>
					<div class="flex items-center justify-between gap-3">
						<div>
							<p class="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-300/80">Current result</p>
							<h2 class="mt-2 text-2xl font-black text-white">{prediction === "waiting" ? "Awaiting frame" : prediction === "no_hand" ? "No hand detected" : prediction === "uncertain" ? "Uncertain" : prediction}</h2>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-right">
							<p class="text-[0.65rem] uppercase tracking-[0.26em] text-slate-500">Confidence</p>
							<p class="text-lg font-black text-white">{confidencePct}</p>
						</div>
					</div>

					<div class="mt-5 rounded-[1.5rem] border border-white/10 bg-slate-950/70 p-4">
						<div class="flex items-center justify-between gap-3 text-sm text-slate-300">
							<span>{handDetected ? `${detectedHands} hand${detectedHands === 1 ? "" : "s"} detected` : "Waiting for landmarks"}</span>
							<span>{lastUpdated ? `Updated ${lastUpdated}` : "No result yet"}</span>
						</div>
						<div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
							<div class="h-full rounded-full bg-gradient-to-r from-cyan-400 via-indigo-500 to-emerald-400 transition-all duration-300" style={`width: ${confidenceBar}`}></div>
						</div>
						{#if prediction === "no_hand"}
							<p class="mt-3 text-sm leading-6 text-slate-400">Move a hand into the frame. The model only needs one clean snapshot to classify the pose.</p>
						{:else if prediction === "uncertain"}
							<p class="mt-3 text-sm leading-6 text-amber-200/80">The landmarks were detected, but the model wants a clearer pose. Try better lighting or a more centered hand.</p>
						{:else if prediction !== "waiting"}
							<p class="mt-3 text-sm leading-6 text-emerald-200/80">This prediction comes from the notebook’s Dense MLP classifier running on MediaPipe landmarks, not from a temporal sequence model.</p>
						{/if}
					</div>

					<div class="mt-4 grid gap-3 sm:grid-cols-3">
						{#each [
							{ label: "Hands", value: handDetected ? String(detectedHands) : "0" },
							{ label: "Mode", value: backendInfo?.inference_mode ?? "landmarks" },
							{ label: "Dim", value: backendInfo?.feature_dim ?? 126 },
						] as metric}
							<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
								<p class="text-xs uppercase tracking-[0.28em] text-slate-500">{metric.label}</p>
								<p class="mt-2 text-lg font-black text-white">{metric.value}</p>
							</div>
						{/each}
					</div>

					<div class="mt-4 rounded-[1.5rem] border border-white/10 bg-slate-950/60 p-4">
						<div class="flex items-center justify-between gap-3">
							<p class="text-sm font-semibold text-slate-200">Top candidates</p>
							<button onclick={() => void speakPrediction(prediction)} class="text-xs font-semibold text-cyan-300 transition hover:text-cyan-200" disabled={prediction === "waiting" || prediction === "no_hand" || prediction === "uncertain"}>Speak</button>
						</div>
						<div class="mt-3 space-y-3">
							{#if topCandidates.length > 0}
								{#each topCandidates as candidate, index}
									<div class="rounded-2xl border border-white/10 bg-white/5 p-3">
										<div class="flex items-center justify-between gap-3 text-sm">
											<span class="font-semibold text-white">{index + 1}. {candidate.label}</span>
											<span class="tabular-nums text-slate-300">{Math.round(candidate.confidence * 100)}%</span>
										</div>
										<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
											<div class="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-400" style={`width: ${Math.max(2, candidate.confidence * 100)}%`}></div>
										</div>
									</div>
								{/each}
							{:else}
								<div class="rounded-2xl border border-dashed border-white/10 bg-white/5 p-4 text-sm text-slate-400">
									The backend will return the top three class probabilities here after the first successful landmark detection.
								</div>
							{/if}
						</div>
					</div>

					{#if errorMessage}
						<div class="mt-4 rounded-[1.5rem] border border-rose-500/20 bg-rose-500/10 p-4 text-sm leading-6 text-rose-100">
							<p class="font-semibold text-rose-200">Notice</p>
							<p class="mt-1 text-rose-50/90">{errorMessage}</p>
						</div>
					{/if}
				</div>

				<div class="rounded-[2rem] border border-white/10 bg-slate-900/60 p-5 shadow-2xl shadow-slate-950/40 backdrop-blur-xl">
					<div class="flex items-center justify-between gap-3">
						<div>
							<p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Recent predictions</p>
							<h3 class="mt-2 text-lg font-bold text-white">Live history</h3>
						</div>
						<button onclick={resetView} class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10">Reset</button>
					</div>

					<div class="mt-4 space-y-3">
						{#if recentPredictions.length > 0}
							{#each recentPredictions as item}
								<div class="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
									<div>
										<p class="font-bold text-white">{item.label}</p>
										<p class="text-xs text-slate-500">{item.at}</p>
									</div>
									<p class="text-sm font-semibold text-slate-300">{Math.round(item.confidence * 100)}%</p>
								</div>
							{/each}
						{:else}
							<div class="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm leading-6 text-slate-400">
								The history will fill once live inference starts. Your camera is not required for still-image testing, which is handy if you prefer debugging with a single snapshot.
							</div>
						{/if}
					</div>
				</div>
			</aside>
		</main>
	</div>
</div>

<style>
	.mirror-video {
		transform: scaleX(-1);
	}
</style>
