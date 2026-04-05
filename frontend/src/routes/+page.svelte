<script lang="ts">
	import { onDestroy, onMount } from "svelte";
	import { fade, slide, scale } from "svelte/transition";

	// Constants
	const API_BASE =
		(import.meta.env.VITE_API_BASE_URL as string) ||
		(typeof window !== "undefined" &&
		window.location.hostname !== "localhost"
			? "https://asl-live.onrender.com"
			: "http://localhost:8000");

	// DOM Refs
	let videoEl = $state<HTMLVideoElement | null>(null);
	let canvasEl = $state<HTMLCanvasElement | null>(null);

	// App State
	let stream = $state<MediaStream | null>(null);
	let started = $derived(stream !== null);
	let isCapturing = $state(false);
	let errorMessage = $state("");
	let backendStatus = $state<"connecting" | "connected" | "offline">(
		"connecting",
	);

	// Inference State
	let sessionId = $state(crypto.randomUUID());
	let prediction = $state("idle");
	let confidence = $state(0);
	let framesCollected = $state(0);

	// Timers & Controllers
	let healthTimer: ReturnType<typeof setInterval> | null = null;
	let captureLoopTimer: ReturnType<typeof setTimeout> | null = null;
	let abortController: AbortController | null = null;

	const confidencePct = $derived(`${(confidence * 100).toFixed(0)}%`);

	async function checkBackendHealth() {
		try {
			const res = await fetch(`${API_BASE}/health`, {
				method: "GET",
				headers: { Accept: "application/json" },
				signal: AbortSignal.timeout(5000),
				cache: "no-store",
			});
			if (res.ok) {
				backendStatus = "connected";
				// Make sure we clear any leftover connecting error if it was just cold starting
				if (
					errorMessage.includes("Backend") ||
					errorMessage.includes("Warming")
				) {
					errorMessage = "";
				}
			} else {
				backendStatus = "offline";
			}
		} catch (error) {
			backendStatus = "offline";
			if (!started && errorMessage === "") {
				errorMessage =
					"Warming up backend... Deployments may take a minute to wake up.";
			}
		}
	}

	function captureBase64(): string | null {
		if (
			!videoEl ||
			!canvasEl ||
			videoEl.videoWidth === 0 ||
			videoEl.videoHeight === 0
		)
			return null;

		// Use a smaller dimension for inference to save bandwidth and compute
		const TARGET_WIDTH = 320;
		const TARGET_HEIGHT = 240;

		canvasEl.width = TARGET_WIDTH;
		canvasEl.height = TARGET_HEIGHT;

		const ctx = canvasEl.getContext("2d");
		if (!ctx) return null;

		// Calculate crop/scale to maintain aspect ratio if needed, or just squash
		// The backend resizes independently too, but we squash locally for speed
		ctx.drawImage(videoEl, 0, 0, TARGET_WIDTH, TARGET_HEIGHT);

		const dataUrl = canvasEl.toDataURL("image/jpeg", 0.6);
		return dataUrl.split(",")[1] ?? null; // Strip the `data:image/jpeg;base64,` header
	}

	let isSpeaking = false;

	async function captureFrameIteration() {
		if (!started) {
			isCapturing = false;
			return;
		}

		isCapturing = true;

		// Skip inference while audio is playing to avoid interfering with playback
		if (!isSpeaking) {
			const imageBase64 = captureBase64();

			if (imageBase64) {
				try {
					if (abortController) abortController.abort();
					abortController = new AbortController();

					const payload = {
						image_base64: imageBase64,
						session_id: sessionId,
					};
					const response = await fetch(`${API_BASE}/predict`, {
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify(payload),
						signal: abortController.signal,
					});

					if (response.ok) {
						const data = await response.json();
						sessionId = data.session_id;
						prediction = data.prediction;
						confidence = data.confidence;
						framesCollected = data.frames_collected;
						errorMessage = "";
					}
				} catch (error: any) {
					if (error.name !== "AbortError") {
						console.error("Inference error:", error);
					}
				}
			}
		}

		// Loop at a calmer pace to avoid overwhelming the browser and server
		if (started) {
			captureLoopTimer = setTimeout(captureFrameIteration, 200);
		} else {
			isCapturing = false;
		}
	}

	async function startCamera() {
		errorMessage = "";
		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: {
					width: { ideal: 640 },
					height: { ideal: 480 },
					facingMode: "user",
				},
			});
			if (videoEl) {
				videoEl.srcObject = stream;
				await videoEl.play();
			}
			captureFrameIteration(); // Start the loop
		} catch (error) {
			stream = null;
			errorMessage = `Camera access denied or failed: ${error instanceof Error ? error.message : String(error)}`;
		}
	}

	function stopCamera() {
		if (captureLoopTimer) {
			clearTimeout(captureLoopTimer);
			captureLoopTimer = null;
		}
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
		if (stream) {
			for (const track of stream.getTracks()) {
				track.stop();
			}
		}
		if (videoEl) {
			videoEl.srcObject = null;
		}
		stream = null;
		isCapturing = false;

		// Reset states upon stopping
		prediction = "idle";
		confidence = 0;
		framesCollected = 0;
	}

	async function resetSession() {
		const oldSession = sessionId;
		sessionId = crypto.randomUUID(); // Cycle the session ID immediately
		prediction = "idle";
		confidence = 0;
		framesCollected = 0;

		try {
			await fetch(`${API_BASE}/reset`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ session_id: oldSession }),
			});
		} catch {
			// Best-effort
		}
	}

	let currentAudio: HTMLAudioElement | null = null;

	async function speakPrediction(text: string) {
		if (currentAudio) {
			currentAudio.pause();
			currentAudio.currentTime = 0;
		}

		isSpeaking = true;
		try {
			currentAudio = new Audio(`${API_BASE}/tts?text=${encodeURIComponent(text)}`);
			currentAudio.onended = () => { isSpeaking = false; };
			currentAudio.onerror = () => { isSpeaking = false; };
			await currentAudio.play();
		} catch (error) {
			console.error("Failed to play audio:", error);
			isSpeaking = false;
		}
	}

	onMount(() => {
		void checkBackendHealth();
		healthTimer = setInterval(() => void checkBackendHealth(), 10000);
	});

	onDestroy(() => {
		if (healthTimer) clearInterval(healthTimer);
		stopCamera();
	});
</script>

<svelte:head>
	<title>ASL Pulse • Live Sign Language Predictor</title>
</svelte:head>

<div
	class="min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(120,119,198,0.3),rgba(255,255,255,0))] text-slate-200 font-sans p-4 sm:p-8 flex flex-col items-center justify-center selection:bg-indigo-500/30"
>
	<!-- Header -->
	<header
		class="w-full max-w-4xl flex flex-col sm:flex-row items-center justify-between mb-8 gap-6 z-10"
		in:slide={{ duration: 700, delay: 100 }}
	>
		<div class="flex items-center gap-4">
			<div
				class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-indigo-500 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/20"
			>
				<svg
					class="w-6 h-6 text-white"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M7 11.5V14m0-2.5v-6a1.5 1.5 0 113 0m-3 6a1.5 1.5 0 00-3 0v2a7.5 7.5 0 0015 0v-5a1.5 1.5 0 00-3 0m-6-3V11m0-5.5v-1a1.5 1.5 0 013 0v1m0 0V11m0-5.5a1.5 1.5 0 013 0v3m0 0V11"
					/>
				</svg>
			</div>
			<div>
				<h1
					class="text-3xl font-extrabold tracking-tight text-white mb-1"
				>
					ASL Pulse
				</h1>
				<p class="text-sm font-medium text-slate-400">
					Live Prediction of 5 Core ASL Words
				</p>
			</div>
		</div>

		<!-- Backend Status Pill -->
		<div
			class="flex items-center gap-3 px-4 py-2.5 rounded-full bg-slate-900/50 border border-slate-700/50 backdrop-blur-md transition-colors duration-300 relative overflow-hidden group"
		>
			<!-- Animated glow effect depending on status -->
			{#if backendStatus === "connected"}
				<div
					class="absolute inset-0 bg-emerald-500/10 opacity-0 group-hover:opacity-100 transition-opacity"
				></div>
				<div
					class="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] flex-shrink-0 animate-pulse"
				></div>
				<span class="text-sm font-bold text-emerald-400"
					>Systems Normal</span
				>
			{:else if backendStatus === "connecting"}
				<div
					class="absolute inset-0 bg-amber-500/10 opacity-0 group-hover:opacity-100 transition-opacity"
				></div>
				<div
					class="w-2.5 h-2.5 rounded-full bg-amber-500 animate-bounce flex-shrink-0"
				></div>
				<span class="text-sm font-bold text-amber-500"
					>Connecting...</span
				>
			{:else}
				<div
					class="absolute inset-0 bg-rose-500/10 opacity-0 group-hover:opacity-100 transition-opacity"
				></div>
				<div
					class="w-2.5 h-2.5 rounded-full bg-rose-500 flex-shrink-0"
				></div>
				<span class="text-sm font-bold text-rose-500"
					>Backend Offline</span
				>
			{/if}
		</div>
	</header>

	<!-- Main Interface Container -->
	<main
		class="w-full max-w-4xl grid grid-cols-1 lg:grid-cols-12 gap-6 relative z-10"
		in:scale={{ start: 0.95, duration: 600, delay: 200 }}
	>
		<!-- Visuals Column -->
		<div class="lg:col-span-8 flex flex-col gap-6">
			<!-- Video Feed Card -->
			<div
				class="relative w-full aspect-video rounded-3xl overflow-hidden bg-slate-900 border border-slate-700/50 shadow-2xl flex flex-col items-center justify-center group"
			>
				{#if !started}
					<div
						class="absolute inset-0 flex flex-col items-center justify-center p-6 text-center z-20 pointer-events-none"
						in:fade={{ duration: 200 }}
					>
						<div
							class="w-20 h-20 rounded-full bg-slate-800/80 flex items-center justify-center mb-4 border border-slate-700 shadow-xl group-hover:scale-110 transition-transform duration-500"
						>
							<svg
								class="w-8 h-8 text-slate-400"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="1.5"
									d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
								/>
							</svg>
						</div>
						<p class="text-lg font-semibold text-slate-300">
							Camera Inactive
						</p>
						<p class="text-sm text-slate-500 mt-1 max-w-xs">
							Start the camera to begin analyzing sign language
							gestures.
						</p>
					</div>
				{/if}

				<!-- Actual Video Feed -->
				<!-- svelte-ignore a11y_media_has_caption -->
				<video
					bind:this={videoEl}
					playsinline
					muted
					class="w-full h-full object-cover z-10 mirror-video transition-opacity duration-700 {started
						? 'opacity-100'
						: 'opacity-0'}"
				></video>

				<!-- Hidden Extraction Canvas -->
				<canvas bind:this={canvasEl} class="hidden"></canvas>

				<!-- Recording Indicator -->
				{#if started && isCapturing}
					<div
						class="absolute top-4 right-4 z-30 flex items-center gap-2 px-3 py-1.5 rounded-full bg-black/50 backdrop-blur-md border border-white/10"
						in:fade={{ duration: 150 }}
						out:fade
					>
						<div
							class="w-2 h-2 rounded-full bg-red-500 animate-[pulse_1s_ease-in-out_infinite]"
						></div>
						<span
							class="text-xs font-bold tracking-wider text-red-500 uppercase"
							>Live</span
						>
					</div>
				{/if}
			</div>

			<!-- Error Alert Drawer -->
			{#if errorMessage}
				<div
					class="bg-rose-500/10 border border-rose-500/20 rounded-2xl p-4 flex items-start gap-4"
					in:slide={{ duration: 300 }}
					out:slide
				>
					<svg
						class="w-6 h-6 text-rose-500 flex-shrink-0 mt-0.5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
						/>
					</svg>
					<div>
						<h3 class="text-sm font-bold text-rose-400">Notice</h3>
						<p class="text-sm text-slate-300 mt-1 leading-relaxed">
							{errorMessage}
						</p>
					</div>
				</div>
			{/if}
		</div>

		<!-- Logic & Results Column -->
		<div class="lg:col-span-4 flex flex-col gap-6">
			<!-- AI Processing Card -->
			<div
				class="bg-slate-900/60 backdrop-blur-md border border-slate-700/50 rounded-3xl p-6 shadow-xl flex-1 flex flex-col relative overflow-hidden"
			>
				<!-- Ambient Glow behind card -->
				<div
					class="absolute -top-24 -right-24 w-48 h-48 bg-indigo-500/20 blur-3xl rounded-full pointer-events-none"
				></div>

				<h2
					class="text-sm font-bold tracking-widest text-slate-500 uppercase mb-6 flex items-center gap-2"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
						/></svg
					>
					Inference Engine
				</h2>

				<!-- Prediction Giant Result -->
				<div
					class="flex-1 flex flex-col items-center justify-center text-center pb-6 border-b border-slate-700/50"
				>
					<!-- Active visual bounding frame for prediction text -->
					<div
						class="relative w-full rounded-2xl py-8 overflow-hidden"
					>
						<!-- Animated background for certain states -->
						{#if prediction !== "idle" && prediction !== "collecting"}
							<div
								class="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-purple-500/5"
								in:fade
							></div>
						{/if}

						{#if prediction === "idle"}
							<span
								class="text-4xl font-black text-slate-600 tracking-tight"
								in:scale>Waiting</span
							>
						{:else if prediction === "collecting"}
							<div
								class="flex flex-col items-center gap-3"
								in:fade
							>
								<div class="flex items-center gap-2">
									<div
										class="w-2 h-2 bg-indigo-500 rounded-full animate-bounce"
										style="animation-delay: 0s"
									></div>
									<div
										class="w-2 h-2 bg-violet-500 rounded-full animate-bounce"
										style="animation-delay: 0.1s"
									></div>
									<div
										class="w-2 h-2 bg-fuchsia-500 rounded-full animate-bounce"
										style="animation-delay: 0.2s"
									></div>
								</div>
								<span class="text-lg font-bold text-indigo-400"
									>Observing Sequence...</span
								>
							</div>
						{:else if prediction === "uncertain"}
							<span
								class="text-4xl font-black text-amber-500 tracking-tight"
								in:scale>Hmm...</span
							>
							<p class="text-slate-400 font-medium mt-2 text-sm">
								Need clearer motion
							</p>
						{:else}
							<div
								class="flex flex-col items-center gap-4"
								in:scale={{ start: 0.8, duration: 400 }}
							>
								<span
									class="text-5xl font-black text-white capitalize tracking-tight drop-shadow-md"
								>
									{prediction}
								</span>
								<button
									onclick={() => speakPrediction(prediction)}
									class="flex items-center justify-center w-12 h-12 rounded-full bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 hover:text-indigo-300 border border-indigo-500/20 hover:border-indigo-500/40 transition-all duration-300 active:scale-95 group"
									aria-label="Play audio pronunciation"
									title="Play audio"
								>
									<svg
										class="w-6 h-6 group-hover:scale-110 transition-transform"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.5 10.5h4l5-5v13l-5-5h-4v-3z"
										/>
									</svg>
								</button>
							</div>
						{/if}
					</div>
				</div>

				<!-- Metrics Breakdown -->
				<div class="pt-6 grid grid-cols-2 gap-4">
					<!-- Confidence Metric -->
					<div
						class="bg-slate-800/50 rounded-2xl p-4 border border-slate-700/30"
					>
						<div
							class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2"
						>
							Confidence
						</div>
						<div class="flex items-end gap-2 text-white">
							<span class="text-2xl font-black leading-none"
								>{confidencePct}</span
							>
						</div>

						<!-- Progress Bar -->
						<div
							class="w-full h-1.5 bg-slate-900 rounded-full mt-3 overflow-hidden"
						>
							<div
								class="h-full bg-gradient-to-r from-emerald-400 to-indigo-500 transition-all duration-300 ease-out"
								style="width: {confidence * 100}%"
							></div>
						</div>
					</div>

					<!-- Frames Metric -->
					<div
						class="bg-slate-800/50 rounded-2xl p-4 border border-slate-700/30"
					>
						<div
							class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2"
						>
							Frames
						</div>
						<div class="flex items-end gap-1 text-white">
							<span class="text-2xl font-black leading-none"
								>{framesCollected}</span
							>
							<span
								class="text-sm font-bold text-slate-500 mb-0.5"
								>/ 40</span
							>
						</div>

						<!-- Progress Bar -->
						<div
							class="w-full h-1.5 bg-slate-900 rounded-full mt-3 overflow-hidden"
						>
							<div
								class="h-full bg-indigo-500 transition-all duration-300 ease-out"
								style="width: {(framesCollected / 40) * 100}%"
							></div>
						</div>
					</div>
				</div>
			</div>

			<!-- Controls Card -->
			<div
				class="bg-slate-900/60 backdrop-blur-md border border-slate-700/50 rounded-3xl p-3 shadow-xl flex flex-col gap-3"
			>
				{#if !started}
					<button
						onclick={startCamera}
						disabled={backendStatus === "offline"}
						class="w-full relative py-4 px-6 bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-400 hover:to-violet-500 disabled:from-slate-800 disabled:to-slate-800 disabled:text-slate-500 text-white font-bold rounded-2xl shadow-lg shadow-indigo-500/25 transition-all duration-300 active:scale-[0.98] group overflow-hidden"
					>
						<!-- Button inner highlight -->
						<div
							class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent"
						></div>
						<span
							class="relative flex items-center justify-center gap-2"
						>
							<svg
								class="w-5 h-5"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
								><path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
								/><path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
								/></svg
							>
							{backendStatus === "offline"
								? "Backend Unavailable"
								: "Initialize Scanner"}
						</span>
					</button>
				{:else}
					<button
						onclick={stopCamera}
						class="w-full py-4 px-6 bg-rose-500/10 hover:bg-rose-500/20 text-rose-500 font-bold rounded-2xl border border-rose-500/20 transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
					>
						<svg
							class="w-5 h-5"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
							><path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
							/><path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"
							/></svg
						>
						Terminate Scanner
					</button>
				{/if}

				<button
					onclick={resetSession}
					disabled={!started && prediction === "idle"}
					class="w-full py-3 px-6 bg-slate-800/80 hover:bg-slate-800 border border-slate-700 hover:border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-300 font-medium rounded-2xl transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
						/></svg
					>
					Refresh Session Buffer
				</button>
			</div>
		</div>
	</main>
</div>

<style>
	/* Make the video act like a mirror */
	.mirror-video {
		transform: scaleX(-1);
	}
</style>
