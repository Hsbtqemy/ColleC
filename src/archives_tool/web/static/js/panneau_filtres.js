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

  // Delegation sur document plutot qu'attache par-bouton : HTMX
  // remplace `#tableau-items` apres un tri/pagination, ce qui efface
  // l'ancien bouton « Filtrer ». Une delegation au document survit
  // a tous les swaps sans re-cablage.
  document.addEventListener("click", (e) => {
    if (e.target.closest('[data-action="filter"]')) {
      ouvrir();
    } else if (e.target.closest("[data-panneau-filtres-fermer]")) {
      fermer();
    }
  });

  // Fermeture par Escape.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.dataset.ouvert === "true") fermer();
  });
})();
