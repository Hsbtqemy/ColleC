/** @type {import('tailwindcss').Config} */
//
// archives-tool — extensions du `tailwind.config.js` pour la bibliothèque
// de composants. À fusionner dans le `theme.extend` existant.
//
// Aucune dépendance ajoutée. La compilation reste : `tailwindcss -i input.css
// -o output.css` via le script `npm run build:css`.
//
module.exports = {
  content: [
    './src/archives_tool/web/templates/**/*.html',
  ],
  theme: {
    extend: {
      fontFamily: {
        // Stack système, sans webfont. Utilisée par défaut sur <body>.
        sans: [
          'system-ui', '-apple-system', 'Segoe UI', 'Roboto',
          'Helvetica Neue', 'Arial', 'sans-serif',
        ],
        // Cotes, identifiants, DOI, hash. SF Mono natif sur macOS,
        // Cascadia / Consolas sur Windows.
        mono: [
          'ui-monospace', 'SF Mono', 'Cascadia Code',
          'Menlo', 'Consolas', 'monospace',
        ],
      },
      // Bordures fines `0.5 px` = 1 px CSS sur écrans HiDPI.
      // La valeur reste 1 px en CSS, c'est l'opacité du noir qui change.
      colors: {
        'border-tertiary':  'rgba(0, 0, 0, 0.08)',
        'border-secondary': 'rgba(0, 0, 0, 0.16)',
        'border-primary':   'rgba(0, 0, 0, 0.28)',

        // Couleurs sémantiques (points de badges, accents).
        // Volontairement non scannées pour éviter qu'on les utilise
        // comme remplissage d'arrière-plan : seuls les points de
        // badge et les liens y ont droit.
        'state-info': '#378ADD',
        'state-warn': '#BA7517',
        'state-ok':   '#639922',
        'state-err':  '#E24B4A',

        // Versions désaturées pour les segments d'avancement.
        'seg-brouillon':  '#D3D1C7',
        'seg-a-verifier': '#FAC775',
        'seg-verifie':    '#B5D4F4',
        'seg-valide':     '#97C459',
        'seg-a-corriger': '#F0997B',
      },
    },
  },
  plugins: [
    // Petit utilitaire `font-tabular` pour les nombres alignés à droite.
    function ({ addUtilities }) {
      addUtilities({
        '.font-tabular': { 'font-variant-numeric': 'tabular-nums' },
      });
    },
  ],
};
