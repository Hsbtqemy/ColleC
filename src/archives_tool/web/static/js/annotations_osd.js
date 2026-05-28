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

  /** Vocabulaire pour le widget TAG d'Annotorious 2.7.
   *  Format natif Annotorious : array d'objets `{label, uri}`.
   *  Quand `uri` est présent, Annotorious crée DIRECTEMENT un
   *  body `SpecificResource purpose=tagging source={id, label}` au
   *  save — pivot Wikidata/VIAF gratuit. Sinon TextualBody value=label.
   *  Vérifié dans le bundle openseadragon-annotorious.min.js :
   *  `onSubmit: function(e) { var n = e.uri ? { type: 'SpecificResource',
   *   purpose: 'tagging', source: { id: e.uri, label: e.label } }
   *   : { type: 'TextualBody', purpose: 'tagging', value: e.label || e } }` */
  const _vocabEntrees = [];

  /** Précharge les valeurs vocabulaire pour l'autocomplete. Non-bloquant :
   *  si l'endpoint échoue, Annotorious démarre sans suggestions et
   *  l'utilisateur peut quand même taper librement.
   *
   *  Quand `fichierId` est fourni, l'endpoint résout fichier → item →
   *  fonds et filtre les vocabulaires selon le rattachement vocab ↔
   *  fonds (cf. `vocabulaire-scoping-future.md` T2). Sans fichier_id,
   *  l'endpoint retourne tout (mode global).
   *
   *  Remplit `_vocabEntrees` en place (vidé d'abord pour éviter les
   *  doublons quand on navigue entre fichiers de fonds différents). */
  async function chargerVocabulaires(fichierId) {
    _vocabEntrees.length = 0;
    const url = fichierId
      ? `/api/vocabulaires/autocomplete?fichier_id=${encodeURIComponent(fichierId)}`
      : "/api/vocabulaires/autocomplete";
    try {
      const r = await fetch(url);
      if (!r.ok) {
        console.warn("[annotations] autocomplete HTTP", r.status);
        return;
      }
      const data = await r.json();
      for (const v of data.valeurs || []) {
        if (!v.libelle) continue;
        // Si URI présent : Annotorious crée un SpecificResource au save.
        // Sinon : juste un libellé pour la suggestion (TextualBody).
        if (v.uri) {
          _vocabEntrees.push({ label: v.libelle, uri: v.uri });
        } else {
          _vocabEntrees.push(v.libelle);
        }
      }
      console.info(
        "[annotations] vocab préchargé (fichier=" + (fichierId || "global") + ") :",
        _vocabEntrees.length,
        "entrées",
      );
    } catch (e) {
      console.warn("[annotations] Précharge vocabulaires échouée :", e);
    }
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
      // Synchronise le panneau latéral après le chargement initial.
      // Les events Annotorious (create/update/delete) le re-syncent
      // automatiquement par la suite.
      rafraichirPanneau(anno, fichierId);
    } catch (e) {
      console.warn("[annotations] GET erreur réseau :", e);
    }
  }

  /** Extrait un texte court de l'annotation pour l'affichage panneau.
   *  Annotorious 2.7 produit deux formes de body de tag :
   *  - `{type: TextualBody, purpose: tagging, value: "Copi"}` (tag libre)
   *  - `{type: SpecificResource, purpose: tagging, source: {id, label}}`
   *    (tag avec URI Wikidata du vocabulaire). Le libellé est dans
   *    `source.label`. Ordre de priorité : tag (n'importe lequel),
   *    puis identifying, puis n'importe quel body avec un texte. */
  function libelleAnnotation(annotation) {
    const bodies = annotation.body || [];
    const labelDeBody = function (b) {
      if (b.value) return b.value;
      if (b.source) {
        if (typeof b.source === "string") return b.source;
        if (b.source.label) return b.source.label;
        if (b.source.id) return b.source.id;
      }
      return null;
    };
    // 1. Cherche un tag (TextualBody value OU SpecificResource source.label)
    for (const b of bodies) {
      if (b.purpose === "tagging") {
        const t = labelDeBody(b);
        if (t) return { texte: t, type: "tag" };
      }
    }
    // 2. Puis une identification explicite
    for (const b of bodies) {
      if (b.purpose === "identifying") {
        const t = labelDeBody(b);
        if (t) return { texte: t, type: "ident" };
      }
    }
    // 3. N'importe quel body avec texte
    for (const b of bodies) {
      const t = labelDeBody(b);
      if (t) return { texte: t, type: "commentaire" };
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
      //  - COMMENT : zone de texte libre
      //  - TAG     : tags structurés. `vocabulary` accepte un array
      //              d'objets `{label, uri}` (ou strings). Si l'entrée
      //              choisie a une `uri`, Annotorious crée un body
      //              `SpecificResource source={id, label}` directement
      //              (pivot Wikidata/VIAF gratuit). Sinon TextualBody.
      //              On place TAG en premier pour qu'il soit l'élément
      //              de saisie naturellement focus.
      widgets: [
        { widget: "TAG", vocabulary: _vocabEntrees },
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
        // γ.3 : si l'utilisateur a choisi un tag avec URI dans le
        // vocabulary, Annotorious crée déjà un body SpecificResource
        // natif (cf. config vocabulary={label,uri}). Pas besoin
        // d'enrichir post-save.
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
  // Attend la précharge vocabulaires pour que le widget TAG ait ses
  // suggestions à l'instanciation (race fix γ.3-revue).
  document.addEventListener("visionneuse:pret", async function (e) {
    const viz = e.target;
    if (_annosParViseur.has(viz)) return; // déjà greffé (re-open)
    const { osd, fichier_id } = e.detail || {};
    if (!osd) return;
    // Charge le vocab filtré par le fichier courant — Annotorious démarre
    // avec les suggestions adaptées au fonds (cf. T2 scoping). Le widget
    // TAG capture la référence à `_vocabEntrees` à l'instanciation, donc
    // le remplissage doit être terminé AVANT initialiserAnnotorious.
    await chargerVocabulaires(fichier_id);
    const anno = initialiserAnnotorious(osd, fichier_id);
    if (anno) {
      _annosParViseur.set(viz, anno);
    }
  });

  /** Outils de dessin supportés. Annotorious 2.x accepte ces deux-là.
   *  - `rect`    : rectangle aligné. Drag pour dessiner.
   *  - `polygon` : polygone libre. Clic pour ajouter un point,
   *                double-clic pour fermer la forme. */
  const _OUTILS_VALIDES = new Set(["rect", "polygon"]);

  /** Retrouve le viewer + anno associé à un bouton du groupe (toggle
   *  Annoter ou sélecteur d'outil). Les boutons partagent un attribut
   *  `data-annoter-cible="visionneuse-<id>"` qui pointe sur le viewer. */
  function annoDepuisBouton(btn) {
    const cibleId = btn.dataset.annoterToggle || btn.dataset.annoterCible;
    if (!cibleId) return { viz: null, anno: null };
    const viz = document.getElementById(cibleId);
    if (!viz) return { viz: null, anno: null };
    return { viz, anno: _annosParViseur.get(viz) || null };
  }

  /** Met à jour l'état visuel des boutons d'outil (actif = data-actif="1"). */
  function rafraichirBoutonsOutil(cibleId, outilActif) {
    const boutons = document.querySelectorAll(
      `[data-annoter-outil][data-annoter-cible="${cibleId}"]`,
    );
    boutons.forEach(function (b) {
      b.dataset.actif = b.dataset.annoterOutil === outilActif ? "1" : "0";
    });
  }

  /** Affiche / masque le groupe d'outils selon que l'édition est active. */
  function rafraichirVisibiliteOutils(cibleId, edition) {
    const groupe = document.querySelector(
      `[data-annoter-outils][data-annoter-cible="${cibleId}"]`,
    );
    if (groupe) {
      groupe.dataset.edition = edition ? "1" : "0";
    }
  }

  // Bouton externe « Annoter » → bascule readOnly + setDrawingTool
  // sur le viewer cible. Le bouton porte `data-annoter-toggle` avec
  // la valeur = id du viewer (`visionneuse-<fichier_id>`).
  // Boutons d'outil (`data-annoter-outil="rect|polygon"`) basculent
  // l'outil actif sans toucher au mode lecture/édition.
  document.addEventListener("click", function (e) {
    // Switch d'outil pendant l'édition.
    const btnOutil = e.target.closest("[data-annoter-outil]");
    if (btnOutil) {
      e.preventDefault();
      const { anno, viz } = annoDepuisBouton(btnOutil);
      if (!anno || !viz) return;
      const outil = btnOutil.dataset.annoterOutil;
      if (!_OUTILS_VALIDES.has(outil)) return;
      // Si on est encore en lecture, le clic sur un outil active aussi
      // l'édition — geste plus naturel que de forcer deux clics.
      if (anno.readOnly) {
        anno.readOnly = false;
        const btnToggle = document.querySelector(
          `[data-annoter-toggle="${viz.id}"]`,
        );
        if (btnToggle) {
          btnToggle.dataset.annoterActif = "1";
          btnToggle.textContent = "Annoter (actif)";
        }
        rafraichirVisibiliteOutils(viz.id, true);
      }
      anno.setDrawingTool(outil);
      rafraichirBoutonsOutil(viz.id, outil);
      return;
    }

    // Toggle édition / lecture.
    const btn = e.target.closest("[data-annoter-toggle]");
    if (!btn) return;
    e.preventDefault();
    const { anno, viz } = annoDepuisBouton(btn);
    if (!anno || !viz) {
      console.warn("[annotations] Pas d'instance Annotorious sur", btn.dataset.annoterToggle);
      return;
    }
    // Toggle readOnly. Annotorious 2.x : `setDrawingEnabled` est
    // contrôlé indirectement par readOnly + setDrawingTool.
    const enLecture = anno.readOnly;
    anno.readOnly = !enLecture;
    btn.dataset.annoterActif = enLecture ? "1" : "0";
    btn.textContent = enLecture ? "Annoter (actif)" : "Annoter";
    rafraichirVisibiliteOutils(viz.id, enLecture);
    if (!enLecture) {
      // On bascule en lecture : neutraliser tout dessin en cours.
      try { anno.cancelSelected(); } catch (_) {}
    } else {
      // Activation : on respecte un outil déjà sélectionné si présent,
      // sinon rectangle par défaut.
      const dejaActif = document.querySelector(
        `[data-annoter-outil][data-annoter-cible="${viz.id}"][data-actif="1"]`,
      );
      const outil = dejaActif ? dejaActif.dataset.annoterOutil : "rect";
      anno.setDrawingTool(outil);
      rafraichirBoutonsOutil(viz.id, outil);
    }
  });
})();
