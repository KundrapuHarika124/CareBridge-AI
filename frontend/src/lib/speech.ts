// Voice input and spoken replies through Azure Speech, used only when the backend reports
// a real speech provider. The browser gets a short-lived token from the backend; the
// subscription key never reaches the browser and no audio is stored by CareBridge.
import { ApiError, post, type Lang } from "../api";

export type SpeechFailure = "MIC_DENIED" | "NO_SPEECH" | "UNAVAILABLE" | "FAILED";

interface BrowserSpeechRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => BrowserSpeechRecognition;
    webkitSpeechRecognition?: new () => BrowserSpeechRecognition;
  }
}

export function isBrowserSpeechSupported(): boolean {
  return typeof window !== "undefined"
    && !!(window.SpeechRecognition || window.webkitSpeechRecognition)
    && typeof window.speechSynthesis !== "undefined";
}

export function isBrowserRecognitionSupported(): boolean {
  return typeof window !== "undefined"
    && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function isBrowserSynthesisSupported(): boolean {
  return typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined";
}

export class SpeechError extends Error {
  kind: SpeechFailure;
  constructor(kind: SpeechFailure) {
    super(kind);
    this.kind = kind;
  }
}

interface Token { token: string; region: string; expires_in: number; provider: string }
let cached: { value: Token; expiresAt: number } | null = null;

async function getToken(): Promise<Token> {
  if (cached && Date.now() < cached.expiresAt) return cached.value;
  try {
    const value = await post<Token>("/speech/token");
    if (value.provider !== "azure") throw new SpeechError("UNAVAILABLE");
    cached = { value, expiresAt: Date.now() + (value.expires_in - 60) * 1000 };
    return value;
  } catch (error) {
    if (error instanceof SpeechError) throw error;
    if (error instanceof ApiError) throw new SpeechError("UNAVAILABLE");
    throw new SpeechError("FAILED");
  }
}

const recognitionLocale = (lang: Lang) => (lang === "te" ? "te-IN" : "en-IN");
const voiceName = (lang: Lang) =>
  lang === "te"
    ? import.meta.env.VITE_TTS_VOICE_TE ?? "te-IN-ShrutiNeural"
    : import.meta.env.VITE_TTS_VOICE_EN ?? "en-IN-NeerjaNeural";

async function ensureMicrophone(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia) throw new SpeechError("UNAVAILABLE");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
  } catch {
    throw new SpeechError("MIC_DENIED");
  }
}

let activeBrowserRecognizer: BrowserSpeechRecognition | null = null;
let activeAzureRecognizer: any | null = null;

async function recognizeWithBrowser(lang: Lang): Promise<{ text: string; confidence: number | null }> {
  if (!isBrowserRecognitionSupported()) throw new SpeechError("UNAVAILABLE");
  await ensureMicrophone();
  const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
  if (!Recognition) throw new SpeechError("UNAVAILABLE");
  const recognizer = new Recognition();
  activeBrowserRecognizer = recognizer;
  recognizer.lang = lang === "te" ? "te-IN" : "en-IN";
  recognizer.continuous = false;
  recognizer.interimResults = false;
  return new Promise((resolve, reject) => {
    recognizer.onresult = (event) => {
      const result = event.results?.[0]?.[0];
      if (result?.transcript?.trim()) {
        resolve({ text: result.transcript.trim(), confidence: typeof result.confidence === "number" ? result.confidence : null });
      } else {
        reject(new SpeechError("NO_SPEECH"));
      }
    };
    recognizer.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        reject(new SpeechError("MIC_DENIED"));
      } else if (event.error === "no-speech") {
        reject(new SpeechError("NO_SPEECH"));
      } else {
        reject(new SpeechError("FAILED"));
      }
    };
    recognizer.onend = () => {
      if (activeBrowserRecognizer === recognizer) activeBrowserRecognizer = null;
    };
    try {
      recognizer.start();
    } catch {
      reject(new SpeechError("FAILED"));
    }
  });
}

export function cancelListening(): void {
  if (activeAzureRecognizer) {
    try {
      activeAzureRecognizer.close();
    } catch {
      /* already closed */
    }
    activeAzureRecognizer = null;
  }
  if (activeBrowserRecognizer) {
    try {
      activeBrowserRecognizer.abort();
    } catch {
      try {
        activeBrowserRecognizer.stop();
      } catch {
        /* already stopped */
      }
    }
    activeBrowserRecognizer = null;
  }
  stopSpeaking();
}

/** Listen for one utterance. Resolves with the transcript and the recogniser's confidence. */
export async function recognizeOnce(lang: Lang): Promise<{ text: string; confidence: number | null }> {
  let azureToken: Token | null = null;
  try {
    azureToken = await getToken();
  } catch {
    azureToken = null;
  }
  if (!azureToken) {
    return recognizeWithBrowser(lang);
  }
  await ensureMicrophone();
  const { token, region } = azureToken;
  const sdk = await import("microsoft-cognitiveservices-speech-sdk");
  const config = sdk.SpeechConfig.fromAuthorizationToken(token, region);
  config.speechRecognitionLanguage = recognitionLocale(lang);
  config.outputFormat = sdk.OutputFormat.Detailed;
  const recognizer = new sdk.SpeechRecognizer(config, sdk.AudioConfig.fromDefaultMicrophoneInput());
  activeAzureRecognizer = recognizer;
  return new Promise((resolve, reject) => {
    recognizer.recognizeOnceAsync(
      (result) => {
        recognizer.close();
        if (activeAzureRecognizer === recognizer) activeAzureRecognizer = null;
        if (result.reason === sdk.ResultReason.RecognizedSpeech && result.text.trim()) {
          let confidence: number | null = null;
          try {
            const detail = JSON.parse(result.properties.getProperty(sdk.PropertyId.SpeechServiceResponse_JsonResult));
            const value = detail?.NBest?.[0]?.Confidence;
            confidence = typeof value === "number" ? value : null;
          } catch {
            confidence = null;
          }
          resolve({ text: result.text.trim(), confidence });
        } else if (result.reason === sdk.ResultReason.NoMatch || result.reason === sdk.ResultReason.RecognizedSpeech) {
          reject(new SpeechError("NO_SPEECH"));
        } else {
          reject(new SpeechError("FAILED"));
        }
      },
      () => {
        recognizer.close();
        if (activeAzureRecognizer === recognizer) activeAzureRecognizer = null;
        reject(new SpeechError("FAILED"));
      },
    );
  });
}

let activeSynth: { close: () => void } | null = null;

/** Speak a reply aloud. Failures are reported to the caller; the text is always on screen. */
export async function speak(text: string, lang: Lang): Promise<void> {
  let azureToken: Token | null = null;
  try {
    azureToken = await getToken();
  } catch {
    azureToken = null;
  }
  if (!azureToken) {
    if (!isBrowserSynthesisSupported()) throw new SpeechError("UNAVAILABLE");
    stopSpeaking();
    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang === "te" ? "te-IN" : "en-IN";
      utterance.onend = () => resolve();
      utterance.onerror = () => reject(new SpeechError("FAILED"));
      window.speechSynthesis.speak(utterance);
    });
  }
  const { token, region } = azureToken;
  const sdk = await import("microsoft-cognitiveservices-speech-sdk");
  const config = sdk.SpeechConfig.fromAuthorizationToken(token, region);
  config.speechSynthesisVoiceName = voiceName(lang);
  stopSpeaking();
  const synth = new sdk.SpeechSynthesizer(config);
  activeSynth = synth;
  return new Promise((resolve, reject) => {
    synth.speakTextAsync(
      text,
      () => {
        synth.close();
        if (activeSynth === synth) activeSynth = null;
        resolve();
      },
      () => {
        synth.close();
        if (activeSynth === synth) activeSynth = null;
        reject(new SpeechError("FAILED"));
      },
    );
  });
}

export function stopSpeaking(): void {
  if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* browser synthesis is unavailable */
    }
  }
  if (activeSynth) {
    try {
      activeSynth.close();
    } catch {
      /* already closed */
    }
    activeSynth = null;
  }
}
