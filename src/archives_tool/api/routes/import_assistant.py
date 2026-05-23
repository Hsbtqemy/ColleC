"""Routes de l'assistant d'import web (V0.7).

Wizard multi-pages : chaque étape a son URL `/import/{id}/{etape}`.
`/import/{id}` redirige vers l'étape courante de la session. Une
étape non encore atteinte redirige vers l'étape courante (pas de
saut en avant). L'état est persisté dans `SessionImport` à chaque
POST — l'utilisateur peut fermer et reprendre.

Sous-étape 1 : cycle de vie (accueil, création, abandon).
Sous-étape 2 : upload tableur + saisie des métadonnées du fonds.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_config,
    get_db,
    get_nom_base,
    get_racines,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import (
    charger_session_import_ou_404,
    contexte_base as _contexte_base,
)
from archives_tool.api.services.import_web import (
    CIBLE_IGNORE,
    CIBLE_META,
    CIBLE_META_FICHIER,
    TAILLE_MAX_TABLEUR,
    MappingInvalide,
    ProfilIncomplet,
    TableurInvalide,
    abandonner_session,
    apercu_import,
    attacher_tableur,
    cibles_proposees,
    colonnes_champs_avances,
    construire_mapping,
    construire_mapping_depuis_simple,
    creer_session,
    detecter_anomalies_mapping,
    enregistrer_fonds,
    enregistrer_mapping,
    enregistrer_resolution,
    executer_import,
    lister_sessions_en_cours,
    suggerer_reponses_simple,
)
from archives_tool.api.templating import templates
from archives_tool.config import ConfigLocale
from archives_tool.models import ETAPES_IMPORT, Fonds, SessionImport
from archives_tool.profils.schema import FondsProfil, Profil, ResolutionFichiers

router = APIRouter()


# ---------------------------------------------------------------------------
# Accueil + cycle de vie
# ---------------------------------------------------------------------------


@router.get("/import", response_class=HTMLResponse)
def page_import(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Accueil de l'assistant : imports en cours + démarrer un import."""
    sessions = lister_sessions_en_cours(db)
    return templates.TemplateResponse(
        request,
        "pages/import_accueil.html",
        _contexte_base(nom_base, utilisateur, sessions=sessions),
    )


@router.post("/import/nouveau", response_class=HTMLResponse, response_model=None)
def nouveau_import(
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Crée une session d'import vierge et ouvre sa première étape."""
    session = creer_session(db, utilisateur)
    return RedirectResponse(f"/import/{session.id}", status_code=303)


@router.post(
    "/import/{session_id}/abandonner",
    response_class=HTMLResponse,
    response_model=None,
)
def abandonner_import(
    session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Abandonne une session : statut `abandonnee`, tableur temporaire
    supprimé. Idempotent."""
    session = charger_session_import_ou_404(db, session_id)
    abandonner_session(db, session)
    return RedirectResponse("/import", status_code=303)


@router.get("/import/{session_id}", response_class=HTMLResponse, response_model=None)
def page_session_import(
    session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Ouvre une session sur son étape courante."""
    session = charger_session_import_ou_404(db, session_id)
    return RedirectResponse(
        f"/import/{session.id}/{session.etape}", status_code=303
    )


# ---------------------------------------------------------------------------
# Navigation entre étapes
# ---------------------------------------------------------------------------


def _rediriger_vers_etape_courante(session: SessionImport) -> RedirectResponse:
    return RedirectResponse(
        f"/import/{session.id}/{session.etape}", status_code=303
    )


def _etape_accessible(session: SessionImport, demandee: str) -> bool:
    """Vrai si l'utilisateur peut afficher `demandee` : une étape déjà
    franchie ou l'étape courante, jamais un saut en avant."""
    return ETAPES_IMPORT.index(demandee) <= ETAPES_IMPORT.index(session.etape)


# ---------------------------------------------------------------------------
# Étape 1 — upload du tableur
# ---------------------------------------------------------------------------


@router.get(
    "/import/{session_id}/tableur",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_tableur(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    session = charger_session_import_ou_404(db, session_id)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_tableur.html",
        _contexte_base(nom_base, utilisateur, session=session, erreur=None),
    )


@router.post(
    "/import/{session_id}/tableur",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_tableur(
    session_id: int,
    request: Request,
    fichier: UploadFile,
    feuille: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    # Lecture bornée : on ne charge jamais plus que la limite + 1 octet
    # en mémoire. `attacher_tableur` rejette si la taille dépasse la
    # limite — un upload géant est ainsi tronqué, pas avalé en entier.
    contenu = fichier.file.read(TAILLE_MAX_TABLEUR + 1)
    try:
        attacher_tableur(
            db,
            session,
            contenu,
            fichier.filename or "tableur",
            feuille=feuille.strip() or None,
        )
    except TableurInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_tableur.html",
            _contexte_base(
                nom_base, utilisateur, session=session, erreur=str(e)
            ),
            status_code=400,
        )
    return RedirectResponse(f"/import/{session.id}/fonds", status_code=303)


# ---------------------------------------------------------------------------
# Étape 2 — métadonnées du fonds
# ---------------------------------------------------------------------------

# Champs de la section `fonds:` exposés par le formulaire, dans l'ordre
# d'affichage. cote + titre sont obligatoires (FondsProfil), le reste
# optionnel.
_CHAMPS_FONDS: tuple[str, ...] = (
    "cote",
    "titre",
    "description",
    "description_interne",
    "editeur",
    "lieu_edition",
    "periodicite",
    "issn",
    "date_debut",
    "date_fin",
    "responsable_archives",
    "personnalite_associee",
)


@router.get(
    "/import/{session_id}/fonds",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_fonds(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "fonds"):
        return _rediriger_vers_etape_courante(session)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_fonds.html",
        _contexte_base(
            nom_base,
            utilisateur,
            session=session,
            valeurs=session.fonds_data or {},
            champs=_CHAMPS_FONDS,
            erreurs={},
        ),
    )


@router.post(
    "/import/{session_id}/fonds",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_fonds(
    session_id: int,
    request: Request,
    cote: Annotated[str, Form()] = "",
    titre: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    description_interne: Annotated[str, Form()] = "",
    editeur: Annotated[str, Form()] = "",
    lieu_edition: Annotated[str, Form()] = "",
    periodicite: Annotated[str, Form()] = "",
    issn: Annotated[str, Form()] = "",
    date_debut: Annotated[str, Form()] = "",
    date_fin: Annotated[str, Form()] = "",
    responsable_archives: Annotated[str, Form()] = "",
    personnalite_associee: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    # Champs vides → absents du dict : FondsProfil les traitera comme
    # None (valeur par défaut), pas comme chaîne vide.
    brut = {
        "cote": cote,
        "titre": titre,
        "description": description,
        "description_interne": description_interne,
        "editeur": editeur,
        "lieu_edition": lieu_edition,
        "periodicite": periodicite,
        "issn": issn,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "responsable_archives": responsable_archives,
        "personnalite_associee": personnalite_associee,
    }
    fonds_data = {k: v.strip() for k, v in brut.items() if v and v.strip()}

    try:
        FondsProfil.model_validate(fonds_data)
    except ValidationError as e:
        erreurs = {
            str(err["loc"][0]): err["msg"]
            for err in e.errors()
            if err.get("loc")
        }
        return templates.TemplateResponse(
            request,
            "pages/import_etape_fonds.html",
            _contexte_base(
                nom_base,
                utilisateur,
                session=session,
                valeurs=fonds_data,
                champs=_CHAMPS_FONDS,
                erreurs=erreurs,
            ),
            status_code=400,
        )

    enregistrer_fonds(db, session, fonds_data)
    return RedirectResponse(f"/import/{session.id}/mapping", status_code=303)


# ---------------------------------------------------------------------------
# Étape 3 — mapping colonnes → champs
# ---------------------------------------------------------------------------

# Cibles de mapping d'une colonne. `__meta__` et `__ignore__`
# (sentinelles de import_web) sont rendus à part.
# Champs de niveau item :
_CIBLES_ITEM: tuple[tuple[str, str], ...] = (
    ("cote", "Cote"),
    ("titre", "Titre"),
    ("numero", "Numéro"),
    ("date", "Date"),
    ("annee", "Année"),
    ("type_coar", "Type COAR"),
    ("langue", "Langue"),
    ("description", "Description"),
    ("notes_internes", "Notes internes"),
    ("doi_nakala", "DOI Nakala"),
    ("doi_collection_nakala", "DOI collection"),
)
# Champs de niveau fichier (granularité fichier — une ligne = un scan).
_CIBLES_FICHIER: tuple[tuple[str, str], ...] = (
    ("fichier.nom_fichier", "Nom du fichier"),
    ("fichier.hash_sha256", "Hash (empreinte)"),
    ("fichier.iiif_url_nakala", "URL IIIF Nakala"),
)
# Champs DC fréquents qui n'ont pas de colonne dédiée sur `Item` mais
# qui méritent d'apparaître dans le sélecteur — autrement l'utilisateur
# cherche « auteur » dans la liste, ne trouve pas, et zappe la donnée
# au lieu de la pousser via « Métadonnée personnalisée ». Chaque cible
# est techniquement un préfixe `metadonnees.<slug>` traité comme un
# champ dédié (mapping[clé] = colonne, déduplication d'office).
# Les clés ici sont la source de vérité pour le sélecteur ; le service
# `import_web` expose le set parallèle `_CIBLES_META_CANONIQUES` qui
# doit rester synchronisé (cf. test `test_alignement_meta_canoniques`).
_CIBLES_META_FREQUENTES: tuple[tuple[str, str], ...] = (
    ("metadonnees.auteur", "Auteur"),
    ("metadonnees.editeur", "Éditeur"),
    ("metadonnees.contributeur", "Contributeur"),
    ("metadonnees.sujet", "Sujet / mots-clés"),
    ("metadonnees.droits", "Droits / licence"),
    ("metadonnees.source", "Source"),
)

# Hints affichés sous le sélecteur quand une cible est choisie.
# Texte court (< 100 char) qui explique ce que la cible attend, à
# destination de l'utilisateur qui ne connait pas le vocabulaire
# interne (type_coar, fichier.iiif_url_nakala, etc.). Les sentinelles
# `__meta__` / `__meta_fichier__` / `__ignore__` ont aussi leur hint.
_HINTS_CIBLES: dict[str, str] = {
    # Item — structurants.
    "cote": "Identifiant unique de l'item dans le fonds (obligatoire).",
    "titre": "Titre principal de l'item, indexé pour la recherche.",
    "numero": "Numéro ou tomaison (ex. « N°47 », « Tome II »).",
    "date": (
        "Date au format EDTF — accepte les dates incertaines "
        "(`1923?`, `192X`, `1923/1924`)."
    ),
    "annee": "Année extraite, entier indexé (ex. 1923).",
    "type_coar": (
        "URI Coar Resource Type (ex. "
        "`https://purl.org/coar/resource_type/c_18cf` pour Manuscrit)."
    ),
    "langue": "Code ISO 639-3 (ex. `fra`, `eng`, `spa`).",
    "description": "Description publique destinée aux exports DC.",
    "notes_internes": (
        "Notes équipe pour le chantier — ne sont pas exportées en DC."
    ),
    "doi_nakala": "DOI Nakala de l'item publié (ex. `10.34847/nkl.xxx`).",
    "doi_collection_nakala": (
        "DOI Nakala de la collection-parent dans laquelle l'item est publié."
    ),
    # Fichier — propres à un scan.
    "fichier.nom_fichier": "Nom du scan (ex. `xxx_001.tif`).",
    "fichier.hash_sha256": "Empreinte SHA-256 du fichier source.",
    "fichier.iiif_url_nakala": (
        "URL `info.json` IIIF du fichier déposé sur Nakala."
    ),
    # Métadonnées DC fréquentes (rangées dans `Item.metadonnees`).
    "metadonnees.auteur": "Auteur principal (DC creator), texte libre.",
    "metadonnees.editeur": "Éditeur ou maison d'édition (DC publisher).",
    "metadonnees.contributeur": "Contributeur secondaire (DC contributor).",
    "metadonnees.sujet": "Sujet ou mots-clés (DC subject), texte libre.",
    "metadonnees.droits": "Licence ou statut de droits (DC rights).",
    "metadonnees.source": "Source d'origine de l'item (DC source).",
    # Sentinelles : volontairement vides. Le libellé d'option dans le
    # sélecteur (« Métadonnée personnalisée (item) », « — Ne pas
    # importer ») se suffit à lui-même, et l'heuristique de proposition
    # place beaucoup de colonnes sur `__meta__` au upload — répéter
    # 25 fois la même phrase serait du bruit visuel.
    CIBLE_META: "",
    CIBLE_META_FICHIER: "",
    CIBLE_IGNORE: "",
}


def _contexte_mapping(
    nom_base: str,
    utilisateur: str,
    session: SessionImport,
    cibles: list[str],
    erreur: str | None,
    granularite: str = "item",
) -> dict[str, object]:
    """Contexte du template mapping : colonnes + cible choisie pour
    chacune (alignées par position) + granularité + anomalies
    détectées entre cibles et classif (V0.9.2-import #4)."""
    colonnes = list(session.colonnes_detectees or [])
    return _contexte_base(
        nom_base,
        utilisateur,
        session=session,
        lignes=list(zip(colonnes, cibles)),
        cibles_item=_CIBLES_ITEM,
        cibles_fichier=_CIBLES_FICHIER,
        cibles_meta_frequentes=_CIBLES_META_FREQUENTES,
        cible_meta=CIBLE_META,
        cible_meta_fichier=CIBLE_META_FICHIER,
        cible_ignore=CIBLE_IGNORE,
        hints_cibles=_HINTS_CIBLES,
        echantillons=session.colonnes_echantillon or {},
        anomalies=detecter_anomalies_mapping(session, cibles),
        granularite=granularite,
        erreur=erreur,
    )


def _contexte_mapping_simple(
    nom_base: str,
    utilisateur: str,
    session: SessionImport,
    suggestions,
    erreur: str | None,
    valeurs: dict[str, str] | None = None,
) -> dict[str, object]:
    """Contexte du template mapping simple : 4 questions explicites.

    `valeurs` permet de réafficher les choix utilisateur tels quels en
    cas d'erreur de validation (sinon les radio/select retomberaient
    sur les suggestions par défaut).

    `champs_avances_perdus` (V0.9.2-import #3) liste les colonnes du
    mapping existant qui seraient ramenées en metadonnees au prochain
    submit simple — le template affiche un avertissement non-bloquant
    si la liste n'est pas vide."""
    return _contexte_base(
        nom_base,
        utilisateur,
        session=session,
        colonnes_disponibles=list(session.colonnes_detectees or []),
        echantillons=session.colonnes_echantillon or {},
        suggestions=suggestions,
        valeurs=valeurs or {},
        champs_avances_perdus=colonnes_champs_avances(session),
        erreur=erreur,
    )


@router.get(
    "/import/{session_id}/mapping",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_mapping(
    session_id: int,
    request: Request,
    avance: bool = False,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Étape mapping. Mode simple par défaut (4 questions, V0.9.2-import
    #3). `?avance=1` ouvre le mode avancé historique (28 selects)."""
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "mapping"):
        return _rediriger_vers_etape_courante(session)
    if avance:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_mapping.html",
            _contexte_mapping(
                nom_base,
                utilisateur,
                session,
                cibles_proposees(session),
                None,
                granularite=session.granularite,
            ),
        )
    return templates.TemplateResponse(
        request,
        "pages/import_etape_mapping_simple.html",
        _contexte_mapping_simple(
            nom_base,
            utilisateur,
            session,
            suggerer_reponses_simple(session),
            None,
        ),
    )


@router.post(
    "/import/{session_id}/mapping/simple",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_mapping_simple(
    session_id: int,
    request: Request,
    colonne_cote: Annotated[str, Form()] = "",
    granularite: Annotated[str, Form()] = "item",
    colonne_titre: Annotated[str, Form()] = "",
    colonne_date: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """V0.9.2-import #3 — soumission du mode simple (4 questions).

    Construit un mapping complet : colonnes explicitement choisies →
    champs dédiés, le reste → metadonnees.<slug> (item ou fichier
    selon la classif statistique). Re-render avec erreur si validation
    échoue."""
    session = charger_session_import_ou_404(db, session_id)
    valeurs = {
        "colonne_cote": colonne_cote,
        "granularite": granularite,
        "colonne_titre": colonne_titre,
        "colonne_date": colonne_date,
    }
    if not colonne_cote.strip():
        return templates.TemplateResponse(
            request,
            "pages/import_etape_mapping_simple.html",
            _contexte_mapping_simple(
                nom_base,
                utilisateur,
                session,
                suggerer_reponses_simple(session),
                "Choisissez la colonne qui identifie chaque item.",
                valeurs=valeurs,
            ),
            status_code=400,
        )
    try:
        mapping = construire_mapping_depuis_simple(
            session,
            colonne_cote=colonne_cote.strip(),
            colonne_titre=colonne_titre.strip() or None,
            colonne_date=colonne_date.strip() or None,
        )
    except MappingInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_mapping_simple.html",
            _contexte_mapping_simple(
                nom_base,
                utilisateur,
                session,
                suggerer_reponses_simple(session),
                str(e),
                valeurs=valeurs,
            ),
            status_code=400,
        )
    enregistrer_mapping(db, session, mapping, granularite)
    return RedirectResponse(f"/import/{session.id}/fichiers", status_code=303)


@router.post(
    "/import/{session_id}/mapping",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_mapping(
    session_id: int,
    request: Request,
    cible: Annotated[list[str], Form()] = [],  # noqa: B006 — FastAPI relit Form().
    granularite: Annotated[str, Form()] = "item",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    colonnes = list(session.colonnes_detectees or [])
    try:
        mapping = construire_mapping(colonnes, cible)
    except MappingInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_mapping.html",
            _contexte_mapping(
                nom_base, utilisateur, session, cible, str(e), granularite
            ),
            status_code=400,
        )
    enregistrer_mapping(db, session, mapping, granularite)
    return RedirectResponse(f"/import/{session.id}/fichiers", status_code=303)


# ---------------------------------------------------------------------------
# Étape 4 — résolution des fichiers (optionnelle)
# ---------------------------------------------------------------------------


@router.get(
    "/import/{session_id}/fichiers",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_fichiers(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    racines: dict = Depends(get_racines),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "fichiers"):
        return _rediriger_vers_etape_courante(session)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_fichiers.html",
        _contexte_base(
            nom_base,
            utilisateur,
            session=session,
            racines=sorted(racines.keys()),
            config=session.configuration_fichiers or {},
            erreur=None,
        ),
    )


@router.post(
    "/import/{session_id}/fichiers",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_fichiers(
    session_id: int,
    request: Request,
    racine: Annotated[str, Form()] = "",
    motif_chemin: Annotated[str, Form()] = "",
    type_motif: Annotated[str, Form()] = "template",
    ordre_depuis_nom: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    racines: dict = Depends(get_racines),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    ordre = ordre_depuis_nom.strip()

    def _rerendre(erreur: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_fichiers.html",
            _contexte_base(
                nom_base,
                utilisateur,
                session=session,
                racines=sorted(racines.keys()),
                config={
                    "racine": racine,
                    "motif_chemin": motif_chemin,
                    "type_motif": type_motif,
                    "ordre_depuis_nom": ordre,
                },
                erreur=erreur,
            ),
            status_code=400,
        )

    # Valider la regex `ordre_depuis_nom` independamment du reste —
    # `Profil._valider_regex_ordre` lève si la regex ne compile pas
    # ou n'a aucun groupe de capture.
    if ordre:
        try:
            Profil.model_validate(
                {
                    "version_profil": 2,
                    "fonds": {"cote": "_", "titre": "_"},
                    "tableur": {"chemin": "_"},
                    "mapping": {"cote": "_"},
                    "ordre_depuis_nom": ordre,
                }
            )
        except ValidationError as e:
            premier = e.errors()[0]
            return _rerendre(premier.get("msg", "Regex ordre invalide."))

    # Racine vide → metadonnees seules ; mais on conserve `ordre_depuis_nom`
    # si l'utilisateur en a posé une (cas Nakala / colonnes).
    if not racine.strip():
        config = {"ordre_depuis_nom": ordre} if ordre else None
        enregistrer_resolution(db, session, config)
        return RedirectResponse(
            f"/import/{session.id}/apercu", status_code=303
        )

    config = {
        "racine": racine.strip(),
        "motif_chemin": motif_chemin.strip(),
        "type_motif": type_motif,
    }
    try:
        ResolutionFichiers.model_validate(config)
    except ValidationError as e:
        premier = e.errors()[0]
        return _rerendre(premier.get("msg", "Configuration fichiers invalide."))
    if ordre:
        config["ordre_depuis_nom"] = ordre
    enregistrer_resolution(db, session, config)
    return RedirectResponse(f"/import/{session.id}/apercu", status_code=303)


# ---------------------------------------------------------------------------
# Étape 5 — aperçu (dry-run) + exécution
# ---------------------------------------------------------------------------


def _cote_fonds_cree(db: Session, session: SessionImport) -> str | None:
    """Cote du fonds créé par une session déjà exécutée, ou None."""
    if session.fonds_cree_id is None:
        return None
    fonds = db.get(Fonds, session.fonds_cree_id)
    return fonds.cote if fonds is not None else None


def _autres_warnings(rapport) -> list[str]:
    """Warnings hors divergences déjà résumées dans `divergences_aggregees`.

    V0.9.2-import T6 — les divergences agrégées sont rendues dans
    un bloc résumé séparé ; on filtre les warnings flat qui les
    portent (via `MARQUEUR_WARNING_DIVERGENCE`) pour éviter le doublon
    dans le bloc « Autres avertissements ».
    """
    from archives_tool.importers.ecrivain import MARQUEUR_WARNING_DIVERGENCE

    if rapport is None:
        return []
    return [
        w for w in rapport.warnings
        if MARQUEUR_WARNING_DIVERGENCE not in w
    ]


@router.get(
    "/import/{session_id}/apercu",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_apercu(
    session_id: int,
    request: Request,
    tolerer_sans_cote: bool = False,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    config: ConfigLocale = Depends(get_config),
) -> HTMLResponse | RedirectResponse:
    """Aperçu dry-run. `?tolerer_sans_cote=true` relance la simulation
    en ignorant les lignes sans cote au lieu de les compter en erreur."""
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "apercu"):
        return _rediriger_vers_etape_courante(session)

    # Session déjà exécutée : on montre le résultat, pas un dry-run.
    if session.statut == "validee":
        return templates.TemplateResponse(
            request,
            "pages/import_etape_apercu.html",
            _contexte_base(
                nom_base,
                utilisateur,
                session=session,
                rapport=None,
                autres_warnings=[],
                erreur=None,
                fonds_cote=_cote_fonds_cree(db, session),
                tolerer_sans_cote=False,
            ),
        )

    erreur: str | None = None
    rapport = None
    try:
        rapport = apercu_import(
            db, session, config, ignorer_lignes_sans_cote=tolerer_sans_cote
        )
    except ProfilIncomplet as e:
        erreur = str(e)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_apercu.html",
        _contexte_base(
            nom_base,
            utilisateur,
            session=session,
            rapport=rapport,
            autres_warnings=_autres_warnings(rapport),
            erreur=erreur,
            fonds_cote=None,
            tolerer_sans_cote=tolerer_sans_cote,
        ),
    )


@router.post(
    "/import/{session_id}/executer",
    response_class=HTMLResponse,
    response_model=None,
)
def executer_import_route(
    session_id: int,
    request: Request,
    tolerer_sans_cote: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    config: ConfigLocale = Depends(get_config),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)

    # Déjà exécutée : on renvoie vers le fonds créé (POST idempotent).
    if session.statut == "validee":
        cote = _cote_fonds_cree(db, session)
        cible = f"/fonds/{cote}" if cote else "/import"
        return RedirectResponse(cible, status_code=303)

    if not _etape_accessible(session, "apercu"):
        return _rediriger_vers_etape_courante(session)

    def _rerendre(erreur: str | None, rapport) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_apercu.html",
            _contexte_base(
                nom_base,
                utilisateur,
                session=session,
                rapport=rapport,
                autres_warnings=_autres_warnings(rapport),
                erreur=erreur,
                fonds_cote=None,
                tolerer_sans_cote=tolerer_sans_cote,
            ),
            status_code=400,
        )

    try:
        rapport = executer_import(
            db,
            session,
            config,
            utilisateur,
            ignorer_lignes_sans_cote=tolerer_sans_cote,
        )
    except ProfilIncomplet as e:
        return _rerendre(str(e), None)
    if rapport.erreurs:
        return _rerendre(None, rapport)

    return RedirectResponse(
        f"/fonds/{rapport.fonds_cote}", status_code=303
    )
