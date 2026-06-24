// Bouton « copier dans le presse-papier » générique.
//
// Délégué sur `document` → survit aux swaps / lazy-loads HTMX (la citation
// Nakala arrive en partial). Inerte tant qu'aucun `[data-copier]` n'existe.
//
// Usage : <button data-copier="#selecteur" data-label-ok="Copié ✓">Copier</button>
// Copie le TEXTE visible (`innerText`) de l'élément ciblé — donc sans les
// balises de mise en forme (ex. <i> du titre dans la citation).
(function () {
  "use strict";

  function retourLabel(btn, ancien) {
    return function () {
      btn.textContent = ancien;
    };
  }

  function confirmer(btn) {
    var ancien = btn.textContent;
    btn.textContent = btn.getAttribute("data-label-ok") || "Copié";
    window.setTimeout(retourLabel(btn, ancien), 1500);
  }

  function copierFallback(texte, onOk) {
    try {
      var ta = document.createElement("textarea");
      ta.value = texte;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      onOk();
    } catch (err) {
      /* presse-papier indisponible : on ne casse rien */
    }
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-copier]");
    if (!btn) return;
    var cible = document.querySelector(btn.getAttribute("data-copier"));
    if (!cible) return;
    var texte = (cible.innerText || cible.textContent || "").trim();
    if (!texte) return;
    var onOk = function () {
      confirmer(btn);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texte).then(onOk, function () {
        copierFallback(texte, onOk);
      });
    } else {
      copierFallback(texte, onOk);
    }
  });
})();
