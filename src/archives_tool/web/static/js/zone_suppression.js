// Activation conditionnelle des formulaires de suppression d'entité
// (fonds / collection libre / item). Le bouton submit reste désactivé
// tant que l'input `confirmer` ne contient pas exactement la cote
// attendue, indiquée par `data-cote-confirmer` sur le <form>.
//
// Défense en surface : le serveur revérifie côté route et renvoie 400
// si confirmer != cote. Le rôle de ce script est purement UX —
// transformer le 400 JSON brut en un bouton qui ne s'allume qu'au
// bon moment, pour les utilisateurs qui auraient fait un typo.
//
// Inerte (no-op) si aucun formulaire avec `data-cote-confirmer` n'est
// présent dans la page.

(function () {
  function brancher(form) {
    var attendue = form.dataset.coteConfirmer;
    if (!attendue) return;
    var input = form.querySelector('input[name="confirmer"]');
    var bouton = form.querySelector('button[type="submit"]');
    if (!input || !bouton) return;

    function rafraichir() {
      var match = input.value === attendue;
      bouton.disabled = !match;
      bouton.style.opacity = match ? "1" : "0.5";
      bouton.style.cursor = match ? "pointer" : "not-allowed";
    }
    input.addEventListener("input", rafraichir);
    rafraichir();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-cote-confirmer]").forEach(brancher);
  });
})();
