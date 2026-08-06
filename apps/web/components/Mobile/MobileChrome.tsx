"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";

import { useSession } from "@components/Contexts/AuthContext";
import { useNativePlatform, useOnline } from "@lib/mobile/useNative";
import { Haptics } from "@lib/mobile/native";

// Top-level mobile chrome that only renders under the native shell. The
// entire component returns the desktop children when not in the Capacitor
// runtime, so there is zero visual diff for web users.
//
//   - Header: status-bar spacer + brand mark
//   - Body: children rendered with safe-area padding
//   - Tab bar: bottom navigation, fixed to the safe-area bottom
//   - Offline banner: shown when the network drops
export default function MobileChrome({ children }: { children: React.ReactNode }) {
  const { isNative, ready } = useNativePlatform();
  const { status } = useSession();
  const online = useOnline();
  const pathname = usePathname() ?? "/";

  const isAuthenticated = status === "authenticated";
  const tabs = useMemo(
    () => buildMobileTabs({ pathname, isAuthenticated }),
    [pathname, isAuthenticated],
  );

  if (!ready || !isNative) return <>{children}</>;

  return (
    <div className="bbu-mobile-shell" data-platform={isNative ? "ios" : "web"}>
      {!online && (
        <div className="bbu-offline" role="status">
          You’re offline. Reconnect to keep learning.
        </div>
      )}
      <header className="bbu-mobile-header">
        <div className="bbu-mobile-header__brand">
          <span className="bbu-mobile-header__mark" aria-hidden="true" />
          <span className="bbu-mobile-header__title">Birth &amp; Baby University</span>
        </div>
      </header>
      <main className="bbu-mobile-main">{children}</main>
      <nav className="bbu-mobile-tabbar" aria-label="Primary">
        {tabs.map((tab) => (
          <Link
            key={tab.path}
            href={tab.path}
            className={`bbu-mobile-tab${tab.active ? " is-active" : ""}`}
            onClick={() => void Haptics.selection()}
          >
            <span className="bbu-mobile-tab__icon" aria-hidden="true">
              {tab.icon}
            </span>
            <span className="bbu-mobile-tab__label">{tab.label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}

type Tab = { label: string; path: string; icon: string; active: boolean };

// Tabs are intentionally coarse. The org-scoped URL is derived from the first
// pathname segment; this gives each tenant its own landing context while
// staying inside Next's router.
function buildMobileTabs({
  pathname,
  isAuthenticated,
}: {
  pathname: string;
  isAuthenticated: boolean;
}): Tab[] {
  const segments = pathname.split("/").filter(Boolean);
  const orgBase = segments[0] === "orgs" && segments[1] ? `/orgs/${segments[1]}` : "/";

  const isActive = (test: string) =>
    pathname === test || pathname.startsWith(`${test}/`);

  const homeActive = pathname === "/" || pathname === orgBase;

  if (!isAuthenticated) {
    return [
      { label: "Home", path: "/", icon: "🏠", active: homeActive },
      { label: "Catalog", path: `${orgBase}/catalog`, icon: "📚", active: isActive(`${orgBase}/catalog`) },
      { label: "Sign in", path: "/auth/login", icon: "🔐", active: isActive("/auth") },
    ];
  }

  return [
    { label: "Home", path: `${orgBase}`, icon: "🏠", active: homeActive },
    { label: "Courses", path: `${orgBase}/courses`, icon: "📚", active: isActive(`${orgBase}/courses`) },
    { label: "Community", path: `${orgBase}/community`, icon: "💬", active: isActive(`${orgBase}/community`) },
    { label: "Profile", path: "/home/profile", icon: "👤", active: isActive("/home/profile") },
  ];
}
