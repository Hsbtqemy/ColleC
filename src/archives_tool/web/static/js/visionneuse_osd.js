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
    // Construction DOM safe : `nom` est le nom_fichier (free text issu
    // d'imports tableur, peut contenir n'importe quel caractere HTML).
    // `telecharger` est une URL construite mais on la passe quand meme
    // via la propriete href plutot que par interpolation dans une
    // chaine HTML — anti-injection defensive (si jamais quelqu'un
    // refactor src_brut pour inclure du user data).
    viz.replaceChildren();
    const wrap = document.createElement("div");
    wrap.style.cssText = "display:flex;flex-direction:column;align-items:center;" +
      "justify-content:center;height:100%;padding:24px;color:#fff;" +
      "background:#1a1a1a;border-radius:6px;text-align:center;";

    const p = document.createElement("p");
    p.style.cssText = "font-size:14px;margin-bottom:14px;max-width:360px;";
    p.appendChild(document.createTextNode("Impossible d'afficher l'aperçu de "));
    const strong = document.createElement("strong");
    strong.style.fontFamily = "monospace";
    strong.textContent = nom;
    p.appendChild(strong);
    p.appendChild(document.createTextNode("."));
    wrap.appendChild(p);

    const a = document.createElement("a");
    a.href = telecharger;
    a.style.cssText = "padding:6px 14px;font-size:13px;background:#fff;" +
      "color:#1a1a1a;border-radius:4px;text-decoration:none;";
    a.textContent = "Télécharger";
    wrap.appendChild(a);

    viz.appendChild(wrap);
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
      // Les icônes de contrôle (zoom, home, full page, rotation) sont
      // servies par FastAPI sous /static/. Sans ce préfixe, OSD tente
      // de les charger depuis `/images/` (chemin par défaut) et les
      // boutons restent invisibles ou cassés.
      prefixUrl: "/static/js/vendor/openseadragon/images/",
      showNavigationControl: true,
      showRotationControl: true,
      showFullPageControl: true,
      gestureSettingsMouse: { clickToZoom: false },
    });
    // Expose l'instance OSD + fichier_id pour les scripts qui se
    // greffent (Annotorious, mesures, etc.). Pattern d'événement
    // pour découpler — pas de couplage direct avec un script tiers.
    osd.addHandler("open", function () {
      viz.dispatchEvent(new CustomEvent("visionneuse:pret", {
        bubbles: true,
        detail: { osd: osd, fichier_id: data.fichier_id || null },
      }));
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
