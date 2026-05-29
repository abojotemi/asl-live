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

	type CapturedLetter = {
		letter: string;
		confidence: number;
		at: string;
	};

	const API_BASE =
		(import.meta.env.VITE_API_BASE_URL as string) ||
		(typeof window !== "undefined" && window.location.hostname !== "localhost"
			? "https://asl-live.onrender.com"
			: "http://localhost:8000");

	const CAMERA_WIDTH = 640;
	const CAMERA_HEIGHT = 480;
	const MAX_WORD_LENGTH = 5;
	const FALLBACK_CONFIDENCE_THRESHOLD = 0.4;
	const TOP_HISTORY_COUNT = 8;

	let videoEl = $state<HTMLVideoElement | null>(null);
	let canvasEl = $state<HTMLCanvasElement | null>(null);
	let fileInputEl = $state<HTMLInputElement | null>(null);
	let stream = $state<MediaStream | null>(null);
	let cameraState = $state<"idle" | "starting" | "live">("idle");
	let backendStatus = $state<"connecting" | "connected" | "offline">("connecting");
	let backendInfo = $state<BackendHealth | null>(null);
	let errorMessage = $state("");
	let isProcessing = $state(false);
	let isSpeaking = $state(false);
	let prediction = $state("waiting");
	let confidence = $state(0);
	let handDetected = $state(false);
	let detectedHands = $state(0);
	let topCandidates = $state<PredictionCandidate[]>([]);
	let lastUpdated = $state("");
	let uploadedImageUrl = $state<string | null>(null);
	let uploadedImageName = $state("");
	let recentPredictions = $state<Array<{ label: string; confidence: number; at: string }>>([]);
	let capturedLetters = $state<CapturedLetter[]>([]);
	let statusTimer: ReturnType<typeof setInterval> | null = null;
	let abortController: AbortController | null = null;
	let currentAudio: HTMLAudioElement | null = null;
	let currentAudioUrl: string | null = null;
	let activeTab = $state<"asl" | "stt">("asl");
	let sttSupported = $state(false);
	let sttListening = $state(false);
	let sttTranscript = $state("");
	let sttInterim = $state("");
	let sttError = $state("");
	let speechRecognition: any = null;

	const confidenceThreshold = $derived(
		backendInfo?.confidence_threshold ?? FALLBACK_CONFIDENCE_THRESHOLD,
	);
	const confidencePct = $derived(`${Math.round(confidence * 100)}%`);
	const confidenceBar = $derived(`${Math.max(0, Math.min(100, confidence * 100))}%`);
	const builtWord = $derived(capturedLetters.map((item) => item.letter).join(""));
	const wordReady = $derived(capturedLetters.length === MAX_WORD_LENGTH);
	const lettersRemaining = $derived(Math.max(0, MAX_WORD_LENGTH - capturedLetters.length));
	const lastCaptured = $derived(capturedLetters[capturedLetters.length - 1] ?? null);
	const cameraStatusLabel = $derived(
		cameraState === "live"
			? "Camera ready"
			: cameraState === "starting"
				? "Starting camera"
				: "Camera idle",
	);

	function isLetterPrediction(value: string) {
		return /^[A-Z]$/.test(value);
	}

	function pushRecentPrediction(label: string, value: number) {
		recentPredictions = [
			{ label, confidence: value, at: new Date().toLocaleTimeString() },
			...recentPredictions,
		].slice(0, TOP_HISTORY_COUNT);
	}

	function addCapturedLetter(letter: string, value: number) {
		capturedLetters = [
			...capturedLetters,
			{ letter, confidence: value, at: new Date().toLocaleTimeString() },
		].slice(0, MAX_WORD_LENGTH);
	}

	function removeLastLetter() {
		capturedLetters = capturedLetters.slice(0, -1);
	}

	function clearWord() {
		capturedLetters = [];
	}

	async function checkBackendHealth() {
		try {
			const res = await fetch(`${API_BASE}/health`, {
				method: "GET",
				headers: { Accept: "application/json" },
				cache: "no-store",
				signal: AbortSignal.timeout(5000),
			});

			if (!res.ok) {
				backendStatus = "offline";
				return;
			}

			backendStatus = "connected";
			backendInfo = (await res.json()) as BackendHealth;
			if (errorMessage.includes("backend") || errorMessage.includes("offline")) {
				errorMessage = "";
			}
		} catch {
			backendStatus = "offline";
			if (!errorMessage) {
				errorMessage = "Backend is offline or still waking up.";
			}
		}
	}

	function captureBase64(): string | null {
		if (!videoEl || !canvasEl || videoEl.videoWidth === 0 || videoEl.videoHeight === 0) {
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
		return uploadedImageUrl?.split(",")[1] ?? null;
	}

	async function readFileAsDataUrl(file: File) {
		return await new Promise<string>((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(String(reader.result));
			reader.onerror = () => reject(reader.error);
			reader.readAsDataURL(file);
		});
	}

	async function speakText(text: string) {
		if (currentAudio) {
			currentAudio.pause();
			currentAudio.currentTime = 0;
		}
		if (currentAudioUrl) {
			URL.revokeObjectURL(currentAudioUrl);
			currentAudioUrl = null;
		}

		isSpeaking = true;
		try {
			const response = await fetch(`${API_BASE}/tts?text=${encodeURIComponent(text)}`);
			if (!response.ok) throw new Error(`TTS failed with ${response.status}`);

			const blob = await response.blob();
			currentAudioUrl = URL.createObjectURL(blob);
			currentAudio = new Audio(currentAudioUrl);
			currentAudio.onended = () => {
				isSpeaking = false;
				if (currentAudioUrl) {
					URL.revokeObjectURL(currentAudioUrl);
					currentAudioUrl = null;
				}
			};
			currentAudio.onerror = () => {
				isSpeaking = false;
				if (currentAudioUrl) {
					URL.revokeObjectURL(currentAudioUrl);
					currentAudioUrl = null;
				}
			};
			await currentAudio.play();
		} catch (error) {
			console.error("TTS error:", error);
			if (typeof window !== "undefined" && "speechSynthesis" in window) {
				window.speechSynthesis.cancel();
				const utterance = new SpeechSynthesisUtterance(text);
				utterance.onend = () => {
					isSpeaking = false;
				};
				utterance.onerror = () => {
					isSpeaking = false;
				};
				window.speechSynthesis.speak(utterance);
				return;
			}
			errorMessage = "Could not start audio playback.";
			isSpeaking = false;
		}
	}

	async function predictFromBase64(imageBase64: string): Promise<PredictionResponse | null> {
		if (!imageBase64 || isProcessing) return null;

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

			if (isLetterPrediction(data.prediction)) {
				pushRecentPrediction(data.prediction, data.confidence);
			}

			if (data.prediction === "no_hand") {
				errorMessage = "No hand landmarks were detected. Try moving closer to the camera.";
			}

			return data;
		} catch (error) {
			if ((error as { name?: string }).name !== "AbortError") {
				console.error("Inference error:", error);
				errorMessage = "Inference failed. Check the backend and camera permissions.";
			}
			return null;
		} finally {
			isProcessing = false;
		}
	}

	async function captureAndPredict() {
		const imageBase64 = cameraState === "live" ? captureBase64() : captureUploadedBase64();
		if (!imageBase64) {
			if (!uploadedImageUrl && cameraState !== "live") {
				errorMessage = "Start the camera or upload an image before capturing a letter.";
			}
			return null;
		}
		return await predictFromBase64(imageBase64);
	}

	async function captureAndAddLetter() {
		const result = await captureAndPredict();
		if (!result) return;

		if (!isLetterPrediction(result.prediction)) {
			errorMessage =
				result.prediction === "uncertain"
					? "The model needs a clearer pose before adding a letter."
					: "No usable letter was detected for the word builder.";
			return;
		}

		if (result.confidence < confidenceThreshold) {
			errorMessage = `That prediction is below the ${Math.round(confidenceThreshold * 100)}% threshold. Try again.`;
			return;
		}

		if (capturedLetters.length >= MAX_WORD_LENGTH) {
			errorMessage = "Your 5-letter word is already full. Clear it to build another one.";
			return;
		}

		addCapturedLetter(result.prediction, result.confidence);
		errorMessage = "";
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
		} catch (error) {
			cameraState = "idle";
			stream = null;
			errorMessage = `Camera access failed: ${error instanceof Error ? error.message : String(error)}`;
		}
	}

	function stopCamera() {
		abortController?.abort();
		abortController = null;

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
		lastUpdated = "";
	}

	async function speakCapturedWord() {
		if (!wordReady || !builtWord) return;
		await speakText(builtWord);
	}

	function getSpeechRecognitionCtor() {
		if (typeof window === "undefined") return null;
		const browserWindow = window as Window & {
			SpeechRecognition?: new () => any;
			webkitSpeechRecognition?: new () => any;
		};
		return browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition ?? null;
	}

	function stopTranscription() {
		if (speechRecognition) {
			speechRecognition.onresult = null;
			speechRecognition.onerror = null;
			speechRecognition.onend = null;
			speechRecognition.stop();
		}
		sttListening = false;
	}

	function clearTranscript() {
		sttTranscript = "";
		sttInterim = "";
		sttError = "";
	}

	async function copyTranscript() {
		const text = [sttTranscript, sttInterim].filter(Boolean).join(" ").trim();
		if (!text || typeof navigator === "undefined" || !navigator.clipboard) return;
		await navigator.clipboard.writeText(text);
	}

	function startTranscription() {
		sttError = "";
		const SpeechRecognitionCtor = getSpeechRecognitionCtor();
		if (!SpeechRecognitionCtor) {
			sttError = "Speech recognition is not supported in this browser.";
			return;
		}

		stopTranscription();
		speechRecognition = new SpeechRecognitionCtor();
		speechRecognition.lang = "en-US";
		speechRecognition.continuous = false;
		speechRecognition.interimResults = true;
		speechRecognition.maxAlternatives = 1;

		speechRecognition.onresult = (event: any) => {
			let finalChunk = "";
			let interimChunk = "";
			for (let i = event.resultIndex; i < event.results.length; i += 1) {
				const transcript = event.results[i][0]?.transcript ?? "";
				if (event.results[i].isFinal) {
					finalChunk += `${transcript} `;
				} else {
					interimChunk += `${transcript} `;
				}
			}
			if (finalChunk.trim()) {
				sttTranscript = `${sttTranscript} ${finalChunk}`.trim();
			}
			sttInterim = interimChunk.trim();
		};

		speechRecognition.onerror = (event: any) => {
			sttError = event?.error
				? `Transcription error: ${event.error}`
				: "Transcription failed.";
			sttListening = false;
		};

		speechRecognition.onend = () => {
			sttListening = false;
			sttInterim = "";
		};

		sttListening = true;
		try {
			speechRecognition.start();
		} catch {
			sttListening = false;
			sttError = "Could not start speech recognition.";
		}
	}

	async function resetView() {
		stopCamera();
		uploadedImageUrl = null;
		uploadedImageName = "";
		recentPredictions = [];
		capturedLetters = [];
		lastUpdated = "";
		errorMessage = "";
		await checkBackendHealth();
	}

	onMount(() => {
		void checkBackendHealth();
		statusTimer = setInterval(() => void checkBackendHealth(), 10000);
		sttSupported = getSpeechRecognitionCtor() !== null;
	});

	onDestroy(() => {
		if (statusTimer) clearInterval(statusTimer);
		stopCamera();
		stopTranscription();
		if (currentAudio) currentAudio.pause();
		if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
		if (typeof window !== "undefined" && "speechSynthesis" in window) {
			window.speechSynthesis.cancel();
		}
	});
</script>

<svelte:head>
	<title>ASL Prism • 5-letter word builder</title>
	<meta
		name="description"
		content="Capture five ASL alphabet predictions, build a word, and play it aloud."
	/>
</svelte:head>

<div class="min-h-screen overflow-hidden bg-slate-950 text-slate-100">
	<div class="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(59,130,246,0.22),transparent_30%),radial-gradient(circle_at_right,rgba(16,185,129,0.12),transparent_18%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]"></div>
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
					<h1 class="mt-1 text-3xl font-black tracking-tight text-white sm:text-4xl">Build a 5-letter word from capture predictions</h1>
					<p class="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
						Capture one ASL letter at a time, stack five predictions into a word, and play the completed word aloud when you're done.
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

		<div class="flex flex-wrap items-center gap-3 rounded-3xl border border-white/10 bg-white/5 p-2 shadow-lg shadow-slate-950/30 backdrop-blur-xl">
			<button onclick={() => (activeTab = "asl")} class="rounded-2xl px-4 py-2 text-sm font-semibold transition {activeTab === 'asl' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200'}">
				ASL capture
			</button>
			<button onclick={() => (activeTab = "stt")} class="rounded-2xl px-4 py-2 text-sm font-semibold transition {activeTab === 'stt' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200'}">
				Speech to text
			</button>
		</div>

		{#if activeTab === "asl"}
		<main class="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
			<section class="space-y-6">
				<div class="rounded-[2rem] border border-white/10 bg-slate-900/55 p-4 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-5">
					<div class="mb-4 flex items-center justify-between gap-3">
						<div>
							<h2 class="text-lg font-bold text-white">Capture a letter</h2>
							<p class="text-sm text-slate-400">Use the camera or an uploaded image, then add the prediction to your 5-letter word.</p>
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
								<p class="text-2xl font-black text-white">Ready when you are</p>
								<p class="mt-2 max-w-lg text-sm leading-6 text-slate-400">
									Start the camera for live capture, or upload a still image and use that as your next letter.
								</p>
							</div>
						{/if}

						{#if uploadedImageUrl && cameraState !== "live"}
							<img src={uploadedImageUrl} alt="Uploaded preview" class="h-full w-full bg-slate-950 object-contain" />
						{/if}

						<video bind:this={videoEl} playsinline muted class="mirror-video h-full w-full object-cover {cameraState === 'live' ? 'opacity-100' : 'opacity-0'}"></video>

						<div class="pointer-events-none absolute inset-0 border border-cyan-400/15"></div>
						<div class="pointer-events-none absolute left-4 top-4 rounded-full border border-white/10 bg-slate-950/70 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.25em] text-cyan-200">
							126-dim landmark MLP
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
						<button onclick={startCamera} disabled={cameraState === "starting"} class="rounded-2xl bg-gradient-to-r from-indigo-500 to-cyan-500 px-4 py-3 text-sm font-bold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
							{cameraState === "starting" ? "Opening camera…" : "Start camera"}
						</button>
						<button onclick={cameraState === "live" ? stopCamera : resetView} class="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm font-bold text-rose-300 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">
							{cameraState === "live" ? "Stop camera" : "Reset all"}
						</button>
						<button onclick={() => void captureAndAddLetter()} disabled={isProcessing || (!uploadedImageUrl && cameraState !== "live") || wordReady} class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-bold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50">
							{isProcessing ? "Capturing…" : uploadedImageUrl && cameraState !== "live" ? "Analyze image + add letter" : "Capture frame + add letter"}
						</button>
					</div>

					<div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Word slots</span>
								<span class="font-semibold text-emerald-200">{capturedLetters.length}/{MAX_WORD_LENGTH}</span>
							</div>
							<p class="mt-2 text-xs text-slate-400">Add one captured prediction per slot, then play the finished word.</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Threshold</span>
								<span class="font-semibold text-emerald-200">{Math.round(confidenceThreshold * 100)}%</span>
							</div>
							<p class="mt-2 text-xs text-slate-400">Only confident letter predictions can be added.</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Current capture</span>
								<span class="font-semibold text-cyan-200">{prediction}</span>
							</div>
							<p class="mt-2 text-xs text-slate-400">The latest notebook-style landmark prediction.</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
							<div class="flex items-center justify-between gap-3">
								<span>Confidence</span>
								<span class="font-semibold text-cyan-200">{confidencePct}</span>
							</div>
							<p class="mt-2 text-xs text-slate-400">Use the capture button to lock a letter into the word.</p>
						</div>
					</div>
				</div>

				<div class="rounded-[2rem] border border-white/10 bg-slate-900/55 p-4 shadow-2xl shadow-slate-950/40 backdrop-blur-xl sm:p-5">
					<div class="mb-4 flex items-center justify-between gap-3">
						<div>
							<h2 class="text-lg font-bold text-white">Upload a still image</h2>
							<p class="text-sm text-slate-400">Great for testing the single-frame pipeline before building a word.</p>
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
								Upload a clear hand pose and capture it as the next letter in your word.
							</div>
						</div>
						<div class="rounded-3xl border border-white/10 bg-slate-950/40 p-5">
							<p class="text-sm font-semibold text-slate-300">Capture notes</p>
							<div class="mt-3 grid gap-3 sm:grid-cols-2">
								<div class="rounded-2xl bg-white/5 p-4">
									<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Feature shape</p>
									<p class="mt-2 text-lg font-black text-white">126</p>
								</div>
								<div class="rounded-2xl bg-white/5 p-4">
									<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Word length</p>
									<p class="mt-2 text-lg font-black text-white">5 letters</p>
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
							<p class="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-300/80">Current prediction</p>
							<h2 class="mt-2 text-2xl font-black text-white">{prediction === "waiting" ? "Awaiting capture" : prediction === "no_hand" ? "No hand detected" : prediction === "uncertain" ? "Uncertain" : prediction}</h2>
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
							<p class="mt-3 text-sm leading-6 text-amber-200/80">The hand was detected, but the pose needs to be clearer before it can be added to your word.</p>
						{:else if prediction !== "waiting"}
							<p class="mt-3 text-sm leading-6 text-emerald-200/80">This result comes from the notebook’s Dense MLP classifier running on MediaPipe landmarks.</p>
						{/if}
					</div>

					<div class="mt-4 rounded-[1.5rem] border border-white/10 bg-slate-950/60 p-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<p class="text-sm font-semibold text-slate-200">Your 5-letter word</p>
								<p class="text-xs text-slate-500">Capture letters one by one, then play the word aloud.</p>
							</div>
							<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold text-slate-200">{capturedLetters.length}/{MAX_WORD_LENGTH}</span>
						</div>

						<div class="mt-4 grid grid-cols-5 gap-2">
							{#each Array.from({ length: MAX_WORD_LENGTH }, (_, index) => index) as index}
								<div class="flex aspect-square flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-center">
									<p class="text-2xl font-black text-white">{capturedLetters[index]?.letter ?? "—"}</p>
									<p class="mt-1 text-[0.65rem] uppercase tracking-[0.28em] text-slate-500">{index + 1}</p>
								</div>
							{/each}
						</div>

						<div class="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Built word</p>
							<p class="mt-2 break-all text-3xl font-black text-white">{builtWord || "_____"}</p>
							<p class="mt-2 text-sm text-slate-400">{wordReady ? "Word complete — press play to hear it." : `${lettersRemaining} more letter${lettersRemaining === 1 ? "" : "s"} needed.`}</p>
						</div>

						<div class="mt-4 flex flex-wrap gap-3">
							<button onclick={speakCapturedWord} disabled={!wordReady || isSpeaking} class="rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-4 py-3 text-sm font-bold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
								{isSpeaking ? "Playing…" : "Play word"}
							</button>
							<button onclick={removeLastLetter} disabled={capturedLetters.length === 0} class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-bold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50">Undo</button>
							<button onclick={clearWord} disabled={capturedLetters.length === 0} class="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm font-bold text-rose-300 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">Clear word</button>
						</div>

						<div class="mt-4 flex flex-wrap gap-2 text-sm text-slate-300">
							<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1">Threshold {Math.round(confidenceThreshold * 100)}%</span>
							<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1">Last capture {lastCaptured ? lastCaptured.letter : "—"}</span>
						</div>
					</div>

					<div class="mt-4 grid gap-3 sm:grid-cols-3">
						<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Hands</p>
							<p class="mt-2 text-lg font-black text-white">{handDetected ? String(detectedHands) : "0"}</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Mode</p>
							<p class="mt-2 text-lg font-black text-white">{backendInfo?.inference_mode ?? "landmarks"}</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="text-xs uppercase tracking-[0.28em] text-slate-500">Dim</p>
							<p class="mt-2 text-lg font-black text-white">{backendInfo?.feature_dim ?? 126}</p>
						</div>
					</div>

					<div class="mt-4 rounded-[1.5rem] border border-white/10 bg-slate-950/60 p-4">
						<div class="flex items-center justify-between gap-3">
							<p class="text-sm font-semibold text-slate-200">Top candidates</p>
							<span class="text-xs font-semibold text-cyan-300">{prediction === "waiting" ? "Capture a pose" : `Latest: ${prediction}`}</span>
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
									The backend will show the top three class probabilities here after the first successful landmark detection.
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
							<p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Recent captures</p>
							<h3 class="mt-2 text-lg font-bold text-white">Word-building history</h3>
						</div>
						<button onclick={resetView} class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10">Reset</button>
					</div>

					<div class="mt-4 space-y-3">
						{#if capturedLetters.length > 0}
							{#each capturedLetters as item, index}
								<div class="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
									<div>
										<p class="font-bold text-white">{index + 1}. {item.letter}</p>
										<p class="text-xs text-slate-500">{item.at}</p>
									</div>
									<p class="text-sm font-semibold text-slate-300">{Math.round(item.confidence * 100)}%</p>
								</div>
							{/each}
						{:else}
							<div class="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm leading-6 text-slate-400">
								Capture five letters to build a word. Once the fifth slot is filled, the play button becomes available.
							</div>
						{/if}
					</div>
				</div>
			</aside>
		</main>
		{:else}
		<main class="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
			<section class="rounded-[2rem] border border-white/10 bg-slate-900/55 p-5 shadow-2xl shadow-slate-950/40 backdrop-blur-xl">
				<div class="flex items-center justify-between gap-3">
					<div>
						<p class="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">Speech to text</p>
						<h2 class="mt-2 text-2xl font-black text-white">Transcribe microphone audio</h2>
						<p class="mt-2 text-sm leading-6 text-slate-400">Use your browser’s speech recognition to turn spoken audio into text. This stays separate from the ASL capture flow.</p>
					</div>
					<div class="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-slate-300">
						{sttSupported ? (sttListening ? "Listening" : "Ready") : "Unsupported"}
					</div>
				</div>

				<div class="mt-5 grid gap-3 sm:grid-cols-3">
					<button onclick={sttListening ? stopTranscription : startTranscription} class="rounded-2xl bg-gradient-to-r from-indigo-500 to-cyan-500 px-4 py-3 text-sm font-bold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" disabled={!sttSupported && !sttListening}>
						{sttListening ? "Stop listening" : "Start listening"}
					</button>
					<button onclick={copyTranscript} class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-bold text-slate-100 transition hover:bg-white/10" disabled={!sttTranscript && !sttInterim}>
						Copy transcript
					</button>
					<button onclick={clearTranscript} class="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm font-bold text-rose-300 transition hover:bg-rose-500/20" disabled={!sttTranscript && !sttInterim}>
						Clear
					</button>
				</div>

				<div class="mt-5 rounded-[1.5rem] border border-white/10 bg-slate-950/70 p-4">
					<p class="text-sm font-semibold text-slate-200">Live transcript</p>
					<div class="mt-3 min-h-48 rounded-2xl border border-dashed border-white/10 bg-white/5 p-4 text-base leading-7 text-slate-100">
						{#if sttTranscript}
							<p class="whitespace-pre-wrap">{sttTranscript}{sttInterim ? ` ${sttInterim}` : ""}</p>
						{:else if sttInterim}
							<p class="whitespace-pre-wrap text-slate-300">{sttInterim}</p>
						{:else}
							<p class="text-slate-500">Start listening and speak clearly. Your transcription will appear here.</p>
						{/if}
					</div>
					<div class="mt-3 flex flex-wrap gap-2 text-sm text-slate-300">
						<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1">Language en-US</span>
						<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1">Interim results on</span>
					</div>
				</div>
			</section>

			<aside class="space-y-6">
				<div class="rounded-[2rem] border border-white/10 bg-slate-900/60 p-5 shadow-2xl shadow-slate-950/40 backdrop-blur-xl">
					<div class="flex items-center justify-between gap-3">
						<div>
							<p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Status</p>
							<h3 class="mt-2 text-lg font-bold text-white">Speech recognition</h3>
						</div>
						<span class="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold text-slate-200">{sttSupported ? "Supported" : "Not supported"}</span>
					</div>

					<div class="mt-4 space-y-3 text-sm leading-6 text-slate-300">
						<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="font-semibold text-white">How it works</p>
							<p class="mt-1 text-slate-400">Click start, speak into your microphone, and the browser will stream text into the transcript box.</p>
						</div>
						<div class="rounded-2xl border border-white/10 bg-white/5 p-4">
							<p class="font-semibold text-white">Current state</p>
							<p class="mt-1 text-slate-400">{sttListening ? "Listening for audio input." : "Idle and ready to listen."}</p>
						</div>
						{#if sttError}
							<div class="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-rose-100">
								<p class="font-semibold text-rose-200">Notice</p>
								<p class="mt-1">{sttError}</p>
							</div>
						{/if}
					</div>
				</div>
			</aside>
		</main>
		{/if}
	</div>
</div>

<style>
	.mirror-video {
		transform: scaleX(-1);
	}
</style>
