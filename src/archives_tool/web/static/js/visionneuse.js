// Visionneuse OpenSeadragon de la vue item.
//
// Le serveur embarque la résolution de chaque fichier dans
// <script id="sources-fichiers" type="application/json"> sous la
// forme { "<fichier_id>": { primary: {type,url}, fallback: {...} } }.
// La visionneuse est instanciée une fois (sans source) ; un click
// sur une vignette appelle viewer.open(source) avec fallback sur
// l'événement open-failed (typique : timeout IIIF Nakala).

(function () {
  const sourcesNode = document.getElementById("sources-fichiers");
  const liste = document.getElementById("liste-fichiers");
  const conteneur = document.getElementById("visionneuse");
  const placeholder = document.getElementById("visionneuse-placeholder");
  const bandeau = document.getElementById("visionneuse-bandeau");
  if (!sourcesNode || !liste || !conteneur || typeof OpenSeadragon === "undefined") {
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

  // État courant ; reset à chaque `ouvrir()` pour qu'un nouveau click
  // ne propage pas le fallback d'un fichier précédent ni le suffixe
  // « (fallback) » dans le bandeau.
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

  liste.addEventListener("click", function (event) {
    const bouton = event.target.closest("button[data-fichier-id]");
    if (!bouton) return;
    const id = bouton.dataset.fichierId;
    const nom = bouton.dataset.nomFichier;
    document.querySelectorAll("#liste-fichiers button").forEach((b) =>
      b.classList.remove("bg-gray-100")
    );
    bouton.classList.add("bg-gray-100");
    ouvrir(id, nom);
    // URL bookmarkable sans full reload.
    const url = new URL(window.location.href);
    url.searchParams.set("fichier", id);
    history.replaceState(null, "", url.toString());
  });

  if (window.FICHIER_INITIAL_ID) {
    const bouton = liste.querySelector(
      `button[data-fichier-id="${window.FICHIER_INITIAL_ID}"]`
    );
    if (bouton) bouton.click();
  }
})();
