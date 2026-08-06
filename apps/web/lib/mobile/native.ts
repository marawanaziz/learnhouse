// Safe wrappers around the Capacitor runtime. The mobile native shell injects
// `window.Capacitor` automatically when the wrapped web app is loaded under
// the WKWebView (iOS) or Android WebView. In a regular browser the global is
// missing and every helper here becomes a no-op so the web bundle is unaffected.
//
// All exports are tree-shakable; React 19's compiler drops unused branches.

export type BBUPlatform = "ios" | "android" | "web";

export interface BBUCapacitorGlobal {
  isNativePlatform: () => boolean;
  getPlatform: () => BBUPlatform;
  Plugins?: Record<string, unknown>;
}

declare global {
  interface Window {
    Capacitor?: BBUCapacitorGlobal;
  }
}

const BRAND = {
  surface: "#FFF8F0",
  navy: "#0F2F4F",
  coral: "#E27063",
};

export function getCapacitor(): BBUCapacitorGlobal | undefined {
  if (typeof window === "undefined") return undefined;
  return window.Capacitor;
}

export function isNativePlatform(): boolean {
  return Boolean(getCapacitor()?.isNativePlatform());
}

export function getPlatform(): BBUPlatform {
  const cap = getCapacitor();
  if (!cap) return "web";
  const p = cap.getPlatform();
  return p === "ios" || p === "android" ? p : "web";
}

function callPlugin<T>(name: string, method: string, args?: unknown): Promise<T | undefined> {
  const cap = getCapacitor();
  if (!cap?.isNativePlatform()) return Promise.resolve(undefined);
  const plugin = (cap.Plugins as Record<string, any> | undefined)?.[name];
  if (!plugin || typeof plugin[method] !== "function") return Promise.resolve(undefined);
  try {
    const out = plugin[method](args ?? {});
    return Promise.resolve(out instanceof Promise ? (out as Promise<T>) : (out as T));
  } catch {
    return Promise.resolve(undefined);
  }
}

export const brand = BRAND;

// Mirror of @capacitor/status-bar — keeps a reference of the live plugin.
export const StatusBar = {
  setStyle: (style: "DARK" | "LIGHT") =>
    callPlugin("StatusBar", "setStyle", { style }),
  setBackgroundColor: (color: string) =>
    callPlugin("StatusBar", "setBackgroundColor", { color }),
  setOverlaysWebView: (overlay: boolean) =>
    callPlugin("StatusBar", "setOverlaysWebView", { overlay }),
};

// Mirror of @capacitor/splash-screen.
export const SplashScreen = {
  show: () => callPlugin("SplashScreen", "show", { autoHide: false }),
  hide: () => callPlugin("SplashScreen", "hide", {}),
};

// Mirror of @capacitor/haptics.
export const Haptics = {
  impact: (style: "LIGHT" | "MEDIUM" | "HEAVY" = "LIGHT") =>
    callPlugin("Haptics", "impact", { style }),
  selection: () => callPlugin("Haptics", "selectionChanged", {}),
  vibrate: () => callPlugin("Haptics", "vibrate", {}),
};

// Mirror of @capacitor/keyboard.
export const Keyboard = {
  setStyle: (style: "DARK" | "LIGHT" | "DEFAULT") =>
    callPlugin("Keyboard", "setStyle", { style }),
  setResizeMode: (mode: "native" | "body" | "ionic" | "none") =>
    callPlugin("Keyboard", "setResizeMode", { mode }),
  addListener: (
    event: "keyboardWillShow" | "keyboardDidShow" | "keyboardWillHide" | "keyboardDidHide",
    cb: (_info: { keyboardHeight: number }) => void,
  ) => {
    if (!isNativePlatform()) return () => undefined;
    const cap = getCapacitor();
    const plugin = (cap?.Plugins as Record<string, any> | undefined)?.Keyboard;
    const handle = plugin?.addListener?.(event, cb);
    return () => handle?.remove?.();
  },
};

// Mirror of @capacitor/share — used for course/community share links.
export const Share = {
  share: (opts: { title?: string; text?: string; url?: string; dialogTitle?: string }) =>
    callPlugin("Share", "share", opts),
};

// Mirror of @capacitor/browser — used to launch Stripe Checkout in the
// in-app browser so the user can return to the WebView after payment.
export const Browser = {
  open: (opts: { url: string; presentationStyle?: "fullscreen" | "popover"; windowName?: string }) =>
    callPlugin("Browser", "open", opts),
  close: () => callPlugin("Browser", "close", {}),
};

// Mirror of @capacitor/network — used for the connectivity banner.
export const Network = {
  getStatus: () =>
    callPlugin<{ connected: boolean; connectionType: string }>("Network", "getStatus"),
  addListener: (
    cb: (_status: { connected: boolean; connectionType: string }) => void,
  ) => {
    if (!isNativePlatform()) return () => undefined;
    const cap = getCapacitor();
    const plugin = (cap?.Plugins as Record<string, any> | undefined)?.Network;
    const handle = plugin?.addListener?.("networkStatusChange", cb);
    return () => handle?.remove?.();
  },
};

// Initialize the native shell's chrome once on first render.
export async function initNativeChrome() {
  if (!isNativePlatform()) return;
  await Promise.allSettled([
    StatusBar.setStyle("DARK"),
    StatusBar.setBackgroundColor(BRAND.surface),
    StatusBar.setOverlaysWebView(false),
    Keyboard.setStyle("DARK"),
    Keyboard.setResizeMode("native"),
    SplashScreen.hide(),
  ]);
}

let initialized = false;

export function ensureInitialized() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  if (isNativePlatform()) {
    document.documentElement.classList.add("bbu-native");
    document.documentElement.dataset.bbuPlatform = getPlatform();
    void initNativeChrome();
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", ensureInitialized, { once: true });
}
