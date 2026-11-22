/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#EEF7F6", 100: "#D5ECEA", 600: "#0F6E6A", 700: "#0B5855", 800: "#084340" },
      },
      fontFamily: {
        sans: ["'Noto Sans'", "'Noto Sans Telugu'", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
