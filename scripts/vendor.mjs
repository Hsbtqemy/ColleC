// Copie les bundles vendor depuis node_modules vers
// src/archives_tool/web/static/js/vendor/. Le dossier `vendor/`
// est gitignoré — ce script est lancé après `npm install` pour
// régénérer les vendors localement.
//
// Multi-plateforme (utilise `fs` natif Node.js, pas `cp`/`mkdir`).
//
// Usage : `npm run vendor`

import { copyFileSync, cpSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const RACINE_VENDOR = "src/archives_tool/web/static/js/vendor";

/** Crée le dossier de destination puis copie un fichier unique. */
function copierFichier(src, destDir, destNom) {
  mkdirSync(destDir, { recursive: true });
  copyFileSync(src, join(destDir, destNom));
  console.log(`  ${src}\n  → ${join(destDir, destNom)}\n`);
}

/** Crée le dossier puis recopie un sous-dossier entier (récursif). */
function copierDossier(srcDir, destDir) {
  if (!existsSync(srcDir)) {
    throw new Error(`Source introuvable : ${srcDir}`);
  }
  mkdirSync(destDir, { recursive: true });
  cpSync(srcDir, destDir, { recursive: true });
  console.log(`  ${srcDir}\n  → ${destDir}\n`);
}

console.log("Synchronisation des vendors…\n");

// OpenSeadragon : visionneuse de la page item (avec assets images).
copierDossier(
  "node_modules/openseadragon/build/openseadragon",
  join(RACINE_VENDOR, "openseadragon"),
);

// Sortable.js : drag-drop du panneau colonnes (page collection).
copierFichier(
  "node_modules/sortablejs/Sortable.min.js",
  join(RACINE_VENDOR, "sortable"),
  "Sortable.min.js",
);

// HTMX : interactions partielles (toutes les pages, inclus dans base.html).
copierFichier(
  "node_modules/htmx.org/dist/htmx.min.js",
  join(RACINE_VENDOR, "htmx"),
  "htmx.min.js",
);

console.log("✓ Vendors synchronisés.");
