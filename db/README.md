# Base de connaissances du bot (Supabase)

Schéma `_jin_knowledge_base` dans le projet Supabase **JIN APPS**
(ref `afospuiklslsddxrseub`, région `eu-west-3`, Paris). Créé le 2026-09-23 par
`migrations/001_jin_knowledge_base.sql`, vérifié en réel (connexion, écriture, isolation).

## Tables

| Table | Rôle |
|---|---|
| `documents` | un enregistrement par fichier Drive (id, nom, lien, `modified_time`, empreinte, statut) |
| `chunks` | morceaux de texte + vecteur (`vector(1536)`, index HNSW cosinus) + colonne de recherche plein texte française |
| `sync_runs` | journal des passages du job de synchronisation |
| fonction `match_chunks(embedding, n, seuil)` | morceaux les plus proches, avec score de similarité |

## Accès

- Rôle dédié **`jin_kb_bot`** : ne voit que ce schéma (pas `_ask_jin_fr`, `_engage_jin_fr`, `_admin_jin_fr`),
  ni superutilisateur ni `bypassrls`. `anon`, `authenticated` et `service_role` n'ont aucun droit dessus.
- Mot de passe dans Secret Manager (`admin-jin-fr`) : **`jin-kb-db-password`**. Jamais dans le dépôt.
- Connexion via le pooler Supabase (IPv4, mode session) :
  `postgresql://jin_kb_bot.afospuiklslsddxrseub:<mot de passe>@aws-1-eu-west-3.pooler.supabase.com:5432/postgres`
- Avec un pilote Postgres en mode pooler, désactiver les requêtes préparées (ex. `prepare_threshold=None` avec psycopg 3).

## Appliquer ou rejouer une migration

La migration est rejouable. Avec la CLI Supabase connectée au compte, depuis un dossier lié à JIN APPS
(par exemple `admin.jin.fr`) :

```bash
supabase db query --linked --workdir <dossier lié> -f <chemin absolu>/db/migrations/001_jin_knowledge_base.sql
```

## Points de vigilance

- Les vecteurs sont de dimension 1536. Le modèle est enregistré avec chaque morceau (`embedding_model`)
  pour pouvoir changer de fournisseur : les vecteurs de deux modèles ne sont pas comparables, il faut
  alors tout recalculer.
- Avec `gemini-embedding-001` en dimension réduite (1536 sur 3072), les vecteurs doivent être
  **normalisés (L2)** avant stockage, sinon la distance cosinus est faussée.
