// Raccourcis clavier sur la page de résultats /recherche.
//
// Actions :
//   ←   page précédente (clic sur le lien "Page précédente")
//   →   page suivante  (clic sur le lien "Page suivante")
//   Esc défocus de la barre de recherche (sans clear, pour ne pas perdre la query)
//
// Skip si le focus est dans un input / textarea / select / contenteditable —
// l'utilisateur peut continuer à taper dans la barre, dans q2 ou un champ
// année sans subir une navigation parasite.
//
// La page entière étant un reload classique (pas de HTMX swap), on se
// contente d'un .click() sur les <a> de pagination — le browser fait le
// reste. Les boutons disabled sont des <span> sans href, donc le click()
// est no-op naturellement.

(function () {
  function focusEstDansSaisie() {
    const a = document.activeElement;
    if (!a) return false;
    const tag = a.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (a.isContentEditable) return true;
    return false;
  }

  function cliquerLienPagination(ariaLabel) {
    // Les liens de pagination du template recherche.html portent
    // aria-label="Page précédente" / "Page suivante" sur le <a> actif.
    // Le <span> aria-hidden des positions extrêmes (page 1 ou dernière)
    // n'a pas d'aria-label, donc on ne l'attrape pas.
    const lien = document.querySelector(`a[aria-label="${ariaLabel}"]`);
    if (lien) {
      lien.click();
      return true;
    }
    return false;
  }

  function init() {
    // N'active les raccourcis que sur la page /recherche (pas sur les
    // autres pages où ← / → peuvent avoir d'autres sémantiques — ex.
    // navigation page liseuse).
    if (window.location.pathname !== "/recherche") return;

    document.addEventListener("keydown", function (event) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (focusEstDansSaisie()) {
        // Dans un input : seul Esc fait sens (défocus). Pas de ← / → pour
        // ne pas casser le déplacement du curseur dans le champ.
        if (event.key === "Escape") {
          event.preventDefault();
          document.activeElement.blur();
        }
        return;
      }
      if (event.key === "ArrowLeft") {
        if (cliquerLienPagination("Page précédente")) event.preventDefault();
      } else if (event.key === "ArrowRight") {
        if (cliquerLienPagination("Page suivante")) event.preventDefault();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
