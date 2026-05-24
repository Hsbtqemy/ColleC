// liseuse.js — interactions clavier pour la liseuse consultation
// (Lot 3 V0.9.x).
//
// Clavier :
// - ←  : page précédente (clic sur le bouton ‹ du bloc « Page » du
//        bandeau, qui déclenche le swap HTMX déjà câblé).
// - →  : page suivante.
// - Esc : retour à la page item édition (clic sur le lien « Cataloguer »).
//
// Skip si le focus est dans un input/textarea/contenteditable — on
// ne veut pas que ← → cassent la sélection texte du PDF par exemple.
//
// Le script est chargé sur `pages/lire_item.html` uniquement. HTMX
// swappe seulement #zone-visionneuse + bandeau + vignettes : ce
// script reste persistent dans la page complète.

(function () {
  function focusEstDansChampTexte() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if (el.isContentEditable) return true;
    // Le text layer PDF.js est sélectionnable — quand l'utilisateur
    // a sélectionné du texte, on laisse le navigateur gérer (copier,
    // etc). Mais on garde les raccourcis flèches actifs : la sélection
    // texte ne reçoit pas le focus actif (juste range).
    return false;
  }

  function declencherClic(selecteur) {
    var btn = document.querySelector(selecteur);
    if (!btn) return false;
    // Anchor avec hx-get : on dispatch un event "click" qui
    // déclenche le handler HTMX (équivalent au clic souris).
    btn.click();
    return true;
  }

  // Loading state HTMX cross-source : on toggle une classe sur
  // #zone-visionneuse à chaque swap, quelle que soit l'origine
  // (vignette dans le panneau OU bouton Page du bandeau, ce dernier
  // étant hors de .layout-liseuse donc non-couvert par hx-indicator).
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var target = e.detail && e.detail.target;
    if (target && target.id === "zone-visionneuse") {
      target.classList.add("en-chargement");
    }
  });
  function _retirerClasseChargement() {
    var zone = document.getElementById("zone-visionneuse");
    if (zone) zone.classList.remove("en-chargement");
  }
  document.body.addEventListener("htmx:afterSwap", _retirerClasseChargement);
  document.body.addEventListener("htmx:responseError", _retirerClasseChargement);
  document.body.addEventListener("htmx:sendError", _retirerClasseChargement);

  document.addEventListener("keydown", function (e) {
    if (focusEstDansChampTexte()) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    switch (e.key) {
      case "ArrowLeft":
        // Bouton ‹ « Page précédente » — sélection par title pour
        // éviter de matcher › si ‹ est désactivé (cas page 1).
        if (declencherClic('a[title="Page précédente"]')) {
          e.preventDefault();
        }
        break;
      case "ArrowRight":
        if (declencherClic('a[title="Page suivante"]')) {
          e.preventDefault();
        }
        break;
      case "Escape":
        // Lien « Cataloguer » du bandeau — retour vers page item édition.
        var lien = document.querySelector(
          'a[title^="Quitter la consultation"]'
        );
        if (lien) {
          lien.click();
          e.preventDefault();
        }
        break;
    }
  });
})();
