#!/usr/bin/env python3
"""Publie sur Instagram les posts de queue/ dont l'heure est passée.

Chaque post = un dossier queue/<id>/ contenant :
  post.json  {"publish_at": "2026-11-03T12:45:00+01:00",
              "type": "carousel" | "image" | "story",
              "images": ["1.jpg", "2.jpg"],
              "caption": "..."}
  les images JPEG listées.
Une fois publié, le script écrit published.json dans le dossier.

Variables d'environnement :
  IG_TOKEN    jeton utilisateur système Meta (connexion unifiée, n'expire pas)
  IG_USER_ID  identifiant du compte Instagram professionnel (sinon détecté automatiquement)
  REPO        owner/repo (fourni par GitHub Actions)
  BRANCH      branche servant les images (défaut: main)
  DRY_RUN=1   n'appelle pas l'API, affiche seulement ce qui partirait
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("IG_API", "https://graph.facebook.com/v21.0")
ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
TOKEN = os.environ.get("IG_TOKEN", "")
REPO = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY", "")
BRANCH = os.environ.get("BRANCH", "main")
DRY = os.environ.get("DRY_RUN") == "1"


def call(method, path, **params):
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if method == "GET":
        req = urllib.request.Request(url + ("?" + data.decode() if params else ""), headers=headers)
    else:
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from None


def wait_ready(container_id, tries=20):
    for _ in range(tries):
        st = call("GET", container_id, fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"conteneur {container_id} en échec: {st}")
        time.sleep(5)
    raise RuntimeError(f"conteneur {container_id} pas prêt à temps")


def find_ig_id():
    """Cherche le compte Instagram relié au jeton (via les Pages ou le portefeuille)."""
    try:
        pages = call("GET", "me/accounts", fields="instagram_business_account").get("data", [])
        for p in pages:
            if p.get("instagram_business_account"):
                return p["instagram_business_account"]["id"]
    except RuntimeError:
        pass
    me = call("GET", "me", fields="id")
    for edge in ("instagram_accounts", "owned_instagram_accounts"):
        try:
            data = call("GET", f"{me['id']}/{edge}", fields="id,username").get("data", [])
            if data:
                return data[0]["id"]
        except RuntimeError:
            continue
    raise RuntimeError("Compte Instagram introuvable : renseigner la variable IG_USER_ID")


def image_url(post_dir, name):
    rel = f"queue/{post_dir.name}/{name}"
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{urllib.parse.quote(rel)}"


def publish(post_dir, post, ig_id):
    kind = post.get("type", "carousel")
    imgs = post["images"]
    caption = post.get("caption", "")
    if kind == "carousel":
        children = []
        for name in imgs:
            c = call("POST", f"{ig_id}/media", image_url=image_url(post_dir, name), is_carousel_item="true")["id"]
            wait_ready(c)
            children.append(c)
        cid = call("POST", f"{ig_id}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    elif kind == "story":
        cid = call("POST", f"{ig_id}/media", media_type="STORIES", image_url=image_url(post_dir, imgs[0]))["id"]
    else:
        cid = call("POST", f"{ig_id}/media", image_url=image_url(post_dir, imgs[0]), caption=caption)["id"]
    wait_ready(cid)
    media_id = call("POST", f"{ig_id}/media_publish", creation_id=cid)["id"]
    link = call("GET", media_id, fields="permalink").get("permalink", "")
    return media_id, link


def check():
    """Vérifie le jeton et le compte, sans rien publier."""
    print(f"::notice::Type de jeton : {TOKEN[:4]}… ({len(TOKEN)} car.), API {API}")
    for path, f in (("me", "id,name"), ("me/accounts", "id,name,instagram_business_account")):
        try:
            print(f"::notice::{path} -> {json.dumps(call('GET', path, fields=f))[:600]}")
        except Exception as e:
            print(f"::notice::{path} -> erreur {str(e)[:600]}")
    ig_id = os.environ.get("IG_USER_ID") or find_ig_id()
    info = call("GET", ig_id, fields="username,media_count")
    lim = call("GET", f"{ig_id}/content_publishing_limit", fields="quota_usage,config")
    print(f"::notice::OK : @{info.get('username')} (id {ig_id}), {info.get('media_count')} publications, quota {lim}")
    return 0


def main():
    if os.environ.get("CHECK") == "1":
        return check()
    now = datetime.now(timezone.utc)
    due = []
    for d in sorted(p for p in QUEUE.iterdir() if p.is_dir()):
        if (d / "published.json").exists() or not (d / "post.json").exists():
            continue
        post = json.loads((d / "post.json").read_text())
        when = datetime.fromisoformat(post["publish_at"])
        if when <= now:
            due.append((d, post))
    if not due:
        print("Rien à publier.")
        return 0
    if DRY:
        for d, post in due:
            print(f"[DRY] {d.name}: {post['type']} {post['images']}")
        return 0
    if not TOKEN:
        print("IG_TOKEN manquant", file=sys.stderr)
        return 1
    ig_id = os.environ.get("IG_USER_ID") or find_ig_id()
    info = call("GET", ig_id, fields="username")
    print(f"Compte: @{info.get('username')}")
    failed = 0
    for d, post in due:
        try:
            media_id, link = publish(d, post, ig_id)
            (d / "published.json").write_text(json.dumps(
                {"media_id": media_id, "permalink": link,
                 "published_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
            print(f"Publié {d.name}: {link}")
        except Exception as e:  # on continue avec les autres posts
            failed += 1
            (d / "error.log").write_text(f"{datetime.now(timezone.utc).isoformat()} {e}\n")
            print(f"::error::ÉCHEC {d.name}: {str(e)[:800]}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        msg = str(e).replace(TOKEN, "[jeton]") if TOKEN else str(e)
        print(f"::error::{msg[:900]}")
        sys.exit(1)
