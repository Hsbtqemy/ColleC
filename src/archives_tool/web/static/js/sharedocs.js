// ShareDocs : confort de sélection et de ciblage (Chantier 1, polish UX).
//
// (A) Case maître « Tout sélectionner » → coche / décoche tous les fichiers
//     du dossier courant, et reflète l'état (coché / indéterminé / vide).
// (B/C) Les cibles fonds / item sont des <select>. La sentinelle
//     "__nouveau__" révèle la zone de création associée (cote + titre).
//
// Délégation d'événements sur `document` : le <select> des items est
// rechargé par HTMX au changement de fonds, donc on ne peut pas lier les
// écouteurs une fois pour toutes. Inerte (no-op) hors de la page ShareDocs.
(function () {
  "use strict";

  var SENTINELLE = "__nouveau__";

  function casesFichiers() {
    return Array.prototype.slice.call(
      document.querySelectorAll('input[type="checkbox"][name="fichiers"]')
    );
  }

  // (A) Reflète l'état de la case maître d'après les cases individuelles.
  function syncMaitre() {
    var maitre = document.querySelector("[data-sd-tout]");
    if (!maitre) return;
    var cases = casesFichiers();
    if (cases.length === 0) {
      maitre.checked = false;
      maitre.indeterminate = false;
      return;
    }
    var coches = cases.filter(function (c) {
      return c.checked;
    }).length;
    maitre.checked = coches === cases.length;
    maitre.indeterminate = coches > 0 && coches < cases.length;
  }

  // (C) Affiche / masque la zone de création liée à un <select> de cible.
  // Les champs cachés sont `disabled` pour ne pas être soumis (le serveur
  // n'utilise alors que la valeur sélectionnée), et `required` seulement
  // quand ils sont visibles.
  function syncCreation(select) {
    var cle = select.getAttribute("data-sd-cible");
    var zone = document.querySelector('[data-sd-nouveau="' + cle + '"]');
    if (!zone) return;
    var actif = select.value === SENTINELLE;
    zone.hidden = !actif;
    Array.prototype.forEach.call(zone.querySelectorAll("input"), function (inp) {
      inp.disabled = !actif;
      if (inp.hasAttribute("data-sd-requis")) inp.required = actif;
    });
  }

  function initialiser() {
    syncMaitre();
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-sd-cible]"),
      syncCreation
    );
  }

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.matches) return;
    if (t.matches("[data-sd-tout]")) {
      var coche = t.checked;
      casesFichiers().forEach(function (c) {
        c.checked = coche;
      });
      return;
    }
    if (t.matches('input[name="fichiers"]')) {
      syncMaitre();
      return;
    }
    if (t.matches("[data-sd-cible]")) {
      syncCreation(t);
    }
  });

  document.addEventListener("DOMContentLoaded", initialiser);
  // Le <select> des items est remplacé par HTMX au changement de fonds :
  // re-synchroniser après chaque swap pour rebrancher l'état de création.
  document.addEventListener("htmx:afterSwap", initialiser);
})();
