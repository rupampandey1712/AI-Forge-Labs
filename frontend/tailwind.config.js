/** @type {import('tailwindcss').Config} */

// DESIGN DIRECTION (spec §2: "not visually childish")
// The reference points are a modern IDE and a mission-control console, not a
// cartoon. That means: a deep navy ground rather than pure black, one cyan
// accent that carries meaning (progress, focus, "this is live"), amber for
// warnings and red reserved *exclusively* for incidents — so when the
// Debugging Dungeon turns red, it reads as an alarm rather than decoration.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        forge: {
          950: '#05070f',
          900: '#0b1020',
          850: '#0f152a',
          800: '#141b33',
          700: '#1c2544',
          600: '#273154',
          500: '#3a4670',
          400: '#5b6a99',
          300: '#8b99c4',
          200: '#bcc6e3',
          100: '#e3e8f7',
        },
        accent: {
          DEFAULT: '#22d3ee',
          soft: '#67e8f9',
          deep: '#0891b2',
        },
        signal: {
          xp: '#a78bfa',
          success: '#34d399',
          warn: '#fbbf24',
          danger: '#f43f5e',
          decay: '#fb923c',
        },
      },
      fontFamily: {
        sans: ['Inter var', 'Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'SFMono-Regular', 'Consolas', 'monospace'],
        display: ['Space Grotesk', 'Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 24px -4px rgb(34 211 238 / 0.45)',
        'glow-lg': '0 0 48px -8px rgb(34 211 238 / 0.55)',
        danger: '0 0 24px -4px rgb(244 63 94 / 0.5)',
        panel: '0 1px 0 0 rgb(255 255 255 / 0.04) inset, 0 12px 32px -12px rgb(0 0 0 / 0.7)',
      },
      backgroundImage: {
        grid: `linear-gradient(rgb(255 255 255 / 0.035) 1px, transparent 1px),
               linear-gradient(90deg, rgb(255 255 255 / 0.035) 1px, transparent 1px)`,
        'radial-fade': 'radial-gradient(ellipse at top, rgb(34 211 238 / 0.10), transparent 62%)',
      },
      backgroundSize: { grid: '44px 44px' },
      keyframes: {
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '100%': { transform: 'scale(1.8)', opacity: '0' },
        },
        'xp-rise': {
          '0%': { transform: 'translateY(0) scale(0.85)', opacity: '0' },
          '18%': { transform: 'translateY(-8px) scale(1.06)', opacity: '1' },
          '100%': { transform: 'translateY(-56px) scale(1)', opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'scan-line': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(400%)' },
        },
        'glitch-x': {
          '0%,100%': { transform: 'translateX(0)' },
          '20%': { transform: 'translateX(-2px)' },
          '40%': { transform: 'translateX(3px)' },
          '60%': { transform: 'translateX(-1px)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
      },
      animation: {
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.22, 1, 0.36, 1) infinite',
        'xp-rise': 'xp-rise 1.3s cubic-bezier(0.22, 1, 0.36, 1) forwards',
        shimmer: 'shimmer 2.2s infinite',
        'scan-line': 'scan-line 5s linear infinite',
        glitch: 'glitch-x 0.32s steps(2) 2',
        float: 'float 5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
