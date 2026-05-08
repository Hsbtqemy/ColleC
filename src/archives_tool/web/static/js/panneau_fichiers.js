// Câblage des trois états du composant panneau_fichiers du bundle :
// - collapsed : barre verticale 32 px (état par défaut)
// - hover     : 220 px en overlay (déclenché par survol après 250 ms)
// - pinned    : 220 px qui pousse le layout (déclenché par clic sur ▸)
//
// Le markup et le CSS minimal sont déjà dans le composant ; ce fichier
// se contente de basculer `data-state` sur l'élément racine.
// La persistance serveur de l'état (collapsed | pinned) viendra V0.7
// avec les préférences utilisateur.

(function () {
  const panel = document.querySelector("[data-panneau-fichiers]");
  if (!panel) return;

  let timer;
  panel.addEventListener("mouseenter", function () {
    if (panel.dataset.state === "pinned") return;
    timer = setTimeout(function () {
      panel.dataset.state = "hover";
    }, 250);
  });
  panel.addEventListener("mouseleave", function () {
    clearTimeout(timer);
    if (panel.dataset.state === "hover") {
      panel.dataset.state = "collapsed";
    }
  });

  const expand = panel.querySelector('[data-action="expand"]');
  if (expand) {
    expand.addEventListener("click", function () {
      panel.dataset.state = "pinned";
    });
  }

  const togglePin = panel.querySelector('[data-action="toggle-pin"]');
  if (togglePin) {
    togglePin.addEventListener("click", function () {
      panel.dataset.state =
        panel.dataset.state === "pinned" ? "collapsed" : "pinned";
    });
  }
})();
