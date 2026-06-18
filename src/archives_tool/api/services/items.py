"""CRUD Item — création dans un fonds + auto-rattachement à la miroir.

Source de vérité pour les invariants 4 et 6 :
- Tout item a `fonds_id` non NULL (CHECK + service refuse).
- À la création, l'item est ajouté à la collection miroir du fonds
  (invariant 6) — dans la même transaction que la création.

Le `fonds_id` d'un item est immuable : déplacer un item d'un fonds
à un autre n'a pas de sens (sa cote serait incohérente). Pour
« déplacer », supprimer et recréer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.affichage.formatters import (
    date_incertaine as _date_incertaine,
    temps_relatif,
)
from archives_tool.api.services.conflits import (
    convertir_stale_data,
    verifier_et_incrementer_version,
)
from archives_tool.api.services._erreurs import (
    EntiteIntrouvable,
    FormulaireInvalide,
    OperationInterdite,
    chaine_ou_none,
    garde_cote_unique,
    valider_cote_titre,
)
from archives_tool.api.services.operations_entite import (
    journaliser_suppression_item,
)
from archives_tool.api.services.tri import (
    Listage,
    Ordre,
    appliquer_tri,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)


_ETATS_VALIDES: frozenset[str] = frozenset(e.value for e in EtatCatalogage)

#: Plage plausible pour `Item.annee` (index numérique). Partagée par le
#: validateur `FormulaireItem._annee_borne` et la dérivation
#: `annee_depuis_date_edtf` — les deux DOIVENT s'accorder, sinon une
#: année dérivée hors plage casse le round-trip du formulaire.
ANNEE_MIN: int = 0
ANNEE_MAX: int = 3000


class ItemIntrouvable(EntiteIntrouvable):
    """L'identifiant ou la cote de l'item n'existe pas."""


class ItemInvalide(FormulaireInvalide):
    """Données de formulaire invalides."""


class OperationItemInterdite(OperationInterdite):
    """Opération refusée : changer le fonds, fonds sans miroir, etc."""


class FormulaireItem(BaseModel):
    """Formulaire de création / modification d'un item.

    `fonds_id` est obligatoire à la création et immuable à la
    modification (le service `modifier_item` rejette tout changement).
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    cote: str = Field(default="")
    titre: str = Field(default="")
    fonds_id: int = Field(default=0)
    # Verrou optimiste : version lue à l'ouverture du formulaire,
    # comparée à la version actuelle au save. None à la création
    # (l'item n'existe pas encore).
    version: int | None = None

    description: str = Field(default="")
    notes_internes: str = Field(default="")
    type_coar: str = Field(default="")
    langue: str = Field(default="")
    date: str = Field(default="")
    annee: int | None = None
    numero: str = Field(default="")
    numero_tri: int | None = None
    etat_catalogage: str = Field(default=EtatCatalogage.BROUILLON.value)
    metadonnees: dict[str, Any] = Field(default_factory=dict)
    doi_nakala: str = Field(default="")
    doi_collection_nakala: str = Field(default="")

    @field_validator("annee")
    @classmethod
    def _annee_borne(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < ANNEE_MIN or v > ANNEE_MAX:
            raise ValueError(f"Année invraisemblable : {v}")
        return v

    @field_validator("etat_catalogage")
    @classmethod
    def _etat_valide(cls, v: str) -> str:
        if v and v not in _ETATS_VALIDES:
            raise ValueError(f"État inconnu : {v!r}")
        return v or EtatCatalogage.BROUILLON.value


@dataclass
class ItemResume:
    id: int
    cote: str
    titre: str | None
    fonds_id: int
    fonds_cote: str
    etat: str
    date: str | None = None
    annee: int | None = None
    type_coar: str | None = None
    nb_collections: int = 0
    nb_fichiers: int = 0
    modifie_le: datetime | None = None
    modifie_par: str | None = None
    description: str | None = None
    langue: str | None = None
    doi_nakala: str | None = None
    doi_collection_nakala: str | None = None
    metadonnees: dict[str, Any] | None = None

    # ---- Aliases attendus par la macro `tableau_items` (cf.
    # `web/templates/components/tableau_items.html`) -----
    # La macro accède : cote, href, titre, type_chaine, type_label,
    # date, date_incertaine, etat, nb_fichiers, modifie_par,
    # modifie_depuis, meta. Les passerelles ci-dessous évitent une
    # dataclass jumelle.

    @property
    def href(self) -> str:
        return f"/item/{self.cote}?fonds={self.fonds_cote}"

    @property
    def date_incertaine(self) -> bool:
        # Délègue au helper canonique de `affichage/formatters` qui
        # reconnaît `?`, `vers`, `c.`/`ca.`, `s.d.` (insensible à la casse).
        return _date_incertaine(self.date)

    @property
    def type_chaine(self) -> str | None:
        # V0.9.0 : pas de hiérarchie de type chaînée (modèle plat).
        return None

    @property
    def type_label(self) -> str | None:
        # V0.9.4 : libellé humain résolu via TYPES_COAR_OPTIONS
        # (la même table que le composer cartouche et la barre de
        # filtres recherche). Le tableau d'items affichait sinon
        # l'URI brute « http://purl.org/coar/resource_type/c_3e5a »
        # — illisible quand la colonne Type est étroite.
        from archives_tool.api.services.vocabulaires import (
            TYPES_COAR_OPTIONS,
            libelle_pour_valeur,
        )

        if not self.type_coar:
            return None
        libelle = libelle_pour_valeur(self.type_coar, TYPES_COAR_OPTIONS)
        # `libelle_pour_valeur` retombe sur la valeur brute si
        # l'URI n'est pas dans la table — on retourne None dans ce
        # cas pour que le template tombe sur `type_coar` (idem que
        # comportement V0.9.0, pas de double affichage).
        if libelle == self.type_coar:
            return None
        return libelle

    @property
    def modifie_depuis(self) -> str:
        return temps_relatif(self.modifie_le)

    @property
    def meta(self) -> dict[str, Any]:
        return self.metadonnees or {}


def _valider_formulaire(formulaire: FormulaireItem) -> dict[str, str]:
    erreurs = valider_cote_titre(formulaire.cote, formulaire.titre)
    if formulaire.fonds_id <= 0:
        erreurs["fonds_id"] = "Le fonds est obligatoire."
    return erreurs


_OPTIONNELS_NULLABLES: tuple[str, ...] = (
    "description",
    "notes_internes",
    "type_coar",
    "langue",
    "date",
    "numero",
    "doi_nakala",
    "doi_collection_nakala",
)


_REGEX_ANNEE_EDTF = re.compile(r"^-?(\d{4})")


def annee_depuis_date_edtf(date: str | None) -> int | None:
    """Extrait l'année (entier) d'une chaîne de date EDTF tolérante.

    Couvre `1974`, `1974-03`, `1974-03-11`. Retourne `None` sur
    l'imprécis (`vers 1974`, `19XX`, `s.d.`) et sur toute année hors
    de la plage plausible `[ANNEE_MIN, ANNEE_MAX]` — BCE (`-0044`) ou
    aberrante (`9999`) : la date garde son info textuelle, mais l'index
    numérique reste vide et le filtre temporel skip l'item.

    La borne est volontairement la même que le validateur
    :meth:`FormulaireItem._annee_borne` : `annee` étant dérivée *après*
    la validation Pydantic, une valeur hors plage stockée ici casserait
    le round-trip `formulaire_depuis_item` au prochain chargement.

    `annee` est entièrement dérivée de `date` depuis V0.9.8 : ce helper
    est appelé par `_appliquer_formulaire` à chaque save, et l'UI n'expose
    plus `annee` en édition directe.
    """
    if not date:
        return None
    texte = date.strip()
    m = _REGEX_ANNEE_EDTF.match(texte)
    if not m:
        return None
    annee = (-1 if texte.startswith("-") else 1) * int(m.group(1))
    if annee < ANNEE_MIN or annee > ANNEE_MAX:
        return None
    return annee


def _appliquer_formulaire(item: Item, formulaire: FormulaireItem) -> None:
    """Copie le formulaire sur le modèle. `fonds_id` traité séparément
    par les appelants (immuable à la modification).

    `annee` est dérivée automatiquement de `date` (EDTF) — l'utilisateur
    ne la saisit plus directement (input UI disabled, donc absent du
    POST). Règles :
    - date parse en année → sync `item.annee` (autorité)
    - date imprécise / vide + `formulaire.annee` fourni (CLI, API, import) → use it
    - date imprécise / vide + rien → conserve `item.annee` existant
      (préserve les imports legacy où seule `annee` était peuplée)
    """
    item.cote = formulaire.cote.strip()
    item.titre = formulaire.titre.strip()
    item.etat_catalogage = formulaire.etat_catalogage or EtatCatalogage.BROUILLON.value
    annee_derivee = annee_depuis_date_edtf(formulaire.date)
    if annee_derivee is not None:
        item.annee = annee_derivee
    elif formulaire.annee is not None:
        item.annee = formulaire.annee
    # sinon : on laisse item.annee tel quel (legacy preserved)
    item.numero_tri = formulaire.numero_tri
    item.metadonnees = formulaire.metadonnees or None
    for nom in _OPTIONNELS_NULLABLES:
        setattr(item, nom, chaine_ou_none(getattr(formulaire, nom)))


def formulaire_depuis_item(item: Item) -> FormulaireItem:
    """Pré-remplit un formulaire d'édition depuis un item ORM.

    `metadonnees` est défaut-é à dict vide pour ne jamais avoir None
    (le modèle accepte None mais le formulaire attend un dict)."""
    return FormulaireItem(
        cote=item.cote,
        titre=item.titre or "",
        fonds_id=item.fonds_id,
        description=item.description or "",
        notes_internes=item.notes_internes or "",
        type_coar=item.type_coar or "",
        langue=item.langue or "",
        date=item.date or "",
        annee=item.annee,
        numero=item.numero or "",
        numero_tri=item.numero_tri,
        etat_catalogage=item.etat_catalogage,
        metadonnees=dict(item.metadonnees) if item.metadonnees else {},
        doi_nakala=item.doi_nakala or "",
        doi_collection_nakala=item.doi_collection_nakala or "",
    )


def lire_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise ItemIntrouvable(item_id)
    return item


def lire_item_par_cote(db: Session, cote: str, *, fonds_id: int) -> Item:
    """Lecture par cote dans un fonds donné. La cote n'étant unique que
    par fonds, `fonds_id` est obligatoire."""
    item = db.scalar(select(Item).where(Item.cote == cote, Item.fonds_id == fonds_id))
    if item is None:
        raise ItemIntrouvable(f"cote={cote!r} dans le fonds {fonds_id}")
    return item


def collections_de_item(db: Session, item_id: int) -> list[Collection]:
    """Liste les collections (miroir + libres) où un item figure.

    Requête SQL fraîche plutôt que `item.collections` : la relation
    chargée peut être obsolète après des écritures directes sur la
    junction `item_collection`.
    """
    if db.get(Item, item_id) is None:
        raise ItemIntrouvable(item_id)
    return list(
        db.scalars(
            select(Collection)
            .join(ItemCollection, ItemCollection.collection_id == Collection.id)
            .where(ItemCollection.item_id == item_id)
            .order_by(Collection.titre)
        ).all()
    )


def lister_items_fonds(
    db: Session,
    fonds_id: int,
    *,
    etat: str | None = None,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
) -> Listage[ItemResume]:
    """Liste paginée des items d'un fonds, filtrée optionnellement par état."""
    return _lister_items(
        db,
        scope_filtre=Item.fonds_id == fonds_id,
        etat=etat,
        tri=tri,
        ordre=ordre,
        page=page,
        par_page=par_page,
    )


def lister_items_collection(
    db: Session,
    collection_id: int,
    *,
    etat: str | None = None,
    etats: list[str] | tuple[str, ...] | None = None,
    langues: list[str] | tuple[str, ...] | None = None,
    types_coar: list[str] | tuple[str, ...] | None = None,
    annee_de: int | None = None,
    annee_a: int | None = None,
    tri: str | None = None,
    ordre: Ordre = "asc",
    page: int = 1,
    par_page: int = 50,
) -> Listage[ItemResume]:
    """Liste paginée des items d'une collection (via la junction N-N)
    avec filtres multi-valeurs optionnels."""
    return _lister_items(
        db,
        scope_filtre=Item.id.in_(
            select(ItemCollection.item_id).where(
                ItemCollection.collection_id == collection_id
            )
        ),
        etat=etat,
        etats=etats,
        langues=langues,
        types_coar=types_coar,
        annee_de=annee_de,
        annee_a=annee_a,
        tri=tri,
        ordre=ordre,
        page=page,
        par_page=par_page,
    )


def _appliquer_filtres_items(
    stmt,
    *,
    etat: str | None = None,
    etats: list[str] | tuple[str, ...] | None = None,
    langues: list[str] | tuple[str, ...] | None = None,
    types_coar: list[str] | tuple[str, ...] | None = None,
    annee_de: int | None = None,
    annee_a: int | None = None,
) -> tuple[object, dict[str, object]]:
    """Applique les filtres optionnels à une requête (`base_stmt` ou
    `count_stmt`). Retourne `(stmt_filtré, filtres_appliqués)` où le
    second sert au `Listage` pour traçabilité.

    `etat` (singulier) est conservé pour rétro-compatibilité avec
    `lister_items_fonds` ; `etats` (pluriel) prend le pas s'il est
    fourni — éventuels états hors whitelist sont écartés
    silencieusement.
    """
    filtres: dict[str, object] = {}
    if etats:
        valides = [e for e in etats if e in _ETATS_VALIDES]
        if valides:
            stmt = stmt.where(Item.etat_catalogage.in_(valides))
            filtres["etats"] = list(valides)
    elif etat and etat in _ETATS_VALIDES:
        stmt = stmt.where(Item.etat_catalogage == etat)
        filtres["etat"] = etat
    if langues:
        stmt = stmt.where(Item.langue.in_(list(langues)))
        filtres["langues"] = list(langues)
    if types_coar:
        stmt = stmt.where(Item.type_coar.in_(list(types_coar)))
        filtres["types_coar"] = list(types_coar)
    if annee_de is not None:
        stmt = stmt.where(Item.annee >= annee_de)
        filtres["annee_de"] = annee_de
    if annee_a is not None:
        stmt = stmt.where(Item.annee <= annee_a)
        filtres["annee_a"] = annee_a
    return stmt, filtres


def _lister_items(
    db: Session,
    *,
    scope_filtre,
    etat: str | None,
    etats: list[str] | tuple[str, ...] | None = None,
    langues: list[str] | tuple[str, ...] | None = None,
    types_coar: list[str] | tuple[str, ...] | None = None,
    annee_de: int | None = None,
    annee_a: int | None = None,
    tri: str | None,
    ordre: Ordre,
    page: int,
    par_page: int,
) -> Listage[ItemResume]:
    base_stmt = (
        select(Item, Fonds.cote.label("fonds_cote"))
        .join(Fonds, Item.fonds_id == Fonds.id)
        .where(scope_filtre)
    )
    base_stmt, filtres = _appliquer_filtres_items(
        base_stmt,
        etat=etat,
        etats=etats,
        langues=langues,
        types_coar=types_coar,
        annee_de=annee_de,
        annee_a=annee_a,
    )

    mapping_tri = {
        "cote": Item.cote,
        "titre": Item.titre,
        "date": Item.date,
        "annee": Item.annee,
        "etat": Item.etat_catalogage,
        "modifie": Item.modifie_le,
    }
    stmt, tri_eff, ordre_eff = appliquer_tri(
        base_stmt, mapping_tri, tri, ordre, defaut=("cote", "asc")
    )

    count_stmt = select(func.count(Item.id)).where(scope_filtre)
    count_stmt, _ = _appliquer_filtres_items(
        count_stmt,
        etat=etat,
        etats=etats,
        langues=langues,
        types_coar=types_coar,
        annee_de=annee_de,
        annee_a=annee_a,
    )
    total = db.scalar(count_stmt) or 0

    page_eff = max(1, page)
    if par_page > 0:
        stmt = stmt.limit(par_page).offset((page_eff - 1) * par_page)

    rows = db.execute(stmt).all()
    nb_coll_par_item: dict[int, int] = {}
    nb_fich_par_item: dict[int, int] = {}
    if rows:
        ids = [r[0].id for r in rows]
        nb_coll_par_item = dict(
            db.execute(
                select(ItemCollection.item_id, func.count())
                .where(ItemCollection.item_id.in_(ids))
                .group_by(ItemCollection.item_id)
            ).all()
        )
        nb_fich_par_item = dict(
            db.execute(
                select(Fichier.item_id, func.count(Fichier.id))
                .where(Fichier.item_id.in_(ids))
                .group_by(Fichier.item_id)
            ).all()
        )

    items = [
        ItemResume(
            id=item.id,
            cote=item.cote,
            titre=item.titre,
            fonds_id=item.fonds_id,
            fonds_cote=fonds_cote,
            etat=item.etat_catalogage,
            date=item.date,
            annee=item.annee,
            type_coar=item.type_coar,
            nb_collections=nb_coll_par_item.get(item.id, 0),
            nb_fichiers=nb_fich_par_item.get(item.id, 0),
            modifie_le=item.modifie_le,
            modifie_par=item.modifie_par,
            description=item.description,
            langue=item.langue,
            doi_nakala=item.doi_nakala,
            doi_collection_nakala=item.doi_collection_nakala,
            metadonnees=item.metadonnees,
        )
        for item, fonds_cote in rows
    ]
    return Listage(
        items=items,
        tri=tri_eff,
        ordre=ordre_eff,
        page=page_eff,
        par_page=par_page,
        total=total,
        filtres=filtres,
    )


def creer_item(
    db: Session,
    formulaire: FormulaireItem,
    *,
    cree_par: str | None = None,
) -> Item:
    """Crée un item dans un fonds.

    L'item est automatiquement ajouté à la collection miroir du fonds
    (invariant 6). Si la miroir est introuvable (anomalie), lève
    `OperationItemInterdite`.

    Conflit de cote `(fonds_id, cote)` rattrapé via IntegrityError.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise ItemInvalide(erreurs)

    fonds = db.get(Fonds, formulaire.fonds_id)
    if fonds is None:
        raise ItemInvalide(
            {"fonds_id": f"Le fonds {formulaire.fonds_id} n'existe pas."}
        )

    # Fail fast : si le fonds n'a pas de miroir (anomalie), pas la peine
    # de tenter l'insert.
    miroir_id = db.scalar(
        select(Collection.id).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir_id is None:
        raise OperationItemInterdite(
            f"Le fonds {fonds.cote!r} (id={fonds.id}) n'a pas de "
            "collection miroir — anomalie d'intégrité."
        )

    item = Item(fonds_id=fonds.id, cree_par=cree_par)
    _appliquer_formulaire(item, formulaire)
    db.add(item)
    with garde_cote_unique(db, ItemInvalide, item.cote):
        db.flush()
        db.add(ItemCollection(item_id=item.id, collection_id=miroir_id))
        db.commit()
    db.refresh(item)
    return item


#: Cap dur sur le nombre d'items créés par appel à
#: :func:`creer_items_en_serie`. Garde-fou contre la création
#: accidentelle de 100 000 items qui saturerait la DB. Le besoin
#: réel sur archives (60-200 items par revue typique) est largement
#: en-dessous. Si un fonds plus gros nécessite +1000 items, faire
#: plusieurs appels ou passer par l'import tableur.
_CAP_SERIE_ITEMS: int = 1000


@dataclass(frozen=True)
class RapportSerieItems:
    """Rapport d'une création en série d'items.

    ``crees`` : items effectivement créés, dans l'ordre de génération.
    ``ignores`` : cotes qui existaient déjà et ont été sautées
    (uniquement si l'appelant a passé ``ignorer_existants=True``).
    """

    crees: tuple[Item, ...]
    ignores: tuple[str, ...]

    @property
    def nb_crees(self) -> int:
        return len(self.crees)

    @property
    def nb_ignores(self) -> int:
        return len(self.ignores)


def creer_items_en_serie(
    db: Session,
    *,
    fonds_id: int,
    pattern_cote: str,
    de_n: int,
    a_n: int,
    titre_template: str = "",
    collection_id: int | None = None,
    etat: str = "brouillon",
    type_coar: str | None = None,
    langue: str | None = None,
    ignorer_existants: bool = False,
    cree_par: str | None = None,
) -> RapportSerieItems:
    """Crée une série d'items dans un fonds, du numéro ``de_n`` au
    numéro ``a_n`` (inclus).

    Cas d'usage typique : préparer 60 fiches d'items d'une revue avant
    numérisation, pour pouvoir y rattacher les scans au fil.

    Paramètres :

    - ``pattern_cote`` : template Python `str.format` avec une
      variable ``{n}`` (ou ``{n:03d}`` pour zéro-padding). Ex :
      ``"PF-{:03d}"`` produit ``PF-001``, ``PF-002``, ...
    - ``de_n`` / ``a_n`` : bornes inclusives. ``de_n <= a_n``,
      plage ≤ :data:`_CAP_SERIE_ITEMS`.
    - ``titre_template`` : template optionnel pour le titre. Mêmes
      variables que pour la cote. ``""`` = titre vide (acceptable).
    - ``collection_id`` : collection cible (libre ou miroir). ``None``
      = la miroir du fonds. Doit appartenir au fonds (ou être une
      transversale).
    - ``etat`` / ``type_coar`` / ``langue`` : valeurs par défaut pour
      tous les items créés.
    - ``ignorer_existants`` : si ``True``, les cotes déjà présentes
      sont sautées silencieusement. Si ``False`` (défaut), un conflit
      lève :class:`ItemInvalide` avec la liste des cotes en conflit.

    Lève :

    - :class:`ItemInvalide` : pattern invalide, plage hors limites,
      conflit de cote sans ``ignorer_existants``, collection
      incompatible avec le fonds.
    - :class:`OperationItemInterdite` : fonds sans miroir (anomalie),
      collection_id introuvable.

    Transactionnel : tous les items sont créés en une seule
    transaction. Si l'insert échoue mid-way, rollback complet.
    """
    # ---- Validation des bornes ----
    erreurs: dict[str, str] = {}
    if de_n > a_n:
        erreurs["plage"] = (
            f"La borne inférieure ({de_n}) est supérieure à la borne "
            f"supérieure ({a_n})."
        )
    nb_demande = max(0, a_n - de_n + 1)
    if nb_demande > _CAP_SERIE_ITEMS:
        erreurs["plage"] = (
            f"Plage trop large : {nb_demande} items demandés, cap à "
            f"{_CAP_SERIE_ITEMS}. Faire plusieurs appels ou utiliser "
            f"l'import tableur pour un plus gros volume."
        )
    if nb_demande == 0:
        erreurs["plage"] = "Plage vide."

    # ---- Validation du pattern ----
    if not pattern_cote.strip():
        erreurs["pattern_cote"] = "Le pattern de cote est obligatoire."
    else:
        try:
            cote_test = pattern_cote.format(n=de_n)
            if not cote_test.strip():
                erreurs["pattern_cote"] = "Le pattern produit une cote vide."
        except (KeyError, IndexError, ValueError) as e:
            erreurs["pattern_cote"] = (
                f"Pattern invalide : {e}. Utilisez {{n}} ou {{n:03d}} comme variable."
            )

    # ---- Validation titre template (si fourni) ----
    if titre_template:
        try:
            titre_template.format(n=de_n)
        except (KeyError, IndexError, ValueError) as e:
            erreurs["titre_template"] = (
                f"Pattern titre invalide : {e}. Variables disponibles : "
                f"{{n}} (numéro courant)."
            )

    # ---- Validation état ----
    if etat not in _ETATS_VALIDES:
        erreurs["etat"] = (
            f"État invalide : {etat!r}. Valeurs autorisées : "
            f"{', '.join(sorted(_ETATS_VALIDES))}."
        )

    if erreurs:
        raise ItemInvalide(erreurs)

    # ---- Lookup fonds + miroir ----
    fonds = db.get(Fonds, fonds_id)
    if fonds is None:
        raise ItemInvalide({"fonds_id": f"Le fonds {fonds_id} n'existe pas."})

    miroir_id = db.scalar(
        select(Collection.id).where(
            Collection.fonds_id == fonds.id,
            Collection.type_collection == TypeCollection.MIROIR.value,
        )
    )
    if miroir_id is None:
        raise OperationItemInterdite(
            f"Le fonds {fonds.cote!r} (id={fonds.id}) n'a pas de "
            "collection miroir — anomalie d'intégrité."
        )

    # ---- Lookup collection cible ----
    cible_id = collection_id if collection_id is not None else miroir_id
    cible_collection = db.get(Collection, cible_id)
    if cible_collection is None:
        raise OperationItemInterdite(f"La collection {cible_id} n'existe pas.")
    # Une collection rattachée à un autre fonds est interdite. Une
    # transversale (fonds_id NULL) est OK — elle peut accueillir des
    # items de n'importe quel fonds.
    if cible_collection.fonds_id is not None and cible_collection.fonds_id != fonds.id:
        raise ItemInvalide(
            {
                "collection_id": (
                    f"La collection {cible_collection.cote!r} appartient au "
                    f"fonds {cible_collection.fonds_id}, pas au fonds "
                    f"{fonds.cote!r}."
                )
            }
        )

    # ---- Génération des cotes + détection des conflits ----
    cotes_demandees: list[str] = []
    titres: list[str] = []
    for k in range(de_n, a_n + 1):
        cotes_demandees.append(pattern_cote.format(n=k))
        titres.append(titre_template.format(n=k) if titre_template else "")

    # Doublons intra-série : un pattern sans `{n}` (ex `"PF-fixe"`)
    # produit la même cote pour tous les items. À détecter avant le
    # insert sinon SQLAlchemy lève un IntegrityError opaque mid-bulk.
    if len(set(cotes_demandees)) != len(cotes_demandees):
        # Identifie les cotes répétées pour le message d'erreur.
        from collections import Counter as _Counter

        compte = _Counter(cotes_demandees)
        doublons = sorted(c for c, n in compte.items() if n > 1)
        raise ItemInvalide(
            {
                "pattern_cote": (
                    f"Le pattern produit des cotes en doublon dans la série "
                    f"({len(doublons)} cote(s) répétée(s) : "
                    f"{', '.join(doublons[:5])}). Vérifier que le pattern "
                    f"contient bien la variable `{{n}}` (ex : `PF-{{n:03d}}`)."
                )
            }
        )

    cotes_existantes = set(
        db.scalars(
            select(Item.cote).where(
                Item.fonds_id == fonds.id,
                Item.cote.in_(cotes_demandees),
            )
        ).all()
    )

    if cotes_existantes and not ignorer_existants:
        # Liste tronquée si trop longue (>10) pour ne pas saturer l'erreur.
        exemples = sorted(cotes_existantes)[:10]
        suffixe = (
            f" (+ {len(cotes_existantes) - 10} autres)"
            if len(cotes_existantes) > 10
            else ""
        )
        raise ItemInvalide(
            {
                "cotes_en_conflit": (
                    f"{len(cotes_existantes)} cote(s) déjà présente(s) "
                    f"dans le fonds {fonds.cote!r} : "
                    f"{', '.join(exemples)}{suffixe}. Utiliser "
                    f"`ignorer_existants=True` pour les sauter."
                )
            }
        )

    # ---- Création en bulk ----
    items_a_creer: list[tuple[Item, str]] = []  # (item, cote_pour_log)
    ignores: list[str] = []
    for cote, titre in zip(cotes_demandees, titres):
        if cote in cotes_existantes:
            ignores.append(cote)
            continue
        item = Item(
            fonds_id=fonds.id,
            cote=cote,
            titre=titre or "",
            etat_catalogage=etat,
            type_coar=type_coar,
            langue=langue,
            cree_par=cree_par,
        )
        items_a_creer.append((item, cote))
        db.add(item)

    if not items_a_creer:
        # Tout était déjà existant — aucune création, mais on rend
        # le rapport pour signaler les ignorés.
        return RapportSerieItems(crees=(), ignores=tuple(ignores))

    db.flush()  # garantit les item.id pour la junction
    # Rattachement à la collection cible
    for item, _ in items_a_creer:
        db.add(ItemCollection(item_id=item.id, collection_id=cible_id))
        # Invariant 6 : si la cible n'est pas la miroir, ajouter
        # AUSSI à la miroir (un item est toujours dans sa miroir).
        if cible_id != miroir_id:
            db.add(ItemCollection(item_id=item.id, collection_id=miroir_id))
    db.commit()

    for item, _ in items_a_creer:
        db.refresh(item)

    return RapportSerieItems(
        crees=tuple(item for item, _ in items_a_creer),
        ignores=tuple(ignores),
    )


def modifier_item(
    db: Session,
    item_id: int,
    formulaire: FormulaireItem,
    *,
    modifie_par: str | None = None,
) -> Item:
    """Met à jour un item. `fonds_id` est immuable : tout changement
    lève `OperationItemInterdite`. Conflit de cote rattrapé via
    IntegrityError.
    """
    erreurs = _valider_formulaire(formulaire)
    if erreurs:
        raise ItemInvalide(erreurs)

    item = lire_item(db, item_id)
    if formulaire.fonds_id != item.fonds_id:
        raise OperationItemInterdite("Le fonds d'un item ne peut pas être modifié.")
    _appliquer_formulaire(item, formulaire)
    item.modifie_par = modifie_par
    item.modifie_le = datetime.now()
    verifier_et_incrementer_version(item, formulaire)

    with (
        garde_cote_unique(db, ItemInvalide, item.cote),
        convertir_stale_data(formulaire.version),
    ):
        db.commit()
    db.refresh(item)
    return item


def supprimer_item(
    db: Session, item_id: int, *, execute_par: str | None = None
) -> None:
    """Supprime un item ; ses fichiers, annotations et liaisons
    disparaissent en cascade. L'item est retiré de toutes ses
    collections (y compris la miroir).

    Journalisé dans `OperationEntite` (principe directeur n°4) dans la
    même transaction que la suppression.
    """
    item = lire_item(db, item_id)
    journaliser_suppression_item(db, item, execute_par=execute_par)
    db.delete(item)
    db.commit()
