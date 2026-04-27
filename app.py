from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import json
import os
import random
import uuid
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
import re

app = Flask(__name__)
app.secret_key = "gateau_secret_2024_xK9mP"

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "db.json")
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─── DB HELPERS ────────────────────────────────────────────────────────────────

def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_or_create_user_id():
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    return session["user_id"]


# ─── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    db = load_db()
    gateaux = db["gateaux"]
    
    # Top 2 les plus likés
    top2 = sorted(gateaux, key=lambda x: x["likes"], reverse=True)[:2]
    
    # Slider: mélange aléatoire pour équité de visibilité
    slider_pool = [g for g in gateaux if g["id"] not in [t["id"] for t in top2]]
    random.shuffle(slider_pool)
    slider = slider_pool[:6]
    
    return render_template("index.html", top2=top2, slider=slider)


@app.route("/catalogue")
def catalogue():
    db = load_db()
    gateaux = db["gateaux"]
    categories = db["categories"]
    cat_filtre = request.args.get("categorie", "Tous")
    user_id = get_or_create_user_id()

    if cat_filtre != "Tous":
        filtres = [g for g in gateaux if g["categorie"] == cat_filtre]
    else:
        filtres = list(gateaux)

    # Suggestion aléatoire: mélange pour équité
    random.shuffle(filtres)

    return render_template(
        "catalogue.html",
        gateaux=filtres,
        categories=categories,
        cat_active=cat_filtre,
        user_id=user_id
    )


@app.route("/gateau/<int:gateau_id>")
def detail_gateau(gateau_id):
    db = load_db()
    gateaux = db["gateaux"]
    gateau = next((g for g in db["gateaux"] if g["id"] == gateau_id), None)
    if not gateau:
        return redirect(url_for("catalogue"))
    # On prépare le corpus pour l'IA
    corpus = [g.get("description", "") for g in gateaux]
    idx = gateaux.index(gateau)
        
        # On force la génération
    gateau["tags_ia"] = ia_engine.generer_automatiquement(corpus, idx)
        
        # --- TEST DE DEBUG DANS TA CONSOLE ---
    print(f"DEBUG IA -> Gâteau: {gateau['nom']} | Tags: {gateau['tags_ia']}")
    # Incrémenter vues
    gateau["vues"] = gateau.get("vues", 0) + 1
    save_db(db)
    
    user_id = get_or_create_user_id()
    user_liked = user_id in gateau.get("user_likes", [])
    
    # Suggestions: 3 gâteaux aléatoires de la même catégorie
    suggestions = [g for g in db["gateaux"] if g["id"] != gateau_id and g["categorie"] == gateau["categorie"]]
    if len(suggestions) < 3:
        suggestions += [g for g in db["gateaux"] if g["id"] != gateau_id and g not in suggestions]
    random.shuffle(suggestions)
    suggestions = suggestions[:3]
    
    return render_template("detail.html", gateau=gateau, user_liked=user_liked, suggestions=suggestions, user_id=user_id)
@app.route("/api/like/<int:gateau_id>", methods=["POST"])
def toggle_like(gateau_id):
    db = load_db()
    gateau = next((g for g in db["gateaux"] if g["id"] == gateau_id), None)
    if not gateau:
        return jsonify({"error": "Introuvable"}), 404
    
    # MODE TEST MULTILIKE : on ajoute +1 à chaque fois
    if "likes" not in gateau:
        gateau["likes"] = 0
    
    gateau["likes"] += 1
    
    # On peut quand même garder l'ID pour la forme, mais on ne bloque plus
    if "user_likes" not in gateau:
        gateau["user_likes"] = []
    user_id = get_or_create_user_id()
    gateau["user_likes"].append(user_id) 
    
    save_db(db)
    # On renvoie toujours liked: True pour que le cœur reste rouge
    return jsonify({"likes": gateau["likes"], "liked": True})

@app.route("/api/vue/<int:gateau_id>", methods=["POST"])
def increment_vue(gateau_id):
    db = load_db()
    gateau = next((g for g in db["gateaux"] if g["id"] == gateau_id), None)
    if not gateau:
        return jsonify({"error": "Introuvable"}), 404
    gateau["vues"] = gateau.get("vues", 0) + 1
    save_db(db)
    return jsonify({"vues": gateau["vues"]})


# ─── CRUD ADMIN ────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    db = load_db()
    gateaux = sorted(db["gateaux"], key=lambda x: x["id"], reverse=True)
    return render_template("admin.html", gateaux=gateaux, categories=db["categories"])


@app.route("/admin/ajouter", methods=["GET", "POST"])
def ajouter_gateau():
    db = load_db()
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        description = request.form.get("description", "").strip()
        categorie = request.form.get("categorie", "").strip()
        
        if not nom or not description or not categorie:
            flash("Tous les champs sont obligatoires.", "error")
            return redirect(url_for("ajouter_gateau"))
        
        image_nom = "default.jpg"
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit(".", 1)[1].lower()
                image_nom = f"gateau_{db['next_id']}.{ext}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], image_nom))
        
        nouveau = {
            "id": db["next_id"],
            "nom": nom,
            "description": description,
            "categorie": categorie,
            "image": image_nom,
            "likes": 0,
            "vues": 0,
            "user_likes": []
        }
        db["gateaux"].append(nouveau)
        db["next_id"] += 1
        save_db(db)
        flash(f"🎂 '{nom}' ajouté avec succès!", "success")
        return redirect(url_for("admin"))
    
    return render_template("form_gateau.html", gateau=None, categories=db["categories"], action="Ajouter")


@app.route("/admin/modifier/<int:gateau_id>", methods=["GET", "POST"])
def modifier_gateau(gateau_id):
    db = load_db()
    gateau = next((g for g in db["gateaux"] if g["id"] == gateau_id), None)
    if not gateau:
        return redirect(url_for("admin"))
    
    if request.method == "POST":
        gateau["nom"] = request.form.get("nom", gateau["nom"]).strip()
        gateau["description"] = request.form.get("description", gateau["description"]).strip()
        gateau["categorie"] = request.form.get("categorie", gateau["categorie"]).strip()
        
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit(".", 1)[1].lower()
                image_nom = f"gateau_{gateau_id}.{ext}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], image_nom))
                gateau["image"] = image_nom
        
        save_db(db)
        flash(f"✏️ '{gateau['nom']}' modifié avec succès!", "success")
        return redirect(url_for("admin"))
    
    return render_template("form_gateau.html", gateau=gateau, categories=db["categories"], action="Modifier")


@app.route("/admin/supprimer/<int:gateau_id>", methods=["POST"])
def supprimer_gateau(gateau_id):
    db = load_db()
    gateau = next((g for g in db["gateaux"] if g["id"] == gateau_id), None)
    if gateau:
        db["gateaux"] = [g for g in db["gateaux"] if g["id"] != gateau_id]
        save_db(db)
        flash(f"🗑️ Gâteau supprimé.", "info")
    return redirect(url_for("admin"))
# tags
class IAContentAnalyzer:
    def __init__(self):
        # On simplifie le vectorizer pour éviter les erreurs de "vocabulaire vide"
        self.vectorizer = TfidfVectorizer(stop_words='french', min_df=1)

    def generer_automatiquement(self, corpus, index_cible):
        # On récupère la description actuelle
        texte = corpus[index_cible]
        
        # SÉCURITÉ : Si la description est trop courte, on n'essaie même pas Scikit-Learn
        if len(texte.split()) < 3:
            return ["Sucré", "Délicieux"]

        try:
            # Calcul TF-IDF
            matrix = self.vectorizer.fit_transform(corpus)
            mots = self.vectorizer.get_feature_names_out()
            scores = matrix.toarray()[index_cible]
            
            indices = scores.argsort()[-3:][::-1]
            tags = [mots[i] for i in indices if scores[i] > 0]
            
            if tags:
                return tags
        except Exception as e:
            # On affiche l'erreur dans le terminal pour que tu puisses la voir !
            print(f"ERREUR IA TECHNIQUE : {e}")
        
        # SI ON ARRIVE ICI : L'IA a échoué, on fait l'extraction manuelle simple
        # On prend les mots de plus de 5 lettres
        mots_manuels = re.findall(r'\b\w{5,}\b', texte.lower())
        # On enlève les mots communs qui ne sont pas des saveurs
        filtre = ['cette', 'votre', 'avec', 'sans', 'dans', 'pour', 'lequel']
        tags_manuels = [m for m in mots_manuels if m not in filtre]
        
        return tags_manuels[:8] if tags_manuels else ["Gourmandise"]

ia_engine = IAContentAnalyzer()
# class IAContentAnalyzer:
#     def __init__(self):
#         self.vectorizer = TfidfVectorizer(stop_words='french', min_df=1)

#     def generer_automatiquement(self, corpus, index_cible):
#         try:
#             # 1. Tentative avec Scikit-Learn
#             matrix = self.vectorizer.fit_transform(corpus)
#             mots = self.vectorizer.get_feature_names_out()
#             scores = matrix.toarray()[index_cible]
            
#             indices = scores.argsort()[-3:][::-1]
#             tags = [mots[i] for i in indices if scores[i] > 0]
            
#             # 2. SÉCURITÉ : Si Scikit-Learn ne donne rien (liste vide)
#             if not tags:
#                 # On prend les mots de la description de plus de 4 lettres
#                 phrase = corpus[index_cible].lower()
#                 # Nettoyage rapide
#                 mots_bruts = re.findall(r'\b\w{5,}\b', phrase) 
#                 # On retire les mots trop communs manuellement
#                 filtre = ['cette', 'votre', 'leurs', 'assez', 'était', 'frais', 'soleil']
#                 tags = [m for m in mots_bruts if m not in filtre][:3]
            
#             return tags
#         except:
#             # 3. DERNIER RECOURS : Mots par défaut
#             return ["Pâtisserie", "Artisanal", "Gourmand"]

# ia_engine = IAContentAnalyzer()
@app.route("/api/top2")
def api_top2():
    db = load_db()
    top2 = sorted(db["gateaux"], key=lambda x: x["likes"], reverse=True)[:2]
    return jsonify(top2)


if __name__ == "__main__":
    app.run(debug=True, port=5000)