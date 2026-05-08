// Câblage du panneau de colonnes (modale latérale droite).
//
// Chargé sur les pages collection ; observe l'arrivée du panneau
// dans le DOM (HTMX append `beforeend` sur body), instancie Sortable
// sur la liste active, écoute les retraits (−) et ajouts (clic sur
// dispo). Ferme la modale sur Escape, clic sur l'overlay, ou
// événement HX-Trigger `panneau-colonnes-ferme` émis par le serveur
// après sauvegarde réussie.

(function () {
  function fermerModale() {
    document.querySelectorAll("[data-modal-colonnes]").forEach((m) => m.remove());
  }

  function instancier(modale) {
    const liste = modale.querySelector("[data-cols-active]");
    if (!liste || typeof Sortable === "undefined") return;
    Sortable.create(liste, {
      handle: "[data-handle]",
      animation: 150,
      ghostClass: "bg-blue-50/50",
    });
  }

  function deplacer(li, vers) {
    vers.appendChild(li);
  }

  function gerePanneau(modale) {
    instancier(modale);

    const listeActive = modale.querySelector("[data-cols-active]");
    const listeDediees = modale.querySelector("[data-cols-available]");
    const listeMetas = modale.querySelector("[data-cols-meta]");

    function actualiserCompteur() {
      const cnt = modale.querySelector("[data-cnt-actives]");
      if (cnt) cnt.textContent = String(listeActive.querySelectorAll("[data-col]").length);
    }

    // Retirer une colonne active : la déplacer vers la liste
    // disponibles correspondante (selon catégorie).
    listeActive.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-retirer]");
      if (!btn) return;
      const li = btn.closest("[data-col]");
      const cat = li.dataset.colCategorie;
      const cible = cat === "metadonnee" ? listeMetas : listeDediees;
      // Reconstruit une ligne dispo (sans handle, sans hidden, etc.)
      const dispo = document.createElement("li");
      dispo.className = "flex items-center gap-3 hover:bg-gray-50 cursor-pointer";
      dispo.style.cssText = "padding:5px 18px 5px 36px;";
      dispo.dataset.col = "";
      dispo.dataset.colKey = li.dataset.colKey;
      dispo.dataset.colCategorie = cat;
      dispo.dataset.colLabel = li.dataset.colLabel;
      dispo.dataset.ajouter = "";
      dispo.innerHTML = `
        <span class="inline-block bg-white" style="width:14px;height:14px;border-radius:3px;border:1px solid rgba(0,0,0,0.16);"></span>
        <span style="font-size:13px;color:#6b7280;">${li.dataset.colLabel}</span>
        ${cat === "metadonnee" ? '<span style="font-size:11px;color:#9ca3af;margin-left:auto;">métadonnée</span>' : ''}
      `;
      cible.appendChild(dispo);
      li.remove();
      actualiserCompteur();
    });

    // Ajouter une colonne disponible : la déplacer dans la liste
    // active (en fin), avec un input hidden + handle.
    function gestionnaireAjout(e) {
      const li = e.target.closest("[data-ajouter]");
      if (!li) return;
      const key = li.dataset.colKey;
      const label = li.dataset.colLabel;
      const cat = li.dataset.colCategorie;
      const obligatoire = li.dataset.colObligatoire === "1";
      const active = document.createElement("li");
      active.className = "flex items-center gap-3 hover:bg-gray-50";
      active.style.cssText = "padding:6px 18px;";
      active.dataset.col = "";
      active.dataset.colKey = key;
      active.dataset.colCategorie = cat;
      active.dataset.colLabel = label;
      active.innerHTML = `
        <input type="hidden" name="colonnes" value="${key}">
        <span class="cursor-grab opacity-60 hover:opacity-100" data-handle aria-label="Réordonner">
          <svg width="10" height="14" viewBox="0 0 10 14" aria-hidden="true">
            <circle cx="2.5" cy="2"  r="1" fill="#9ca3af"/><circle cx="7.5" cy="2"  r="1" fill="#9ca3af"/>
            <circle cx="2.5" cy="7"  r="1" fill="#9ca3af"/><circle cx="7.5" cy="7"  r="1" fill="#9ca3af"/>
            <circle cx="2.5" cy="12" r="1" fill="#9ca3af"/><circle cx="7.5" cy="12" r="1" fill="#9ca3af"/>
          </svg>
        </span>
        <span class="inline-flex items-center justify-center"
              style="width:14px;height:14px;border-radius:3px;background:#378ADD;">
          <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
            <path d="M1.5 4.5 L3.5 6.5 L7.5 2" fill="none" stroke="white"
                  stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <span class="flex-1" style="font-size:13px;color:#1f1f1f;">${label}</span>
        ${cat === "metadonnee" ? '<span style="font-size:11px;color:#9ca3af;">métadonnée</span>' : ''}
        ${!obligatoire ? '<button type="button" data-retirer aria-label="Retirer" class="opacity-40 hover:opacity-100 hover:text-gray-800" style="font-size:14px;line-height:1;color:#9ca3af;padding:0 4px;">−</button>' : ''}
      `;
      listeActive.appendChild(active);
      li.remove();
      actualiserCompteur();
    }
    listeDediees.addEventListener("click", gestionnaireAjout);
    listeMetas.addEventListener("click", gestionnaireAjout);

    // Fermeture : overlay, Annuler, Escape.
    modale.querySelector("[data-modal-overlay]")?.addEventListener("click", fermerModale);
    modale.querySelectorAll("[data-fermer-modale]").forEach((b) =>
      b.addEventListener("click", fermerModale)
    );
  }

  // Écoute les ajouts au body : à chaque réception de la modale, la
  // brancher.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target === document.body) {
      const m = document.querySelector("[data-modal-colonnes]");
      if (m && !m.dataset.cable) {
        m.dataset.cable = "1";
        gerePanneau(m);
      }
    }
  });

  // Fermeture clavier (Escape).
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.querySelector("[data-modal-colonnes]")) {
      fermerModale();
    }
  });

  // Le serveur émet HX-Trigger après save réussi.
  document.body.addEventListener("panneau-colonnes-ferme", fermerModale);
})();
