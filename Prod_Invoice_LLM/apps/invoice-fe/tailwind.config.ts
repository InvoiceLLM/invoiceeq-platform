import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        "bg-main": "#0B0F19",
        "bg-panel": "rgba(21, 27, 38, 0.75)",
        "border-default": "#222D3D",
        "accent-green": "#10B981",
        "accent-red": "#EF4444",
        "accent-blue": "#3B82F6",
        "accent-yellow": "#F59E0B",
      },
    },
  },
  plugins: [],
};
export default config;
