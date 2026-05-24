/** @type {import('tailwindcss').Config} */
//
// Configuration Tailwind. Les couleurs sont organisées en trois familles :
// - bordures (border.tertiary/secondary/primary) — opacités du noir
// - états sémantiques (state-*) — points de badges, liens
// - segments d'avancement (seg-*) — versions désaturées pour les barres
//
// Les composants du bundle handoff Claude Design hard-codent leurs couleurs
// inline ; ces tokens existent pour les usages annexes (liens, futurs
// composants). Cf. handoff/docs/composants_ui.md.
module.exports = {
  content: [
    "./src/archives_tool/web/templates/**/*.html",
    "./src/archives_tool/web/static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "system-ui", "-apple-system", "Segoe UI", "Roboto",
          "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: [
          "ui-monospace", "SF Mono", "Cascadia Code",
          "Menlo", "Consolas", "monospace",
        ],
      },
      // Tailwind defaults : text-xs=12px, text-sm=14px. Sur écran
      // large + corpus à lire (descriptions, métadonnées tabulaires),
      // 14px reste un peu serré. On bump à 13/15 pour gagner ~7% de
      // confort de lecture sans faire grossir l'interface comme un
      // passage direct à text-base (16px). Les `style="font-size:13px"`
      // inline dans les composants gardent leur valeur — ce sont les
      // classes `text-sm`/`text-xs` qui bougent.
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.15rem" }],  // 13px
        sm: ["0.9375rem", { lineHeight: "1.4rem" }],   // 15px
      },
      colors: {
        // Bordures fines : 1 px CSS, l'opacité du noir varie.
        border: {
          tertiary: "rgba(0, 0, 0, 0.08)",
          secondary: "rgba(0, 0, 0, 0.16)",
          primary: "rgba(0, 0, 0, 0.28)",
        },
        // Couleurs sémantiques (points de badges, accents).
        "state-info": "#378ADD",
        "state-warn": "#BA7517",
        "state-ok":   "#639922",
        "state-err":  "#E24B4A",
        "state-neutral": "#888780",
        // Versions désaturées pour les segments d'avancement.
        "seg-brouillon":  "#D3D1C7",
        "seg-a-verifier": "#FAC775",
        "seg-verifie":    "#B5D4F4",
        "seg-valide":     "#97C459",
        "seg-a-corriger": "#F0997B",
      },
    },
  },
  plugins: [],
};
