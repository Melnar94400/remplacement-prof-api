import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = FastAPI(title="POC Affectation PostGIS V8 - Édition Historique")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

def get_db_connection():
    return psycopg2.connect(
        host="aws-0-eu-west-1.pooler.supabase.com",
        port="6543",
        database="postgres",
        user="postgres.scacemkfeugwaugxprhh",
        password=os.getenv("SUPABASE_PASSWORD")
        sslmode="require"  # <--- AJOUTEZ CETTE LIGNE (avec la virgule au-dessus)
    )

MAPPING_DISCIPLINES = {
    "Physique-Chimie": ["Physique-Chimie", "Sciences Physiques (Pro)", "SPCL (Techno)", "Mesures Physiques"],
    "Mathématiques": ["Mathématiques", "Mathématiques-Sciences (Pro)", "SNT (Seconde)"],
    "SVT": ["SVT", "Biologie-Écologie", "ST2S - Biologie et physiopathologie"],
    "Génie Électrique": ["Électrotechnique", "Électronique", "Systèmes Numériques (SN)"],
    "Anglais": ["Anglais", "Anglais de spécialité (LLCE)", "DNL Anglais (Générique)"]
}

class Professeur(BaseModel):
    nom: str
    statut: str
    corps: str
    discipline: str
    adresse_libelle: str
    type_adresse: str
    latitude: float
    longitude: float
    quotite: float
    heures_actuelles: float
    telephone: str = ""
    email: str = ""

class NouveauBesoin(BaseModel):
    uai: str
    discipline: str
    heures: float
    date_debut: str
    date_fin: str

class AffectationRequest(BaseModel):
    prof_id: int
    besoin_id: int

class UpdateAffectation(BaseModel):
    heures: float
    date_debut: str
    date_fin: str

@app.get("/api/referentiel")
def get_referentiel():
    return MAPPING_DISCIPLINES

@app.get("/api/etablissements")
def get_etablissements():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT e.uai, e.nom, e.type, e.degre, ST_Y(e.geom) as latitude, ST_X(e.geom) as longitude,
               (SELECT COUNT(*) FROM besoins b WHERE b.uai = e.uai) as nb_besoins
        FROM etablissements e
        ORDER BY e.nom
    """)
    etabs = cur.fetchall()
    cur.close()
    conn.close()
    return etabs

@app.get("/api/professeurs")
def get_tous_professeurs():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, nom, statut, corps, discipline, type_adresse, rattachement as adresse,
               heures_max, heures_actuelles, (heures_max - heures_actuelles) as heures_restantes,
               telephone, email, ST_Y(geom) as latitude, ST_X(geom) as longitude
        FROM professeurs ORDER BY nom
    """)
    profs = cur.fetchall()
    cur.close()
    conn.close()
    return profs

@app.get("/api/professeurs/{prof_id}/historique")
def get_historique_professeur(prof_id: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT a.discipline, a.heures, TO_CHAR(a.date_debut, 'DD/MM/YYYY') as date_debut, TO_CHAR(a.date_fin, 'DD/MM/YYYY') as date_fin,
               e.nom as etablissement, e.type
        FROM affectations a
        JOIN etablissements e ON a.uai = e.uai
        WHERE a.prof_id = %s
        ORDER BY a.date_debut DESC
    """, (prof_id,))
    historique = cur.fetchall()
    cur.close()
    conn.close()
    return historique

@app.post("/api/professeurs")
def ajouter_professeur(prof: Professeur):
    base_heures = 15.0 if prof.corps == "Agrégé" else 18.0
    heures_max = base_heures * (prof.quotite / 100.0)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO professeurs (nom, statut, discipline, rattachement, type_adresse, corps, quotite, heures_max, heures_actuelles, telephone, email, disponible, geom)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """, (prof.nom, prof.statut, prof.discipline, prof.adresse_libelle, prof.type_adresse, prof.corps, prof.quotite, heures_max, prof.heures_actuelles, prof.telephone, prof.email, prof.longitude, prof.latitude))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Fiche enseignant créée avec succès !"}

@app.put("/api/professeurs/{prof_id}")
def modifier_professeur(prof_id: int, prof: Professeur):
    base_heures = 15.0 if prof.corps == "Agrégé" else 18.0
    heures_max = base_heures * (prof.quotite / 100.0)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE professeurs 
        SET nom=%s, statut=%s, discipline=%s, rattachement=%s, type_adresse=%s, corps=%s, quotite=%s, heures_max=%s, heures_actuelles=%s, telephone=%s, email=%s, geom=ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        WHERE id=%s
    """, (prof.nom, prof.statut, prof.discipline, prof.adresse_libelle, prof.type_adresse, prof.corps, prof.quotite, heures_max, prof.heures_actuelles, prof.telephone, prof.email, prof.longitude, prof.latitude, prof_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Fiche enseignant mise à jour !"}

@app.delete("/api/professeurs/{prof_id}")
def supprimer_professeur(prof_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM professeurs WHERE id = %s", (prof_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Enseignant supprimé de la base."}

@app.get("/api/besoins")
def get_besoins():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT b.id, b.uai, e.nom as nom_etablissement, b.discipline, b.heures, 
               TO_CHAR(b.date_debut, 'YYYY-MM-DD') as date_debut, TO_CHAR(b.date_fin, 'YYYY-MM-DD') as date_fin,
               ST_Y(e.geom) as latitude, ST_X(e.geom) as longitude
        FROM besoins b
        JOIN etablissements e ON b.uai = e.uai
        ORDER BY b.date_declaration DESC
    """)
    besoins = cur.fetchall()
    cur.close()
    conn.close()
    return besoins

@app.post("/api/besoins")
def ajouter_besoin(besoin: NouveauBesoin):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO besoins (uai, discipline, heures, date_debut, date_fin) 
        VALUES (%s, %s, %s, %s, %s)
    """, (besoin.uai, besoin.discipline, besoin.heures, besoin.date_debut, besoin.date_fin))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Besoin enregistré dans le tableau de bord !"}

@app.delete("/api/besoins/{besoin_id}")
def supprimer_besoin(besoin_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM besoins WHERE id = %s", (besoin_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Besoin supprimé (sans affectation)."}

@app.get("/api/match")
def match_professeurs(lat: float, lng: float, matiere: str, heures_requises: float = 0, rayon_metres: int = 10000):
    disciplines_compatibles = [d for d, mats in MAPPING_DISCIPLINES.items() if matiere in mats] or [matiere]
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, nom, statut, corps, discipline, rattachement as adresse, telephone, email,
               heures_max, heures_actuelles, (heures_max - heures_actuelles) as heures_restantes,
               ST_Y(geom) as lat, ST_X(geom) as lng
        FROM professeurs
        WHERE disponible = TRUE AND discipline = ANY(%s) 
          AND (heures_max - heures_actuelles) >= %s
          AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
        ORDER BY (heures_max - heures_actuelles) DESC
    """, (disciplines_compatibles, heures_requises, lng, lat, rayon_metres))
    profs = cur.fetchall()
    cur.close()
    conn.close()
    return profs

@app.post("/api/affecter")
def affecter_professeur(affectation: AffectationRequest):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT uai, discipline, heures, date_debut, date_fin FROM besoins WHERE id = %s", (affectation.besoin_id,))
    besoin = cur.fetchone()
    
    if not besoin:
        return {"error": "Besoin introuvable."}
        
    cur.execute("UPDATE professeurs SET heures_actuelles = heures_actuelles + %s WHERE id = %s", (besoin['heures'], affectation.prof_id))
    
    cur.execute("""
        INSERT INTO affectations (prof_id, uai, discipline, heures, date_debut, date_fin)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (affectation.prof_id, besoin['uai'], besoin['discipline'], besoin['heures'], besoin['date_debut'], besoin['date_fin']))
    
    cur.execute("DELETE FROM besoins WHERE id = %s", (affectation.besoin_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": f"Affectation validée et archivée dans l'historique !"}

# --- NOUVELLES ROUTES : GESTION DES AFFECTATIONS ---

@app.get("/api/affectations")
def get_toutes_affectations():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT a.id, a.prof_id, p.nom as nom_prof, a.uai, e.nom as nom_etablissement,
               a.discipline, a.heures, TO_CHAR(a.date_debut, 'YYYY-MM-DD') as date_debut,
               TO_CHAR(a.date_fin, 'YYYY-MM-DD') as date_fin
        FROM affectations a
        JOIN professeurs p ON a.prof_id = p.id
        JOIN etablissements e ON a.uai = e.uai
        ORDER BY a.date_creation DESC
    """)
    aff = cur.fetchall()
    cur.close()
    conn.close()
    return aff

@app.put("/api/affectations/{id}")
def modifier_affectation(id: int, aff: UpdateAffectation):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Récupérer l'ancienne affectation pour calculer la différence d'heures
    cur.execute("SELECT prof_id, heures FROM affectations WHERE id = %s", (id,))
    old_aff = cur.fetchone()
    if not old_aff:
        return {"error": "Affectation introuvable"}
        
    diff_heures = aff.heures - old_aff['heures']
    
    cur.execute("""
        UPDATE affectations 
        SET heures = %s, date_debut = %s, date_fin = %s 
        WHERE id = %s
    """, (aff.heures, aff.date_debut, aff.date_fin, id))
    
    # Réajustement intelligent des heures du professeur
    cur.execute("UPDATE professeurs SET heures_actuelles = heures_actuelles + %s WHERE id = %s", (diff_heures, old_aff['prof_id']))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Affectation modifiée avec succès"}

@app.delete("/api/affectations/{id}")
def supprimer_affectation(id: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT prof_id, heures FROM affectations WHERE id = %s", (id,))
    old_aff = cur.fetchone()
    
    if old_aff:
        # On rend les heures au prof avant de détruire l'affectation
        cur.execute("UPDATE professeurs SET heures_actuelles = heures_actuelles - %s WHERE id = %s", (old_aff['heures'], old_aff['prof_id']))
        cur.execute("DELETE FROM affectations WHERE id = %s", (id,))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Affectation annulée."}