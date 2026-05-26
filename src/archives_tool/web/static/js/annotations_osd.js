// Plugin Annotorious sur l'instance OpenSeadragon de la visionneuse.
// V0.9.7 beta — intègre l'édition d'annotations W3C / IIIF dans la
// page item.
//
// Couplage avec visionneuse_osd.js via l'événement `visionneuse:pret`
// qui porte `{osd, fichier_id}`. On démarre toujours en mode lecture
// (readOnly=true) ; un bouton externe (data-annoter-toggle) bascule.
//
// Routes REST utilisées :
//   GET    /api/fichiers/{id}/annotations  → AnnotationPage W3C
//   POST   /api/fichiers/{id}/annotations  → création (201 + W3C)
//   PUT    /api/annotations/{id}           → modification
//   DELETE /api/annotations/{id}           → suppression
//
// L'API serveur accepte la forme W3C native (target/body) qu'envoie
// directement Annotorious, donc pas de conversion à faire au client.

(function () {
  if (typeof OpenSeadragon === "undefined") return;
  if (typeof OpenSeadragon.Annotorious !== "function") {
    // Annotorious pas encore chargé ou bundle absent — on ne casse
    // pas la visionneuse, on ne fait juste pas les annotations.
    console.warn(
      "[annotations] OpenSeadragon.Annotorious manquant. Vendor non installé ?",
    );
    return;
  }

  /** Récupère l'ID local d'une annotation depuis son URI W3C. */
  function extraireIdAnnotation(annotation) {
    // L'API serveur émet `id: "<base_url>/api/annotations/<id>"`.
    // Annotorious préserve cet `id` lors des updates/deletes.
    const uri = annotation.id || "";
    const m = uri.match(/\/api\/annotations\/(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  }

  /** Charge les annotations existantes du fichier dans Annotorious. */
  async function chargerAnnotations(anno, fichierId) {
    try {
      const r = await fetch(`/api/fichiers/${fichierId}/annotations`);
      if (!r.ok) {
        console.warn("[annotations] GET échoué :", r.status);
        return;
      }
      const page = await r.json();
      const items = page.items || [];
      // setAnnotations remplace toutes les annotations actuelles
      // (vide ici à l'init) par celles fournies. Format W3C natif.
      anno.setAnnotations(items);
    } catch (e) {
      console.warn("[annotations] GET erreur réseau :", e);
    }
  }

  /** POST une annotation nouvelle et reçoit l'`id` neuf en retour. */
  async function creerAnnotation(annotation, fichierId) {
    const r = await fetch(`/api/fichiers/${fichierId}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
    });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`POST échec ${r.status} : ${body}`);
    }
    return await r.json();
  }

  /** PUT une annotation modifiée. */
  async function modifierAnnotation(annotation) {
    const id = extraireIdAnnotation(annotation);
    if (id == null) {
      throw new Error("Annotation sans ID local — création requise.");
    }
    const r = await fetch(`/api/annotations/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
    });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`PUT échec ${r.status} : ${body}`);
    }
    return await r.json();
  }

  /** DELETE une annotation. Idempotent côté serveur. */
  async function supprimerAnnotation(annotation) {
    const id = extraireIdAnnotation(annotation);
    if (id == null) return;
    await fetch(`/api/annotations/${id}`, { method: "DELETE" });
  }

  /** Initialise Annotorious sur une instance OSD. */
  function initialiserAnnotorious(osd, fichierId) {
    if (fichierId == null) {
      console.warn(
        "[annotations] fichier_id absent — annotations désactivées.",
      );
      return;
    }
    const anno = OpenSeadragon.Annotorious(osd, {
      // Démarre en lecture seule : pas de drag pour dessiner par
      // défaut. Le bouton « Annoter » bascule via setDrawingEnabled
      // et readOnly.
      readOnly: true,
      // Largeur min de la zone dessinée — évite les clics
      // accidentels qui créent des annotations 1x1 pixel.
      drawOnSingleClick: false,
    });

    chargerAnnotations(anno, fichierId);

    // Création : Annotorious appelle createAnnotation après le save
    // de la popup. La réponse serveur contient l'`id` neuf qu'on
    // injecte dans l'annotation pour que les updates ultérieurs
    // pointent au bon endroit.
    anno.on("createAnnotation", async function (annotation) {
      try {
        const sauvee = await creerAnnotation(annotation, fichierId);
        // Remplace l'annotation client (id temporaire) par celle du
        // serveur (id officiel).
        anno.removeAnnotation(annotation);
        anno.addAnnotation(sauvee);
      } catch (e) {
        console.error("[annotations] Création échouée :", e);
        anno.removeAnnotation(annotation);
        alert("Création d'annotation échouée. Voir console.");
      }
    });

    // Modification : géométrie ou body modifiés via le popup.
    anno.on("updateAnnotation", async function (annotation) {
      try {
        await modifierAnnotation(annotation);
      } catch (e) {
        console.error("[annotations] Modification échouée :", e);
        alert("Modification d'annotation échouée. Voir console.");
      }
    });

    // Suppression : poubelle dans le popup.
    anno.on("deleteAnnotation", async function (annotation) {
      try {
        await supprimerAnnotation(annotation);
      } catch (e) {
        console.error("[annotations] Suppression échouée :", e);
      }
    });

    return anno;
  }

  /** Stockage global pour exposer les instances Annotorious aux
   *  boutons de bascule (`data-annoter-toggle`). */
  const _annosParViseur = new WeakMap();

  // Écoute l'événement émis par `visionneuse_osd.js` quand OSD est
  // prêt. On greffe Annotorious dessus une fois par viewer.
  document.addEventListener("visionneuse:pret", function (e) {
    const viz = e.target;
    if (_annosParViseur.has(viz)) return; // déjà greffé (re-open)
    const { osd, fichier_id } = e.detail || {};
    if (!osd) return;
    const anno = initialiserAnnotorious(osd, fichier_id);
    if (anno) {
      _annosParViseur.set(viz, anno);
    }
  });

  // Bouton externe « Annoter » → bascule readOnly + setDrawingTool
  // sur le viewer cible. Le bouton porte `data-annoter-toggle` avec
  // la valeur = id du viewer (`visionneuse-<fichier_id>`).
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-annoter-toggle]");
    if (!btn) return;
    e.preventDefault();
    const cibleId = btn.dataset.annoterToggle;
    const viz = document.getElementById(cibleId);
    if (!viz) return;
    const anno = _annosParViseur.get(viz);
    if (!anno) {
      console.warn("[annotations] Pas d'instance Annotorious sur", cibleId);
      return;
    }
    // Toggle readOnly. Annotorious 2.x : `setDrawingEnabled` est
    // contrôlé indirectement par readOnly + setDrawingTool.
    const enLecture = anno.readOnly;
    anno.readOnly = !enLecture;
    btn.dataset.annoterActif = enLecture ? "1" : "0";
    btn.textContent = enLecture ? "Annoter (actif)" : "Annoter";
    if (!enLecture) {
      // On bascule en lecture : neutraliser tout dessin en cours.
      try { anno.cancelSelected(); } catch (_) {}
    } else {
      // Activation : outil rectangle par défaut. Annotorious 2.x
      // accepte "rect" et "polygon".
      anno.setDrawingTool("rect");
    }
  });
})();
