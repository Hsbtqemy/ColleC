// recherche_globale.js — raccourci clavier `/` ou `Cmd+K` pour
// focus la barre de recherche du header (Lot C V0.9.x).
//
// Skip si focus déjà dans input/textarea/contenteditable — on ne
// veut pas voler le `/` que l'utilisateur tape dans un champ.

(function () {
  function focusEstDansChampTexte() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if (el.isContentEditable) return true;
    return false;
  }

  document.addEventListener("keydown", function (e) {
    // `/` (slash) ou Cmd+K / Ctrl+K → focus barre recherche
    var estSlash = e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey;
    var estCmdK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
    if (!estSlash && !estCmdK) return;
    // Skip si focus dans un champ texte (sauf si Cmd+K — celui-ci
    // force le focus même depuis un champ, c'est sa convention).
    if (estSlash && focusEstDansChampTexte()) return;
    var input = document.getElementById("recherche-globale-input");
    if (input) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
})();
