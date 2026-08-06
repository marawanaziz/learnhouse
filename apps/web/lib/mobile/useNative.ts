"use client";

import { useEffect, useState } from "react";

import {
  Network,
  brand,
  getPlatform,
  initNativeChrome,
  isNativePlatform,
} from "./native";

export function useNativePlatform() {
  // First render happens during SSR where window is undefined. After hydration
  // we reconcile from the actual Capacitor global. The first SSR frame renders
  // the desktop layout; the second frame (post-hydration) renders the mobile
  // chrome. We deliberately accept the brief swap to avoid SSR/CSR drift
  // producing hydration warnings.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // We have to defer the ready flag until after hydration so the SSR pass
    // renders the desktop layout, then the client pass layers the native
    // chrome on top. Calling setState inside an effect here is intentional.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(true);
    void initNativeChrome();
  }, []);

  return {
    ready,
    isNative: ready && isNativePlatform(),
    platform: getPlatform(),
    brand,
  };
}

export function useOnline() {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    if (typeof navigator === "undefined") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOnline(navigator.onLine);

    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    const off = Network.addListener((status) => setOnline(Boolean(status.connected)));

    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      off?.();
    };
  }, []);

  return online;
}
