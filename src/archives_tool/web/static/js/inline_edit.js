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
    // Si la zone porte un marqueur `data-edit-raw`, sa valeur est la
    // source brute (URI COAR, code ISO langue) tandis que le texte
    // visible est le libellé humain. On lit donc l'attribut, pas le
    // textContent — sinon on rempile "Texte" au lieu de l'URI.
    const span = zoneValeur.querySelector("[data-edit-raw]");
    if (span) {
      const raw = span.getAttribute("data-edit-raw");
      if (raw !== null) return raw;
      return span.textContent.trim();
    }
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
    const optionsBrutes = ligne.dataset.editOptions;

    let input;
    if (optionsBrutes) {
      // Vocabulaire contrôlé : <select> strict avec la liste fournie.
      // Le champ peut déjà contenir une valeur hors-liste (legacy ou
      // saisie ailleurs) ; on l'ajoute pour ne pas la perdre au save.
      input = document.createElement("select");
      const options = JSON.parse(optionsBrutes);
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "—";
      input.appendChild(blank);
      const presents = new Set();
      for (const [val, libelle] of options) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = libelle;
        input.appendChild(opt);
        presents.add(val);
      }
      if (valeurAvant && !presents.has(valeurAvant)) {
        const opt = document.createElement("option");
        opt.value = valeurAvant;
        opt.textContent = valeurAvant + " (hors-liste)";
        input.appendChild(opt);
      }
      input.value = valeurAvant;
      input.style.cssText =
        "width:100%;font-size:13px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;background:white;";
    } else {
      const tag = type === "multiligne" ? "textarea" : "input";
      input = document.createElement(tag);
      if (tag === "input") input.type = "text";
      input.value = valeurAvant;
      input.style.cssText =
        "width:100%;font-size:13px;padding:2px 4px;border:1px solid #d1d5db;border-radius:3px;background:white;";
      if (tag === "textarea") {
        input.rows = 3;
        input.style.cssText += "resize:vertical;line-height:1.45;";
      }
    }

    const contenuAvant = zoneValeur.innerHTML;
    zoneValeur.innerHTML = "";
    zoneValeur.appendChild(input);
    input.focus();
    if (input.select) input.select();

    let envoye = false;

    async function envoyer() {
      if (envoye) return;
      envoye = true;
      // No-op si la valeur n'a pas changé : un simple clic-out après
      // un focus passif ne doit pas bumper la version en base.
      if (input.value === valeurAvant) {
        zoneValeur.innerHTML = contenuAvant;
        ligne.dataset.editing = "0";
        return;
      }
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
      // Marquer envoye AVANT de detacher l'input : le innerHTML qui
      // suit declenche un blur synchrone sur l'input qui re-appelle
      // envoyer(). Sans ce flag, une saisie suivie d'Escape soumettait
      // quand meme la valeur tapee au lieu de l'annuler.
      envoye = true;
      zoneValeur.innerHTML = contenuAvant;
      ligne.dataset.editing = "0";
    }

    if (input.tagName === "SELECT") {
      // Pour un <select>, on ne s'appuie PAS sur blur : la popup native
      // du dropdown (Chrome / Firefox sur Windows) prend brievement le
      // focus quand on l'ouvre (Space, F4, clic), declenchant un blur
      // parasite qui fermait le select avant que l'utilisateur ait pu
      // choisir. On sauve sur change (l'utilisateur a vraiment choisi)
      // et on detecte le click outside via mousedown sur document.
      input.addEventListener("change", envoyer);
      const clickOutside = function (event) {
        if (!ligne.contains(event.target)) {
          document.removeEventListener("mousedown", clickOutside);
          annuler();
        }
      };
      document.addEventListener("mousedown", clickOutside);
    } else {
      input.addEventListener("blur", envoyer);
    }
    input.addEventListener("keydown", function (event) {
      const t = input.tagName;
      if (event.key === "Enter" && t === "INPUT") {
        event.preventDefault();
        input.blur();
      } else if (event.key === "Enter" && event.ctrlKey && t === "TEXTAREA") {
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
