# Bibliothèque de composants UI — archives-tool

Dix macros Jinja2 + Tailwind, posées dans `templates/components/`.
Chaque macro est conçue pour être appelée avec **un seul paramètre** :
soit un objet métier déjà préparé côté Python, soit un dict de contexte.

Aucun framework JS n'est introduit. HTMX reste l'outil pour les
interactions (tri, filtres, drag-drop) — le markup expose les
attributs `data-…` qu'il lui faut.

## Convention de nommage

| Token Tailwind            | Valeur                | Rôle                                    |
|---------------------------|-----------------------|-----------------------------------------|
| `border-tertiary`         | `rgba(0,0,0,0.08)`    | Cellules, séparateurs entre sections    |
| `border-secondary`        | `rgba(0,0,0,0.16)`    | Cartes, conteneurs de niveau 1          |
| `border-primary`          | `rgba(0,0,0,0.28)`    | Focus, bordures actives                 |
| `state-info`              | `#378ADD`             | Lien, point « vérifié »                 |
| `state-warn`              | `#BA7517`             | Point « à vérifier »                    |
| `state-ok`                | `#639922`             | Point « validé »                        |
| `state-err`               | `#E24B4A`             | Point « à corriger »                    |
| `font-sans`               | `system-ui`, …        | Texte courant                           |
| `font-mono`               | `SF Mono`, `Consolas` | Cote, DOI, URL, hash, ordre de fichier  |
| `font-tabular`            | `tabular-nums`        | Toutes les colonnes numériques          |

Densités :

- **Aérée** (16 px de padding vertical) — dashboard, bandeau collection.
- **Dense** (12 px) — tableaux d'items, tableau de fichiers, cartouche
  de métadonnées.

---

## 1. `badge_etat(etat, kind='item')`

Fichier : `components/badge_etat.html`.

```jinja
{% from 'components/badge_etat.html' import badge_etat %}

{# Dans une cellule de tableau d'items #}
{{ badge_etat(item.etat) }}

{# États fichier (3 valeurs) #}
{{ badge_etat(fichier.etat, kind='fichier') }}
```

Fond gris uniforme (`bg-gray-100`), point 6×6 px porteur de la
sémantique. Ne **jamais** colorer le fond.

États :

- item — `brouillon`, `a_verifier`, `verifie`, `valide`, `a_corriger`
- fichier — `actif`, `remplace`, `corbeille`

---

## 2. `avancement_compact(rep)` / `avancement_detaille(rep)`

Fichier : `components/avancement.html`.

```jinja
{% from 'components/avancement.html' import avancement_compact, avancement_detaille %}

{# Dashboard, dans la colonne « Avancement » d'un tableau #}
{{ avancement_compact(collection.repartition) }}

{# Page collection, sous le titre #}
{{ avancement_detaille(collection.repartition) }}
```

`rep` = `{brouillon, a_verifier, verifie, valide, a_corriger}` — les
clés manquantes sont traitées comme `0`. La variante détaillée ajoute
une légende avec carrés de 8 px et chiffres formatés français.

---

## 3. `cellule_modifie(par, depuis)`

Fichier : `components/cellule_modifie.html`.

```jinja
<td class="text-right">{{ cellule_modifie(item.modifie_par, item.modifie_depuis) }}</td>
```

Attendu : `par` est une chaîne (« Marie »), `depuis` une chaîne déjà
formatée (« il y a 2h », « hier », « 1 sem. »). Le formatage du temps
relatif est laissé au filtre `humanize` côté Python — il ne dépend pas
du fuseau horaire de la requête.

---

## 4. `phase_chantier(phase)`

Fichier : `components/phase_chantier.html`.

```jinja
<div>
  <span class="font-mono text-sm">{{ collection.cote }}</span>
  {{ phase_chantier(collection.phase) }}
</div>
```

Vocabulaire : `numérisation`, `catalogage`, `révision`,
`finalisation`, `archivée`, `en pause`. Si `phase` est falsy, rien
n'est rendu.

---

## 5. Cartouche de métadonnées

Fichier : `components/cartouche_metadonnees.html`. Plusieurs macros
exposées — l'utilisation typique est de composer manuellement les
sections depuis `pages/item.html` :

```jinja
{% from 'components/cartouche_metadonnees.html' import
   cartouche_wrapper, section, ligne,
   valeur_mono, valeur_doi, valeur_url,
   valeur_date_incertaine, valeur_non_renseigne,
   liste_auteurs, tags_sujets %}

{% call cartouche_wrapper() %}

  {% call section("Identification", info="DC qualifié") %}
    {% call ligne("Cote", field="cote") %}{{ valeur_mono(item.cote) }}{% endcall %}
    {% call ligne("Titre", field="titre") %}{{ item.titre }}{% endcall %}
    {% call ligne("Date", field="date") %}
      {% if item.date_incertaine %}
        {{ valeur_date_incertaine(item.date) }}
      {% else %}
        {{ item.date }}
      {% endif %}
    {% endcall %}
    {% call ligne("Auteurs", field="auteurs") %}{{ liste_auteurs(item.auteurs) }}{% endcall %}
    {% call ligne("Sujets", field="sujets") %}{{ tags_sujets(item.sujets) }}{% endcall %}
  {% endcall %}

  {% call section("Identifiants externes", info="Nakala") %}
    {% call ligne("DOI Nakala", field="doi_nakala") %}
      {% if item.doi_nakala %}{{ valeur_doi(item.doi_nakala_url, item.doi_nakala) }}
      {% else %}{{ valeur_non_renseigne() }}{% endif %}
    {% endcall %}
    {% call ligne("ARK", field="ark") %}{{ valeur_non_renseigne() }}{% endcall %}
  {% endcall %}

{% endcall %}
```

Hooks pour l'édition inline (v0.7) :

- `[data-edit-field="<key>"]` sur chaque `ligne(…)`
- `[data-value]` sur le conteneur de la valeur

---

## 6. `panneau_colonnes(ctx)`

Fichier : `components/panneau_colonnes.html`. Drawer 480 px.

```jinja
{% from 'components/panneau_colonnes.html' import panneau_colonnes %}

{{ panneau_colonnes({
  'collection_cote': collection.cote,
  'actives': [
    {'key':'cote',     'label':'Cote',     'note':'colonne dédiée'},
    {'key':'titre',    'label':'Titre',    'note':'colonne dédiée'},
    {'key':'etat',     'label':'État',     'note':'calculée'},
    …
  ],
  'available_dedicated': [
    {'key':'doi_nakala', 'label':'DOI Nakala'}, …
  ],
  'available_meta': [
    {'key':'fascicule',  'label':'Numéro de fascicule'}, …
  ],
}) }}
```

Hooks JS / HTMX :

- `[data-cols-search]` — input de filtrage
- `[data-cols-active]` — liste réordonnable (drag-and-drop)
- `[data-cols-available]`, `[data-cols-meta]` — listes plates
- `[data-action="reset|apply|cancel"]` — boutons
- `[data-col][data-col-key=…]` — chaque ligne de colonne
- `[data-handle]` — poignée de drag

---

## 7. `tableau_collections(ctx)`

Fichier : `components/tableau_collections.html`.

```jinja
{% from 'components/tableau_collections.html' import tableau_collections %}

{{ tableau_collections({
  'sort': request.args.get('sort', 'modifie'),
  'collections': collections,   # pré-formatées par la route
}) }}
```

Schéma `collections[*]` :

```python
{
  'cote': str, 'href': str, 'titre': str,
  'phase': str | None,
  'sous_collections': int,
  'nb_items': int, 'nb_fichiers': int,
  'repartition': {brouillon, a_verifier, verifie, valide, a_corriger},
  'modifie_par': str, 'modifie_depuis': str,
}
```

Tri HTMX : la route attache `data-sort-key` sur chaque `<th>`.

---

## 8. `tableau_items(ctx)`

Fichier : `components/tableau_items.html`. Tableau dense, colonnes
configurables (le panneau de colonnes pilote `ctx.colonnes`).

```jinja
{% from 'components/tableau_items.html' import tableau_items %}

{{ tableau_items({
  'colonnes': user_prefs.colonnes_items,
  'sort': request.args.get('sort', 'cote'),
  'items': items,
  'pagination': {
    'page': page, 'per_page': 50, 'total': total, 'pages': pages,
  },
  'compteur_filtres': filtres_label,        # 'aucun' | '3 actifs'
  'nb_colonnes_actives': user_prefs.colonnes_items|length,
}) }}
```

Schéma `items[*]` :

```python
{
  'cote': str, 'href': str, 'titre': str,
  'type_chaine': 'Œuvres · Périodiques · Bulletins savants',
  'type_label': 'Periodical issue',
  'date': '1924-01' | 's.d.' | 'vers 1923',
  'date_incertaine': bool,
  'etat': 'brouillon' | …,
  'nb_fichiers': int,
  'modifie_par': str, 'modifie_depuis': str,
  'meta': {custom_key: str, …},   # pour les colonnes métadonnées
}
```

Colonnes connues : `cote`, `titre`, `type`, `date`, `etat`,
`fichiers`, `modifie`. Toute autre clé est rendue depuis
`item.meta[key]`.

---

## 9. `bandeau_item(ctx)`

Fichier : `components/bandeau_item.html`.

```jinja
{% from 'components/bandeau_item.html' import bandeau_item %}

{{ bandeau_item({
  'breadcrumb': [
    {'label':'Tableau de bord', 'href': url_for('dashboard')},
    {'label':'Collections',     'href': url_for('collections')},
    {'label': parent.cote, 'href': url_for('collection', cote=parent.cote), 'mono': True},
  ],
  'item': {
    'cote': item.cote, 'titre': item.titre, 'etat': item.etat,
    'nb_fichiers': item.nb_fichiers,
    'phase': item.collection.phase,
    'modifie_par': item.modifie_par, 'modifie_depuis': item.modifie_depuis,
    'url_vue_fichiers': url_for('item_fichiers', cote=item.cote),
    'url_precedent':    url_for('item', cote=prev_cote),
    'url_suivant':      url_for('item', cote=next_cote),
  },
}) }}
```

---

## 10. `panneau_fichiers(ctx)`

Fichier : `components/panneau_fichiers.html`.

```jinja
{% from 'components/panneau_fichiers.html' import panneau_fichiers %}

{{ panneau_fichiers({
  'etat': user_prefs.panneau_fichiers_etat,    # 'collapsed' | 'pinned'
  'nb_fichiers': item.nb_fichiers,
  'fichiers': fichiers,
  'url_vue_fichiers': url_for('item_fichiers', cote=item.cote),
  'url_ajout':        url_for('item_ajout_fichiers', cote=item.cote),
}) }}
```

Schéma `fichiers[*]` :

```python
{
  'ordre': int, 'nom': str, 'type': 'page' | 'couverture' | 'supplément',
  'vignette_url': str | None,   # placeholder gris si None
  'courant': bool,              # mis en avant
  'href': str,
}
```

Côté JS (à implémenter par Claude Code) :

```js
const panel = document.querySelector('[data-panneau-fichiers]');
let timer;
panel.addEventListener('mouseenter', () => {
  if (panel.dataset.state === 'pinned') return;
  timer = setTimeout(() => panel.dataset.state = 'hover', 250);
});
panel.addEventListener('mouseleave', () => {
  clearTimeout(timer);
  if (panel.dataset.state === 'hover') panel.dataset.state = 'collapsed';
});
panel.querySelector('[data-action="expand"]')?.addEventListener('click',
  () => panel.dataset.state = 'pinned');
panel.querySelector('[data-action="toggle-pin"]')?.addEventListener('click',
  () => panel.dataset.state = panel.dataset.state === 'pinned' ? 'collapsed' : 'pinned');
```

L'état (`collapsed` / `pinned`) doit être persisté côté serveur dans
les préférences utilisateur ; `hover` est purement client.

---

## Templates de pages à mettre à jour

| Page                                 | Composants à intégrer                          |
|--------------------------------------|------------------------------------------------|
| `pages/dashboard.html`               | 7 (tableau collections), 2 (avancement compact) |
| `pages/collection.html`              | 9 (bandeau, adapté), 2 (avancement détaillé), 4 (phase) |
| `pages/item.html`                    | 9 (bandeau item), 5 (cartouche), 10 (panneau fichiers) |
| `partials/collection_items.html`     | 8 (tableau items), 1 (badge), 6 (panneau colonnes) |
| `partials/collection_fichiers.html`  | 8 (tableau, variante fichiers), 1 (badge fichier) |
| `partials/collection_sous.html`      | 7 (tableau collections, sans le wrapper d'en-tête)  |
