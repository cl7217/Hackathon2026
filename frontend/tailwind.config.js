/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Heebo', 'Arial', 'sans-serif'],
      },
      boxShadow: {
        card: '0 12px 40px -20px rgba(15, 45, 75, 0.18)',
      },
    },
  },
  plugins: [],
}
