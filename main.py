from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="POC Affectation PostGIS V6 - Besoins")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

def get_db_connection():
    return psycopg2.connect(dbname="rectorat", user="postgres", password="admin", host="localhost")

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

class Affectation(BaseModel):
    prof_id: int
    heures: float

# --- NOUVEAU MODÈLE ---
class NouveauBesoin(BaseModel):
    uai: str
    discipline: str
    heures: float

@app.get("/api/referentiel")
def get_referentiel():
    return MAPPING_DISCIPLINES

@app.get("/api/etablissements")
def get_etablissements():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT uai, nom, type, degre, ST_Y(geom) as latitude, ST_X(geom) as longitude FROM etablissements")
    etablissements = cur.fetchall()
    cur.close()
    conn.close()
    return etablissements

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

@app.post("/api/affecter")
def affecter_professeur(affectation: Affectation):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE professeurs 
        SET heures_actuelles = heures_actuelles + %s 
        WHERE id = %s
    """, (affectation.heures, affectation.prof_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": f"Affectation réussie ! {affectation.heures}h ont été déduites du solde de l'enseignant."}

@app.get("/api/match")
def match_professeurs(lat: float, lng: float, matiere: str, heures_requises: float = 0, rayon_metres: int = 5000):
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

# --- NOUVELLES ROUTES : BESOINS ---
@app.get("/api/besoins")
def get_besoins():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT b.id, b.uai, e.nom as nom_etablissement, b.discipline, b.heures, TO_CHAR(b.date_declaration, 'DD/MM/YYYY') as date,
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
    cur.execute("INSERT INTO besoins (uai, discipline, heures) VALUES (%s, %s, %s)", (besoin.uai, besoin.discipline, besoin.heures))
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
    return {"message": "Besoin supprimé (pourvu)."}