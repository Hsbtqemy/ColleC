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
    // Fermeture : toujours câblée (lecture seule ou non — l'utilisateur
    // doit pouvoir refermer la modale qu'il a ouverte).
    modale.querySelector("[data-modal-overlay]")?.addEventListener(
      "click", fermerModale
    );
    modale.querySelectorAll("[data-fermer-modale]").forEach((b) =>
      b.addEventListener("click", fermerModale)
    );

    // En mode lecture seule (V0.9.1 T1 Phase C polish) : skip Sortable
    // ET les listeners click sur -/+. Le bouton « Appliquer » est masqué
    // côté template — sans cette protection, l'utilisateur pourrait
    // réordonner / ajouter / retirer des colonnes visuellement sans
    // pouvoir sauver. UX trompeuse, fermée ici.
    if (modale.dataset.lectureSeule === "1") return;

    instancier(modale);

    const listeActive = modale.querySelector("[data-cols-active]");
    const listeDediees = modale.querySelector("[data-cols-available]");
    const listeMetas = modale.querySelector("[data-cols-meta]");

    function actualiserCompteur() {
      const cnt = modale.querySelector("[data-cnt-actives]");
      if (cnt) cnt.textContent = String(listeActive.querySelectorAll("[data-col]").length);
    }

    // Helpers DOM safe : evitent l'injection XSS via template literal
    // dans innerHTML. Les labels des colonnes metadonnees viennent des
    // cles d'Item.metadonnees (import tableur, free text), donc peuvent
    // contenir n'importe quel caractere HTML — un nom de colonne
    // « <img src=x onerror=alert(1)> » declencherait une XSS au clic
    // sur Retirer/Ajouter si on interpole via innerHTML.
    function spanTexte(texte, style, className) {
      const s = document.createElement("span");
      if (style) s.style.cssText = style;
      if (className) s.className = className;
      s.textContent = texte;
      return s;
    }
    function svgRaw(svgHtml) {
      // SVG statique (constant code, jamais user data) : on peut utiliser
      // un container avec innerHTML sans risque.
      const span = document.createElement("span");
      span.innerHTML = svgHtml;
      return span;
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
      // Construction via DOM safe (textContent, pas innerHTML avec
      // template literal — sinon XSS via colLabel).
      dispo.appendChild(spanTexte("", "width:14px;height:14px;border-radius:3px;border:1px solid rgba(0,0,0,0.16);", "inline-block bg-white"));
      dispo.appendChild(spanTexte(li.dataset.colLabel, "font-size:13px;color:#6b7280;"));
      if (cat === "metadonnee") {
        dispo.appendChild(spanTexte("métadonnée", "font-size:11px;color:#9ca3af;margin-left:auto;"));
      }
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

      // Input hidden : `value` set via property (DOM API), evite l'injection
      // dans value="..." si key contient `"`.
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "colonnes";
      hidden.value = key;
      active.appendChild(hidden);

      // Handle drag (SVG statique).
      const handle = document.createElement("span");
      handle.className = "cursor-grab opacity-60 hover:opacity-100";
      handle.dataset.handle = "";
      handle.setAttribute("aria-label", "Réordonner");
      handle.appendChild(svgRaw(
        '<svg width="10" height="14" viewBox="0 0 10 14" aria-hidden="true">' +
        '<circle cx="2.5" cy="2"  r="1" fill="#9ca3af"/><circle cx="7.5" cy="2"  r="1" fill="#9ca3af"/>' +
        '<circle cx="2.5" cy="7"  r="1" fill="#9ca3af"/><circle cx="7.5" cy="7"  r="1" fill="#9ca3af"/>' +
        '<circle cx="2.5" cy="12" r="1" fill="#9ca3af"/><circle cx="7.5" cy="12" r="1" fill="#9ca3af"/>' +
        '</svg>'
      ).firstChild);
      active.appendChild(handle);

      // Coche bleue (SVG statique).
      const coche = document.createElement("span");
      coche.className = "inline-flex items-center justify-center";
      coche.style.cssText = "width:14px;height:14px;border-radius:3px;background:#378ADD;";
      coche.appendChild(svgRaw(
        '<svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">' +
        '<path d="M1.5 4.5 L3.5 6.5 L7.5 2" fill="none" stroke="white" ' +
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
        '</svg>'
      ).firstChild);
      active.appendChild(coche);

      // Label : textContent (pas innerHTML — sinon XSS via label).
      active.appendChild(spanTexte(label, "font-size:13px;color:#1f1f1f;", "flex-1"));

      if (cat === "metadonnee") {
        active.appendChild(spanTexte("métadonnée", "font-size:11px;color:#9ca3af;"));
      }
      if (!obligatoire) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.dataset.retirer = "";
        btn.setAttribute("aria-label", "Retirer");
        btn.className = "opacity-40 hover:opacity-100 hover:text-gray-800";
        btn.style.cssText = "font-size:14px;line-height:1;color:#9ca3af;padding:0 4px;";
        btn.textContent = "−";
        active.appendChild(btn);
      }

      listeActive.appendChild(active);
      li.remove();
      actualiserCompteur();
    }
    listeDediees.addEventListener("click", gestionnaireAjout);
    listeMetas.addEventListener("click", gestionnaireAjout);
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
