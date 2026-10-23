import type { Config } from "tailwindcss";

// Every colour comes from styles/tokens.css, so light/dark switch automatically
// with prefers-color-scheme. The accent is reserved for the primary action and
// active states.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      bg: token("bg"),
      surface: token("surface"),
      fg: token("fg"),
      muted: token("muted"),
      // Hairlines carry their own per-theme alpha (see tokens.css).
      hairline: "rgb(var(--hairline) / var(--hairline-alpha))",
      accent: token("accent"),
      "on-accent": token("on-accent"),
    },
    fontFamily: {
      sans: [
        "-apple-system",
        "BlinkMacSystemFont",
        '"SF Pro Text"',
        '"SF Pro Display"',
        '"Helvetica Neue"',
        "system-ui",
        "sans-serif",
      ],
    },
    fontSize: {
      // At most three sizes on any screen: display, body, caption.
      caption: ["13px", { lineHeight: "18px", letterSpacing: "-0.01em" }],
      body: ["17px", { lineHeight: "24px", letterSpacing: "-0.022em" }],
      display: ["clamp(34px, 6vw, 56px)", { lineHeight: "1.07", letterSpacing: "-0.03em", fontWeight: "600" }],
    },
    borderRadius: {
      none: "0",
      sm: "14px",
      md: "16px",
      lg: "20px",
      full: "9999px",
    },
    extend: {
      borderWidth: { hairline: "0.5px" },
      minHeight: { tap: "44px" },
      minWidth: { tap: "44px" },
      maxWidth: { content: "34rem" },
    },
  },
  plugins: [],
};

export default config;
