// Navigation au clic sur une ligne de tableau marquée `data-row-href`.
//
// Délégué sur `document` → survit aux swaps HTMX (tri des colonnes,
// sauvegarde des préférences de colonnes qui remplacent #tableau-items).
// Inerte (no-op) tant qu'aucune ligne ne porte `data-row-href`.
//
// Ne déclenche PAS quand :
// - le clic vise une zone interactive (lien cote, bouton « − Retirer »,
//   édition d'état inline ▾/select, tout input/label/form) ;
// - une sélection de texte est en cours (l'utilisateur copie une valeur) ;
// - clic non primaire (le clic milieu est géré à part → nouvel onglet).
//
// La cote reste un vrai <a> : c'est le chemin clavier/lecteur d'écran.
(function () {
  "use strict";

  var SELECTEUR_INTERACTIF =
    "a, button, input, select, textarea, label, form, " +
    "[contenteditable], [data-no-row-nav]";

  function hrefDepuisCible(cible) {
    if (!cible || typeof cible.closest !== "function") return null;
    // Clic sur un élément interactif → comportement natif, pas de navigation.
    if (cible.closest(SELECTEUR_INTERACTIF)) return null;
    var ligne = cible.closest("tr[data-row-href]");
    if (!ligne) return null;
    return ligne.getAttribute("data-row-href") || null;
  }

  function selectionEnCours() {
    var sel = window.getSelection && window.getSelection();
    return !!(sel && String(sel).length > 0);
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0) return;
    if (selectionEnCours()) return;
    var href = hrefDepuisCible(e.target);
    if (!href) return;
    // Ctrl/Cmd/Maj → nouvel onglet, comme sur un lien classique.
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
      window.open(href, "_blank");
    } else {
      window.location.assign(href);
    }
  });

  // Clic milieu → nouvel onglet (parité avec un vrai lien).
  document.addEventListener("auxclick", function (e) {
    if (e.button !== 1) return;
    var href = hrefDepuisCible(e.target);
    if (!href) return;
    e.preventDefault();
    window.open(href, "_blank");
  });
})();
