/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        fit: "#10b981",       // calm green
        sick: "#f59e0b",      // amber
        caution: "#f97316",   // orange
        stopstart: "#ef4444", // red
        block: "#8b5cf6",     // violet
      }
    },
  },
  plugins: [],
}
