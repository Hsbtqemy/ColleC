/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/archives_tool/web/templates/**/*.html",
    "./src/archives_tool/web/static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["SF Mono", "Monaco", "Consolas", "monospace"],
      },
      colors: {
        border: {
          tertiary: "rgba(0, 0, 0, 0.08)",
          secondary: "rgba(0, 0, 0, 0.15)",
          primary: "rgba(0, 0, 0, 0.25)",
        },
      },
    },
  },
  plugins: [],
};
