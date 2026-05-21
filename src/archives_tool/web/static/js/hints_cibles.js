// Met à jour le hint d'aide sous chaque sélecteur de cible de mapping
// quand l'utilisateur change la sélection. Le hint initial (server-
// side via `hints_cibles.get(cible, '')`) reste si la sélection
// initiale n'est pas changée.
//
// Source des hints : <script id="hints-cibles-data" type="application/json">
// injecté par le template (dict cible → description courte).

(function () {
  const dataNode = document.getElementById("hints-cibles-data");
  if (!dataNode) return;
  let hints;
  try {
    hints = JSON.parse(dataNode.textContent);
  } catch {
    return;
  }

  function appliquer(select) {
    const ligne = select.closest("[data-cible-ligne]");
    if (!ligne) return;
    const p = ligne.querySelector("[data-cible-hint]");
    if (!p) return;
    p.textContent = hints[select.value] || "";
  }

  document.querySelectorAll('select[data-cible-select]').forEach((s) => {
    s.addEventListener("change", () => appliquer(s));
  });
})();
