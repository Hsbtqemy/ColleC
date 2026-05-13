// Édition inline du cartouche métadonnées.
// Cible le markup `[data-edit-field][data-editable="1"]` posé par
// components/cartouche_metadonnees.html. Workflow : click → input,
// blur/Enter → POST /item/{cote}/champ/{field}, swap la réponse dans
// [data-value]. La version vit dans <meta name="item-context"> et
// est resynchronisée après chaque save via [data-edit-new-version].

(function () {
  const ligneSelector = '[data-edit-field][data-editable="1"]';

  function chercherContextItem() {
    // La page item expose cote/fonds/version via <meta name="item-context">.
    // On garde la référence au noeud DOM pour resynchroniser la version
    // après chaque save sans nouveau querySelector.
    const meta = document.querySelector('meta[name="item-context"]');
    if (!meta) return null;
    return {
      cote: meta.dataset.cote,
      fonds: meta.dataset.fonds,
      version: parseInt(meta.dataset.version, 10),
      urlTemplate: meta.dataset.editUrlTemplate,
      meta,
    };
  }

  function chercherTypeChamp(ligne) {
    return ligne.dataset.editType || "texte";
  }

  function valeurBruteCourante(zoneValeur) {
    // Texte brut, sans le markup (mono / non-renseigné).
    const span = zoneValeur.querySelector("[data-edit-raw]");
    if (span) return span.textContent.trim();
    // Fallback : textContent moins les éléments italic « non renseigné ».
    const txt = zoneValeur.textContent || "";
    const trimmed = txt.trim();
    if (trimmed === "non renseigné") return "";
    return trimmed;
  }

  function activer(ligne, ctx) {
    const zoneValeur = ligne.querySelector("[data-value]");
    if (!zoneValeur) return;
    if (ligne.dataset.editing === "1") return; // déjà en édition

    ligne.dataset.editing = "1";
    const valeurAvant = valeurBruteCourante(zoneValeur);
    const type = chercherTypeChamp(ligne);
    const field = ligne.dataset.editField;

    const tag = type === "multiligne" ? "textarea" : "input";
    const input = document.createElement(tag);
    if (tag === "input") input.type = "text";
    input.value = valeurAvant;
    input.style.cssText =
      "width:100%;font-size:13px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;background:white;";
    if (tag === "textarea") {
      input.rows = 3;
      input.style.cssText += "resize:vertical;line-height:1.45;";
    }

    const contenuAvant = zoneValeur.innerHTML;
    zoneValeur.innerHTML = "";
    zoneValeur.appendChild(input);
    input.focus();
    input.select();

    let envoye = false;

    async function envoyer() {
      if (envoye) return;
      envoye = true;
      const formData = new FormData();
      formData.append("version", String(ctx.version));
      formData.append("valeur", input.value);
      try {
        const url = ctx.urlTemplate
          .replace("{cote}", encodeURIComponent(ctx.cote))
          .replace("{field}", encodeURIComponent(field))
          .replace("{fonds}", encodeURIComponent(ctx.fonds));
        const resp = await fetch(url, { method: "POST", body: formData });
        const html = await resp.text();
        zoneValeur.innerHTML = html;
        if (resp.ok) {
          // Récupérer la nouvelle version pour les saves suivants.
          const span = zoneValeur.querySelector("[data-edit-new-version]");
          if (span) {
            const nv = parseInt(span.dataset.editNewVersion, 10);
            if (!isNaN(nv)) {
              ctx.version = nv;
              ctx.meta.dataset.version = String(nv);
            }
          }
        }
      } catch (e) {
        // Erreur réseau : on restaure la valeur d'origine, l'utilisateur
        // réessaiera. Pas de toast pour rester minimal.
        zoneValeur.innerHTML = contenuAvant;
      } finally {
        ligne.dataset.editing = "0";
      }
    }

    function annuler() {
      if (envoye) return;
      zoneValeur.innerHTML = contenuAvant;
      ligne.dataset.editing = "0";
    }

    input.addEventListener("blur", envoyer);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && tag === "input") {
        event.preventDefault();
        input.blur();
      } else if (event.key === "Enter" && event.ctrlKey && tag === "textarea") {
        event.preventDefault();
        input.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        annuler();
      }
    });
  }

  function init() {
    const ctx = chercherContextItem();
    if (!ctx) return;
    document.addEventListener("click", function (event) {
      const ligne = event.target.closest(ligneSelector);
      if (!ligne) return;
      if (event.target.closest("a, button")) return; // laisser passer les liens
      activer(ligne, ctx);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
