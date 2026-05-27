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

  /** Map `libellé normalisé` → `{libelle, uri, vocabulaire}`.
   *  Préchargée au DOMContentLoaded via GET /api/vocabulaires/autocomplete.
   *  Permet d'enrichir les bodies au save : si l'utilisateur tape un
   *  libellé qui matche une ValeurControlee avec URI, on ajoute un
   *  body `SpecificResource source=URI` à côté du TextualBody.
   *  Pivot Wikidata/VIAF pour les exports Nakala (γ pivoté vers δ). */
  const _vocabIndex = new Map();
  /** Liste plate des libellés pour alimenter le widget TAG Annotorious
   *  (qui accepte un tableau de strings). */
  const _vocabLibelles = [];

  /** Normalise un libellé pour le matching (insensible casse + accents). */
  function normaliserLibelle(s) {
    return (s || "")
      .toString()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .trim();
  }

  /** Précharge les valeurs vocabulaire pour l'autocomplete. Non-bloquant :
   *  si l'endpoint échoue, Annotorious démarre sans suggestions et
   *  l'utilisateur peut quand même taper librement. */
  async function chargerVocabulaires() {
    try {
      const r = await fetch("/api/vocabulaires/autocomplete");
      if (!r.ok) return;
      const data = await r.json();
      for (const v of data.valeurs || []) {
        // Le libellé est la clé de matching côté JS. On stocke l'URI
        // associée pour le body SpecificResource au save.
        const cle = normaliserLibelle(v.libelle);
        if (!cle) continue;
        _vocabIndex.set(cle, {
          libelle: v.libelle,
          uri: v.uri || null,
          vocabulaire: v.vocabulaire,
          vocabulaire_code: v.vocabulaire_code,
          code: v.code,
        });
        if (!_vocabLibelles.includes(v.libelle)) {
          _vocabLibelles.push(v.libelle);
        }
      }
    } catch (e) {
      console.warn("[annotations] Précharge vocabulaires échouée :", e);
    }
  }
  // Lance la précharge dès le script chargé. L'init Annotorious viendra
  // après — si la précharge n'a pas fini, le widget TAG sera initialisé
  // avec une liste vide puis enrichi (Annotorious recharge le widget à
  // chaque édition).
  chargerVocabulaires();

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
      // Synchronise le panneau latéral après le chargement initial.
      // Les events Annotorious (create/update/delete) le re-syncent
      // automatiquement par la suite.
      rafraichirPanneau(anno, fichierId);
    } catch (e) {
      console.warn("[annotations] GET erreur réseau :", e);
    }
  }

  /** Enrichit les bodies d'une annotation : pour chaque TextualBody
   *  `purpose=tagging` (ou body sans purpose avec une `value`) qui
   *  matche une ValeurControlee connue avec URI, ajoute un body
   *  SpecificResource `source=<URI>` `purpose=identifying`. L'URI
   *  devient alors le pivot pour l'export Nakala (δ) et pour les
   *  requêtes cross-fonds (« toutes les annotations de Copi »).
   *
   *  Annotorious 2.x stocke les tags comme `TextualBody value=<libellé>
   *  purpose=tagging`. Au save, on parcourt et enrichit. Idempotent :
   *  si un SpecificResource avec la même URI existe déjà, on ne
   *  duplique pas. */
  function enrichirBodiesAvecUri(annotation) {
    if (!annotation || !Array.isArray(annotation.body)) return annotation;
    const urisExistantes = new Set(
      annotation.body
        .filter(function (b) {
          return b.type === "SpecificResource" && b.source;
        })
        .map(function (b) {
          return b.source;
        }),
    );
    const ajouts = [];
    for (const body of annotation.body) {
      // Seuls les TextualBody (avec purpose tag ou sans purpose) sont
      // candidats à l'enrichissement. On ne touche pas les bodies
      // déjà SpecificResource.
      if (body.type !== "TextualBody") continue;
      const value = body.value;
      if (!value) continue;
      const match = _vocabIndex.get(normaliserLibelle(value));
      if (!match || !match.uri) continue;
      if (urisExistantes.has(match.uri)) continue;
      ajouts.push({
        type: "SpecificResource",
        purpose: "identifying",
        source: match.uri,
      });
      urisExistantes.add(match.uri);
    }
    if (ajouts.length > 0) {
      annotation.body = annotation.body.concat(ajouts);
    }
    return annotation;
  }

  /** Extrait un texte court de l'annotation pour l'affichage panneau.
   *  Priorité : tag (TextualBody purpose=tagging), puis identifying
   *  (libellé), puis commenting (extrait), puis fallback id. */
  function libelleAnnotation(annotation) {
    const bodies = annotation.body || [];
    // Cherche d'abord un tag
    for (const b of bodies) {
      if (b.purpose === "tagging" && b.value) {
        return { texte: b.value, type: "tag" };
      }
    }
    // Puis une identification (URI ou valeur)
    for (const b of bodies) {
      if (b.purpose === "identifying") {
        return {
          texte: b.value || b.source || "(identifié)",
          type: "ident",
        };
      }
    }
    // Puis n'importe quel body avec value
    for (const b of bodies) {
      if (b.value) {
        return { texte: b.value, type: "commentaire" };
      }
    }
    return { texte: "(sans tag)", type: "vide" };
  }

  /** Met à jour le panneau latéral à partir des annotations actuelles. */
  function rafraichirPanneau(anno, fichierId) {
    const panneau = document.querySelector(
      `[data-panneau-annotations="visionneuse-${fichierId}"]`,
    );
    if (!panneau) return;
    const liste = panneau.querySelector("[data-liste]");
    const compteur = panneau.querySelector("[data-compteur]");
    if (!liste || !compteur) return;

    const annotations = anno.getAnnotations() || [];
    compteur.textContent = String(annotations.length);

    if (annotations.length === 0) {
      // Masque le panneau quand vide pour ne pas occuper l'espace.
      panneau.dataset.vide = "1";
      panneau.style.display = "none";
      liste.innerHTML = "";
      return;
    }
    panneau.dataset.vide = "0";
    panneau.style.display = "flex";

    // Tri par création (l'ordre `getAnnotations` n'est pas garanti).
    // On utilise `created` si présent, sinon l'ordre d'insertion.
    const triees = annotations.slice().sort(function (a, b) {
      if (a.created && b.created) {
        return a.created < b.created ? -1 : 1;
      }
      return 0;
    });

    liste.innerHTML = "";
    triees.forEach(function (annotation, idx) {
      const item = document.createElement("li");
      item.style.cssText =
        "padding:6px 10px;border-bottom:1px solid rgba(0,0,0,0.05);cursor:pointer;line-height:1.4;";
      item.dataset.annotationId = annotation.id || "";
      const { texte, type } = libelleAnnotation(annotation);
      const numero = document.createElement("span");
      numero.style.cssText =
        "color:#9ca3af;font-variant-numeric:tabular-nums;margin-right:6px;font-size:11px;";
      numero.textContent = String(idx + 1).padStart(2, "0");
      const lib = document.createElement("span");
      lib.style.cssText = type === "vide" ? "color:#9ca3af;font-style:italic;" : "color:#374151;";
      lib.textContent = texte;
      item.appendChild(numero);
      item.appendChild(lib);
      item.addEventListener("mouseenter", function () {
        item.style.background = "rgba(55, 138, 221, 0.06)";
      });
      item.addEventListener("mouseleave", function () {
        item.style.background = "";
      });
      item.addEventListener("click", function () {
        // Sélectionne l'annotation et zoome dessus. `selectAnnotation`
        // ouvre aussi le popup d'édition (cf. spec Annotorious 2.x).
        // `fitBounds` zoome le viewer OSD sur la région.
        try {
          anno.selectAnnotation(annotation.id);
          if (typeof anno.fitBounds === "function") {
            anno.fitBounds(annotation);
          }
        } catch (e) {
          console.warn("[annotations] selectAnnotation a échoué :", e);
        }
      });
      liste.appendChild(item);
    });
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
      // Widgets du popup d'édition (Annotorious 2.x) :
      //  - COMMENT : zone de texte libre (par défaut)
      //  - TAG     : tags structurés ; avec `vocabulary` la frappe
      //              propose les suggestions (autocomplete). On le
      //              place AVANT COMMENT pour que le tag soit le
      //              premier reflexe utilisateur. Le mapping libellé
      //              → URI est fait au save (enrichirBodiesAvecUri).
      widgets: [
        { widget: "TAG", vocabulary: _vocabLibelles },
        "COMMENT",
      ],
    });

    chargerAnnotations(anno, fichierId);

    // Création : Annotorious appelle createAnnotation après le save
    // de la popup. La réponse serveur contient l'`id` neuf qu'on
    // injecte dans l'annotation pour que les updates ultérieurs
    // pointent au bon endroit.
    anno.on("createAnnotation", async function (annotation) {
      try {
        // γ.3 : enrichit avec URI Wikidata/VIAF si le tag matche une
        // ValeurControlee connue. Pivot autorité pour l'export Nakala.
        enrichirBodiesAvecUri(annotation);
        const sauvee = await creerAnnotation(annotation, fichierId);
        // Remplace l'annotation client (id temporaire) par celle du
        // serveur (id officiel).
        anno.removeAnnotation(annotation);
        anno.addAnnotation(sauvee);
        rafraichirPanneau(anno, fichierId);
      } catch (e) {
        console.error("[annotations] Création échouée :", e);
        anno.removeAnnotation(annotation);
        alert("Création d'annotation échouée. Voir console.");
      }
    });

    // Modification : géométrie ou body modifiés via le popup.
    anno.on("updateAnnotation", async function (annotation) {
      try {
        enrichirBodiesAvecUri(annotation);
        await modifierAnnotation(annotation);
        rafraichirPanneau(anno, fichierId);
      } catch (e) {
        console.error("[annotations] Modification échouée :", e);
        alert("Modification d'annotation échouée. Voir console.");
      }
    });

    // Suppression : poubelle dans le popup.
    anno.on("deleteAnnotation", async function (annotation) {
      try {
        await supprimerAnnotation(annotation);
        rafraichirPanneau(anno, fichierId);
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
