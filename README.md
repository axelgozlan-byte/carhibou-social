# carhibou-social

File de publication Instagram de **carhibou.com**.

- `queue/<id>/post.json` + images JPEG = un post programmé (`publish_at` en heure de Paris).
- Toutes les 15 min, l'action « Publier sur Instagram » publie les posts arrivés à échéance
  via l'API officielle Instagram et écrit `published.json` (lien du post).
- En cas d'échec, `error.log` est écrit dans le dossier du post.

Secrets requis : `IG_TOKEN` (jeton Instagram), `GH_PAT` (pour prolonger le jeton chaque semaine).
