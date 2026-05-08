// Visionneuse OpenSeadragon de la vue item.
//
// Le serveur embarque la résolution de chaque fichier dans
// <script id="sources-fichiers" type="application/json"> sous la
// forme { "<fichier_id>": { primary: {type,url}, fallback: {...} } }.
// La visionneuse est instanciée une fois (sans source) ; un click
// sur une vignette du panneau_fichiers appelle viewer.open(source)
// avec fallback sur l'événement open-failed (typique : timeout
// IIIF Nakala).

(function () {
  const sourcesNode = document.getElementById("sources-fichiers");
  const panneau = document.querySelector("[data-panneau-fichiers]");
  const conteneur = document.getElementById("visionneuse");
  const placeholder = document.getElementById("visionneuse-placeholder");
  const bandeau = document.getElementById("visionneuse-bandeau");
  if (!sourcesNode || !panneau || !conteneur || typeof OpenSeadragon === "undefined") {
    return;
  }

  const sources = JSON.parse(sourcesNode.textContent || "{}");
  const viewer = OpenSeadragon({
    element: conteneur,
    showNavigationControl: true,
    showRotationControl: true,
    visibilityRatio: 1,
    minZoomLevel: 0.5,
    defaultZoomLevel: 1,
    homeFillsViewer: true,
  });

  // OpenSeadragon attend un string pour IIIF/DZI (résolu via URL),
  // un objet `{type:"image", url}` pour une image plate.
  const ADAPTERS = {
    iiif: (cfg) => cfg.url,
    dzi: (cfg) => cfg.url,
    image: (cfg) => ({ type: "image", url: cfg.url }),
  };

  function tileSourceFromConfig(cfg) {
    const adapter = cfg && ADAPTERS[cfg.type];
    return adapter ? adapter(cfg) : null;
  }

  const etat = { fichierId: null, nom: null, fallback: null };

  function ouvrir(fichierId, nom) {
    const cfg = sources[fichierId];
    const libelle = nom || `Fichier #${fichierId}`;
    if (!cfg || !cfg.primary) {
      bandeau.textContent = "Aucune source d'image disponible.";
      return;
    }
    etat.fichierId = fichierId;
    etat.nom = libelle;
    etat.fallback = cfg.fallback;
    placeholder.style.display = "none";
    bandeau.textContent = libelle;
    viewer.open(tileSourceFromConfig(cfg.primary));
  }

  viewer.addHandler("open-failed", function () {
    if (etat.fallback && etat.fichierId !== null) {
      const fb = etat.fallback;
      etat.fallback = null; // une seule chance
      bandeau.textContent = `${etat.nom} (fallback)`;
      viewer.open(tileSourceFromConfig(fb));
    } else {
      bandeau.textContent = "Échec du chargement.";
    }
  });

  panneau.addEventListener("click", function (event) {
    const cible = event.target.closest("[data-fichier-id]");
    if (!cible) return;
    event.preventDefault(); // évite la navigation vers ?fichier=X
    const id = cible.dataset.fichierId;
    const nom = cible.dataset.nomFichier;
    panneau.querySelectorAll("[data-fichier-id]").forEach((el) =>
      el.classList.remove("bg-blue-50/60")
    );
    cible.classList.add("bg-blue-50/60");
    ouvrir(id, nom);
    const url = new URL(window.location.href);
    url.searchParams.set("fichier", id);
    history.replaceState(null, "", url.toString());
  });

  if (window.FICHIER_INITIAL_ID) {
    const cible = panneau.querySelector(
      `[data-fichier-id="${window.FICHIER_INITIAL_ID}"]`
    );
    if (cible) cible.click();
  }
})();
