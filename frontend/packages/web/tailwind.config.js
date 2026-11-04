/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        mil: {
          bg: '#0a1628',
          panel: '#0d1f3c',
          border: '#1a3a5c',
          cyan: '#00e5ff',
          amber: '#ffc107',
          text: '#8ba4c4',
          green: '#00e676',
          red: '#ff1744',
          dim: '#4a6a8a',
        },
        // Keep old names as aliases during transition
        future: {
          dark: '#0a1628',
          darker: '#060811',
          darkest: '#020308',
          primary: '#00e5ff',
          secondary: '#1a3a5c',
          accent: '#00e5ff',
          light: '#8ba4c4',
          success: '#00e676',
          warning: '#ffc107',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      animation: {
        'pulse-subtle': 'pulse-subtle 3s ease-in-out infinite',
        'slide-in': 'slide-in 0.3s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
        'float': 'float 6s ease-in-out infinite',
        'scanline': 'scanline 4s linear infinite',
        'blink': 'blink 1s step-end infinite',
        'border-pulse': 'border-pulse 2s ease-in-out infinite',
      },
      keyframes: {
        'pulse-subtle': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.85' },
        },
        'slide-in': {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        'scanline': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'border-pulse': {
          '0%, 100%': { borderColor: 'rgba(0, 229, 255, 0.3)' },
          '50%': { borderColor: 'rgba(0, 229, 255, 0.6)' },
        },
      },
      boxShadow: {
        'glass': '0 8px 32px 0 rgba(0, 10, 30, 0.8)',
        'glow': '0 0 20px rgba(0, 229, 255, 0.1)',
        'glow-lg': '0 0 40px rgba(0, 229, 255, 0.15)',
        'glow-cyan': '0 0 10px rgba(0, 229, 255, 0.3)',
      },
    },
  },
  plugins: [],
}
