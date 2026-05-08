// Toggle minimal du drawer panneau-filtres.
// Le drawer est rendu en HTML statique (data-ouvert="false" par défaut) ;
// les boutons [data-action="filter"] (dans tableau_items.html) et
// les boutons de fermeture togglent l'attribut.
//
// Submit du form se fait par le bouton « Appliquer » (form GET natif),
// pas via ce script.

(function () {
  const drawer = document.getElementById("panneau-filtres");
  if (!drawer) return;

  function ouvrir() { drawer.dataset.ouvert = "true"; }
  function fermer() { drawer.dataset.ouvert = "false"; }

  // Boutons « Filtrer » (déjà dans tableau_items / partial fichiers).
  document.querySelectorAll('[data-action="filter"]').forEach((btn) => {
    btn.addEventListener("click", ouvrir);
  });

  // Boutons internes au drawer (×, Annuler).
  drawer.querySelectorAll("[data-panneau-filtres-fermer]").forEach((btn) => {
    btn.addEventListener("click", fermer);
  });

  // Fermeture par Escape.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.dataset.ouvert === "true") fermer();
  });
})();
