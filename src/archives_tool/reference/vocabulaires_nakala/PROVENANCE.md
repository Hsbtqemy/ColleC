# Vocabulaires Nakala — snapshots

Données de référence **snapshotées**, copiées telles quelles depuis le
dépôt `plugins-madbot` (MSHS Poitiers / FoReLLIS), plugin
`madbot_nakala_metadata`, à la révision `46b45a6` (2026-06-08).

Source amont :
`https://gitlab.huma-num.fr/mshs-poitiers/forellis/plugins-madbot.git`
`madbot_nakala_metadata/madbot_nakala_metadata/static/json/vocabularies/`

Ces fichiers reflètent les vocabulaires contrôlés acceptés par Nakala
(snapshot des endpoints `https://api.nakala.fr/vocabularies/*`), eux-mêmes
re-snapshotés côté plugin. **Aucune transformation** appliquée à la copie.

| Fichier | Contenu | Format |
|---|---|---|
| `coar_resource_types.json` | Types de dépôt acceptés par Nakala (~29 URIs COAR) | `[{uri, en, fr, es, definition}]` |
| `languages.json` | Langues ISO 639 (~8043) | `[{id, label}]` |
| `licenses.json` | Licences (liste SPDX, ~620) | `[{code, name, url}]` |

## Mises en garde

- **`coar_resource_types.json` = sous-ensemble Nakala**, pas tout le
  vocabulaire COAR. Un type COAR valide mais hors de cette liste sera
  rejeté/coercé au dépôt Nakala. C'est l'autorité pour le **chemin de
  dépôt**, pas pour le catalogage interne libre.
- **`licenses.json` ressemble à la liste SPDX complète**, pas
  nécessairement au sous-ensemble de licences accepté par Nakala. À
  confirmer avant de l'imposer comme vocabulaire contrôlé d'export.
- Pour rafraîchir : re-snapshoter depuis l'amont (le plugin a un
  `scripts/generate_schemas.py`), pas d'édition manuelle ici.

Voir [`docs/developpeurs/nakala-depot-future.md`](../../../../docs/developpeurs/nakala-depot-future.md)
pour le contexte (chantier dépôt/round-trip Nakala) et l'inventaire des
écarts entre les types COAR actuels de ColleC et le set Nakala.
