import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Segoe UI"',
          '"Aptos"',
          '"Helvetica Neue"',
          '"Roboto"',
          '"Open Sans"',
          '"Arial"',
          'sans-serif',
        ],
        enterprise: [
          '"Segoe UI"',
          '"Aptos"',
          '"Helvetica Neue"',
          '"Roboto"',
          '"Open Sans"',
          '"Arial"',
          'sans-serif',
        ],
        mono: ['"Cascadia Code"', '"Consolas"', '"Courier New"', 'monospace'],
      },
      fontSize: {
        'page-title': ['32px', { lineHeight: '1.25', letterSpacing: '-0.5px' }],
        'section-title': ['24px', { lineHeight: '1.3' }],
        'card-title': ['18px', { lineHeight: '1.4' }],
        'modal-title': ['22px', { lineHeight: '1.3' }],
        'body-normal': ['14px', { lineHeight: '1.6' }],
        'btn-text': ['14px', { lineHeight: '1.4', letterSpacing: '0.2px' }],
        'nav-text': ['15px', { lineHeight: '1.4' }],
        'sidebar-text': ['14px', { lineHeight: '1.5' }],
        'th-text': ['13px', { lineHeight: '1.4', letterSpacing: '0.3px' }],
        'td-text': ['13px', { lineHeight: '1.5' }],
        'label-text': ['14px', { lineHeight: '1.4' }],
        'input-text': ['14px', { lineHeight: '1.4' }],
        'badge-text': ['12px', { lineHeight: '1.3' }],
        'tooltip-text': ['12px', { lineHeight: '1.3' }],
      },
      fontWeight: {
        'page-title': '700',
        'section-title': '600',
        'card-title': '600',
        'modal-title': '700',
        'btn-weight': '600',
        'nav-weight': '600',
        'sidebar-weight': '500',
        'th-weight': '600',
        'label-weight': '500',
        'badge-weight': '600',
      },
      colors: {
        canvas: "#0B0F19",
        panel: "#111827",
        panelBorder: "#222D3D",
        brandPrimary: "#10B981",
        brandPrimaryHover: "#059669",
        pageTitle: "#1F2937",
        sectionTitle: "#374151",
        bodyText: "#4B5563",
        tableData: "#2C2C2C",
        placeholderText: "#9CA3AF",
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "gradient-conic":
          "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",
      },
    },
  },
  plugins: [],
};
export default config;
