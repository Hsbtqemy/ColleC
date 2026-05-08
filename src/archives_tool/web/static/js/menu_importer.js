// Toggle minimal du menu déroulant Importer.
// Click sur le bouton ouvre/ferme ; click ailleurs ou Escape ferme.

(function () {
  const conteneur = document.querySelector("[data-menu-importer]");
  if (!conteneur) return;

  const toggle = conteneur.querySelector("[data-menu-toggle]");
  const panel = conteneur.querySelector("[data-menu-panel]");
  if (!toggle || !panel) return;

  function ouvrir() {
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
  }
  function fermer() {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  toggle.addEventListener("click", function (e) {
    e.stopPropagation();
    if (panel.hidden) ouvrir();
    else fermer();
  });

  document.addEventListener("click", function (e) {
    if (!conteneur.contains(e.target)) fermer();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) fermer();
  });
})();
