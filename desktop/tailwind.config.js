/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        jarvis: {
          dark: '#0a0a0c',
          card: 'rgba(20, 20, 24, 0.6)',
          border: 'rgba(255, 255, 255, 0.1)',
          cyan: '#00f0ff',
        }
      }
    },
  },
  plugins: [],
}
