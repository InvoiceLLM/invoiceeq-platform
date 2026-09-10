"use client";

import { useState, useEffect } from "react";

export type ThemeMode = "default" | "infinevo";

const THEME_STORAGE_KEY = "app_theme";

export function useTheme() {
  const [theme, setTheme] = useState<ThemeMode>("default");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const savedTheme = (window.localStorage.getItem(THEME_STORAGE_KEY) as ThemeMode) || "default";
    setTheme(savedTheme);
    document.documentElement.setAttribute("data-theme", savedTheme);

    const handleThemeChange = (e: Event) => {
      const customEvent = e as CustomEvent<ThemeMode>;
      if (customEvent.detail) {
        setTheme(customEvent.detail);
        document.documentElement.setAttribute("data-theme", customEvent.detail);
      }
    };

    window.addEventListener("theme-change", handleThemeChange);
    return () => {
      window.removeEventListener("theme-change", handleThemeChange);
    };
  }, []);

  const toggleTheme = () => {
    const nextTheme: ThemeMode = theme === "default" ? "infinevo" : "default";
    setTheme(nextTheme);
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    document.documentElement.setAttribute("data-theme", nextTheme);
    window.dispatchEvent(new CustomEvent("theme-change", { detail: nextTheme }));
  };

  const setThemeMode = (mode: ThemeMode) => {
    setTheme(mode);
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
    document.documentElement.setAttribute("data-theme", mode);
    window.dispatchEvent(new CustomEvent("theme-change", { detail: mode }));
  };

  return {
    theme,
    toggleTheme,
    setThemeMode,
    isInfinevo: theme === "infinevo",
    mounted,
  };
}
