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

// PDF.js : visionneuse PDF pour la liseuse consultation (Lot 2).
// On utilise le build LEGACY (et non `build/`) car le build courant
// pdfjs-dist v5.6 utilise des features ES2024 (notamment
// Map.prototype.getOrInsertComputed) que les navigateurs récents
// mais pas bleeding-edge ne supportent pas encore. Le legacy cible
// les navigateurs avec ~2 ans de retard et reste full-featured.
copierFichier(
  "node_modules/pdfjs-dist/legacy/build/pdf.min.mjs",
  join(RACINE_VENDOR, "pdfjs"),
  "pdf.min.mjs",
);
copierFichier(
  "node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs",
  join(RACINE_VENDOR, "pdfjs"),
  "pdf.worker.min.mjs",
);
// WASM (OpenJPEG pour JPEG 2000, JBIG2, qcms) : nécessaire pour
// décoder les images embarquées dans les fac-similés Nakala (JP2
// notamment). Sans ces fichiers, le PDF se charge mais les images
// ne s'affichent pas (seul le texte OCR reste).
copierDossier(
  "node_modules/pdfjs-dist/wasm",
  join(RACINE_VENDOR, "pdfjs", "wasm"),
);

// Annotorious (plugin OpenSeadragon) — annotations IIIF / W3C
// sur l'image. Mode édition activable depuis la visionneuse. Voir
// `docs/developpeurs/annotations-image-future.md`.
copierFichier(
  "node_modules/@recogito/annotorious-openseadragon/dist/openseadragon-annotorious.min.js",
  join(RACINE_VENDOR, "annotorious"),
  "openseadragon-annotorious.min.js",
);
copierFichier(
  "node_modules/@recogito/annotorious-openseadragon/dist/annotorious.min.css",
  join(RACINE_VENDOR, "annotorious"),
  "annotorious.min.css",
);

console.log("✓ Vendors synchronisés.");
