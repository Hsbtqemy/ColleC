// Utilitaire de focus-trap réutilisable pour les modales / drawers.
//
// Une overlay accessible doit : (1) déplacer le focus dedans à
// l'ouverture, (2) empêcher Tab/Shift+Tab d'en sortir tant qu'elle est
// ouverte, (3) restaurer le focus sur l'élément déclencheur à la
// fermeture. Ce module fournit ces trois comportements via une seule
// fonction `activer(conteneur)` qui renvoie une fonction de libération.
//
// Chargé globalement dans base.html (avant les consommateurs, qui sont
// chargés par les pages via le block scripts). Inerte tant que personne
// ne l'appelle — il n'expose qu'un objet sur `window`.
//
// Consommateurs : panneau_colonnes.js (modale colonnes),
// panneau_filtres.js (drawer de filtres).

(function () {
  // Éléments naturellement focusables et non masqués / désactivés.
  const SELECTEUR =
    'a[href], button:not([disabled]), input:not([disabled]), ' +
    'select:not([disabled]), textarea:not([disabled]), ' +
    '[tabindex]:not([tabindex="-1"])';

  function focusables(conteneur) {
    return Array.prototype.filter.call(
      conteneur.querySelectorAll(SELECTEUR),
      // offsetParent === null => élément masqué (display:none ou parent
      // inerte). On garde l'actif courant au cas où il serait en cours
      // de transition.
      (el) => el.offsetParent !== null || el === document.activeElement
    );
  }

  // Active le piège sur `conteneur`. Renvoie `liberer()` (idempotente).
  function activer(conteneur) {
    if (!conteneur) return function () {};
    const precedent =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    function onKeydown(e) {
      if (e.key !== "Tab") return;
      const f = focusables(conteneur);
      if (f.length === 0) {
        // Rien de focusable : on garde le focus sur le conteneur.
        e.preventDefault();
        return;
      }
      const premier = f[0];
      const dernier = f[f.length - 1];
      const actif = document.activeElement;
      if (e.shiftKey && (actif === premier || !conteneur.contains(actif))) {
        e.preventDefault();
        dernier.focus();
      } else if (!e.shiftKey && actif === dernier) {
        e.preventDefault();
        premier.focus();
      }
    }

    conteneur.addEventListener("keydown", onKeydown);

    // Focus initial : 1er élément focusable, sinon le conteneur lui-même
    // (nécessite tabindex="-1" sur le conteneur pour être focusable).
    const initiaux = focusables(conteneur);
    if (initiaux.length > 0) {
      initiaux[0].focus();
    } else if (typeof conteneur.focus === "function") {
      conteneur.focus();
    }

    let libere = false;
    return function liberer() {
      if (libere) return;
      libere = true;
      conteneur.removeEventListener("keydown", onKeydown);
      if (precedent && typeof precedent.focus === "function") {
        precedent.focus();
      }
    };
  }

  window.ColleCFocusTrap = { activer };
})();
