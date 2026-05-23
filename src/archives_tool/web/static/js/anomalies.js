// Anomalies de mapping (V0.9.2-import #4) — actions client-side
// « Corriger » / « Garder ». Pas de POST intermédiaire : on modifie
// directement le select de la colonne concernée, et l'utilisateur
// soumet le form complet quand il est prêt.
//
// T4 (passe « trous documentés ») : « Garder le choix actuel »
// persiste maintenant dans localStorage, scopé par session d'import,
// pour qu'un retour sur l'étape ne ré-affiche pas les avertissements
// déjà acceptés. La clé combine (colonne, classif) — si la classif
// change après modification du tableur, l'avertissement réapparaît
// naturellement.

(function () {
  function trouverSelect(colonne) {
    // CSS.escape pour gérer les noms de colonnes avec caractères
    // spéciaux (apostrophes, quotes, URLs Dublin Core, ...).
    return document.querySelector(
      `select[data-cible-select][data-colonne="${CSS.escape(colonne)}"]`,
    );
  }

  function blocAnomalies() {
    return document.querySelector("[data-anomalies]");
  }

  function sessionId() {
    const bloc = blocAnomalies();
    return bloc ? bloc.dataset.sessionId : null;
  }

  function cleStorage(sid) {
    return `colleC-import-${sid}-anomalies-acceptees`;
  }

  function lireAcceptees(sid) {
    try {
      return JSON.parse(localStorage.getItem(cleStorage(sid))) || [];
    } catch (e) {
      return [];
    }
  }

  function ajouterAcceptee(sid, colonne, classif) {
    if (!sid) return;
    const liste = lireAcceptees(sid);
    if (
      liste.some((a) => a.colonne === colonne && a.classif === classif)
    ) {
      return;
    }
    liste.push({ colonne, classif });
    try {
      localStorage.setItem(cleStorage(sid), JSON.stringify(liste));
    } catch (e) {
      // localStorage indisponible (mode privé, quota plein) : fallback
      // silencieux, l'anomalie réapparaîtra au prochain rendu — pas
      // bloquant fonctionnellement.
    }
  }

  function masquerSiVide() {
    const ul = document.querySelector("[data-anomalies-list]");
    if (!ul) return;
    if (ul.children.length === 0) {
      const bloc = ul.closest("[data-anomalies]");
      if (bloc) bloc.style.display = "none";
    }
  }

  function filtrerAuChargement() {
    const bloc = blocAnomalies();
    if (!bloc) return;
    const sid = bloc.dataset.sessionId;
    if (!sid) return;
    const acceptees = lireAcceptees(sid);
    if (acceptees.length === 0) return;
    const lis = bloc.querySelectorAll("[data-anomalie]");
    for (const li of lis) {
      const colonne = li.dataset.colonne;
      const classif = li.dataset.classif || "";
      if (
        acceptees.some(
          (a) => a.colonne === colonne && a.classif === classif,
        )
      ) {
        li.remove();
      }
    }
    masquerSiVide();
  }

  document.addEventListener("click", (e) => {
    const corriger = e.target.closest("[data-action-corriger]");
    const garder = e.target.closest("[data-action-garder]");
    if (!corriger && !garder) return;
    e.preventDefault();

    const li = (corriger || garder).closest("[data-anomalie]");
    if (corriger) {
      const colonne = corriger.dataset.colonne;
      const cibleSuggeree = corriger.dataset.cibleSuggeree;
      const select = trouverSelect(colonne);
      if (select) {
        select.value = cibleSuggeree;
        // Déclenche `change` pour que hints_cibles.js réactualise le hint.
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    if (garder && li) {
      // Persiste le choix « Garder » pour ne pas re-suggérer cette
      // anomalie au prochain rendu de l'étape mapping (T4).
      ajouterAcceptee(
        sessionId(),
        li.dataset.colonne,
        li.dataset.classif || "",
      );
    }
    if (li) li.remove();
    masquerSiVide();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", filtrerAuChargement);
  } else {
    filtrerAuChargement();
  }
})();
