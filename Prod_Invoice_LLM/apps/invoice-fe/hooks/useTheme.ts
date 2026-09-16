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

    const applyThemeWithSuppressedTransitions = (mode: ThemeMode) => {
      document.documentElement.classList.add("theme-switching");
      document.documentElement.setAttribute("data-theme", mode);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          document.documentElement.classList.remove("theme-switching");
        });
      });
    };

    const handleThemeChange = (e: Event) => {
      const customEvent = e as CustomEvent<ThemeMode>;
      if (customEvent.detail) {
        setTheme(customEvent.detail);
        applyThemeWithSuppressedTransitions(customEvent.detail);
      }
    };

    window.addEventListener("theme-change", handleThemeChange);
    return () => {
      window.removeEventListener("theme-change", handleThemeChange);
    };
  }, []);

  const applyThemeWithSuppressedTransitions = (mode: ThemeMode) => {
    document.documentElement.classList.add("theme-switching");
    document.documentElement.setAttribute("data-theme", mode);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.documentElement.classList.remove("theme-switching");
      });
    });
  };

  const toggleTheme = () => {
    const nextTheme: ThemeMode = theme === "default" ? "infinevo" : "default";
    setTheme(nextTheme);
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    applyThemeWithSuppressedTransitions(nextTheme);
    window.dispatchEvent(new CustomEvent("theme-change", { detail: nextTheme }));
  };

  const setThemeMode = (mode: ThemeMode) => {
    setTheme(mode);
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
    applyThemeWithSuppressedTransitions(mode);
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
