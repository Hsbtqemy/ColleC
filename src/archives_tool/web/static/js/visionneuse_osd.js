// Instancie OpenSeadragon sur tous les `<div class="visionneuse-osd">`
// présents dans la page. Lit `data-source` (JSON) qui contient :
//   { primary: {type, url}, fallback: {type, url} | null,
//     telecharger: "...", nom: "..." }
//
// Format passé à OpenSeadragon :
// - type 'iiif' / 'dzi' : tileSources = url (string).
// - type 'image'        : tileSources = { type: 'image', url }.
//
// Sur l'événement open-failed (fichier absent du disque, dérivé pas
// généré, format non supporté côté tuile…), on retombe sur la source
// secondaire si elle existe, sinon on affiche un message + lien
// télécharger.

(function () {
  if (typeof OpenSeadragon === "undefined") return;

  function tuilesPour(source) {
    if (!source) return null;
    if (source.type === "image") {
      return { type: "image", url: source.url };
    }
    // iiif / dzi : OSD accepte la chaîne directement.
    return source.url;
  }

  function afficherFallback(viz, telecharger, nom) {
    viz.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;
                  justify-content:center;height:100%;padding:24px;color:#fff;
                  background:#1a1a1a;border-radius:6px;text-align:center;">
        <p style="font-size:14px;margin-bottom:14px;max-width:360px;">
          Impossible d'afficher l'aperçu de
          <strong style="font-family:monospace;">${nom}</strong>.
        </p>
        <a href="${telecharger}"
           style="padding:6px 14px;font-size:13px;background:#fff;color:#1a1a1a;
                  border-radius:4px;text-decoration:none;">
          Télécharger
        </a>
      </div>`;
  }

  function instancier(viz) {
    let data;
    try {
      data = JSON.parse(viz.dataset.source);
    } catch (e) {
      return;
    }
    const primary = tuilesPour(data.primary);
    if (!primary) {
      afficherFallback(viz, data.telecharger, data.nom);
      return;
    }
    const osd = OpenSeadragon({
      element: viz,
      tileSources: primary,
      showNavigationControl: true,
      showRotationControl: true,
      showFullPageControl: true,
      gestureSettingsMouse: { clickToZoom: false },
    });
    osd.addHandler("open-failed", function () {
      const fb = tuilesPour(data.fallback);
      if (fb) {
        try {
          osd.open(fb);
          return;
        } catch (e) {
          // tombe au fallback HTML
        }
      }
      osd.destroy();
      afficherFallback(viz, data.telecharger, data.nom);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document
      .querySelectorAll(".visionneuse-osd[data-source]")
      .forEach(instancier);
  });
})();
