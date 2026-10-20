import os
import csv
import io
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from dotenv import load_dotenv
import urllib.request
import json
import base64
from datetime import datetime, timedelta

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    return psycopg2.connect(
        host="aws-0-eu-west-1.pooler.supabase.com",
        port="6543",
        database="postgres",
        user="postgres.scacemkfeugwaugxprhh",
        password=os.getenv("SUPABASE_PASSWORD"),
        sslmode="require"
    )

def init_migration():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS matieres_etablissement (
                id SERIAL PRIMARY KEY,
                uai VARCHAR(8) REFERENCES etablissements(uai) ON DELETE CASCADE,
                nom VARCHAR(100) NOT NULL,
                UNIQUE(uai, nom)
            );
            ALTER TABLE professeurs_etablissement ADD COLUMN IF NOT EXISTS matiere_ecole VARCHAR(100) DEFAULT '';
            ALTER TABLE besoins ALTER COLUMN matiere_id DROP NOT NULL;
            ALTER TABLE besoins ALTER COLUMN prof_absent_id DROP NOT NULL;
            ALTER TABLE besoins ADD COLUMN IF NOT EXISTS matiere_declaree VARCHAR(150) DEFAULT '';
            ALTER TABLE affectations ADD COLUMN IF NOT EXISTS matiere_nom VARCHAR(150) DEFAULT '';
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Erreur migration :", e)

init_migration()

# --- MODÈLES DE DONNÉES ---
class LoginEcole(BaseModel):
    uai: str
    mot_de_passe: str

class ConcoursCreate(BaseModel):
    type_concours: str
    intitule: str
    heures_statutaires: float

class MatiereCreate(BaseModel):
    nom: str

class MatiereEcoleUpdate(BaseModel):
    nom: str

class LiaisonCreate(BaseModel):
    concours_id: int
    matiere_id: int

class PosteEtabCreate(BaseModel):
    matiere_ecole: str
    heures_poste: float = 18.0

class CSVImport(BaseModel):
    csv_text: str

class RemplacantCreate(BaseModel):
    nom: str
    statut: str
    concours_id: int
    adresse_libelle: str
    type_adresse: str
    latitude: float
    longitude: float
    quotite: float = 100.0
    heures_actuelles: float = 0.0
    telephone: Optional[str] = ""
    email: Optional[str] = ""

class BesoinCreate(BaseModel):
    uai: str
    prof_absent_id: Optional[int] = None
    matiere_declaree: str
    heures: float
    date_debut: str
    date_fin: str
    motif: Optional[str] = "Congé maladie"

class ResoudreMatiereRequest(BaseModel):
    mode: str  # "associer" ou "creer"
    matiere_id: Optional[int] = None
    corriger_ecole: Optional[bool] = True
    nouveau_nom: Optional[str] = ""
    concours_ids: Optional[List[int]] = []

class AffectationRequest(BaseModel):
    remplacant_id: int
    besoin_id: int

class AffectationUpdate(BaseModel):
    heures: float
    date_debut: str
    date_fin: str

# --- 1. RÉFÉRENTIEL ÉVOLUTIF (CONCOURS & MATIÈRES OFFICIELLES) ---
@app.get("/api/referentiel")
def get_referentiel():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT id, type_concours, intitule, float8(heures_statutaires) FROM concours ORDER BY intitule;")
    concours = [{"id": r[0], "type": r[1], "intitule": r[2], "heures": r[3]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, nom FROM matieres ORDER BY nom;")
    matieres = [{"id": r[0], "nom": r[1]} for r in cur.fetchall()]
    
    cur.execute("""
        SELECT cm.concours_id, cm.matiere_id, c.intitule, m.nom 
        FROM concours_matieres cm
        JOIN concours c ON cm.concours_id = c.id
        JOIN matieres m ON cm.matiere_id = m.id
        ORDER BY c.intitule, m.nom;
    """)
    liaisons = [{"concours_id": r[0], "matiere_id": r[1], "concours": r[2], "matiere": r[3]} for r in cur.fetchall()]
    
    cur.close()
    conn.close()
    return {"concours": concours, "matieres": matieres, "liaisons": liaisons}

@app.post("/api/referentiel/concours")
def add_concours(c: ConcoursCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO concours (type_concours, intitule, heures_statutaires) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
        (c.type_concours, c.intitule, c.heures_statutaires)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.post("/api/referentiel/matieres")
def add_matiere(m: MatiereCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO matieres (nom) VALUES (%s) ON CONFLICT DO NOTHING;", (m.nom.strip(),))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.post("/api/referentiel/liaisons")
def add_liaison(l: LiaisonCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO concours_matieres (concours_id, matiere_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
        (l.concours_id, l.matiere_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/referentiel/liaisons/{concours_id}/{matiere_id}")
def delete_liaison(concours_id: int, matiere_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM concours_matieres WHERE concours_id = %s AND matiere_id = %s;", (concours_id, matiere_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

# --- 2. ÉTABLISSEMENTS, MATIÈRES LOCALES & DOTATIONS HORAIRES ---
@app.get("/api/etablissements")
def get_etablissements():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.uai, e.nom, e.type, e.degre, ST_Y(e.geom), ST_X(e.geom),
               (SELECT COUNT(*) FROM professeurs_etablissement pe WHERE pe.uai = e.uai) as nb_postes,
               (SELECT COALESCE(SUM(float8(pe.heures_poste)), 0) FROM professeurs_etablissement pe WHERE pe.uai = e.uai) as total_heures,
               (SELECT COUNT(*) FROM besoins b WHERE b.uai = e.uai) as nb_besoins
        FROM etablissements e
        ORDER BY e.nom;
    """)
    res = [{
        "uai": r[0], "nom": r[1], "type": r[2], "degre": r[3],
        "latitude": r[4], "longitude": r[5],
        "nb_postes": r[6], "total_heures": r[7], "nb_besoins": r[8]
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/login/ecole")
def login_ecole(creds: LoginEcole):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT uai, nom, type, degre FROM etablissements WHERE uai = %s AND mot_de_passe = %s;", (creds.uai, creds.mot_de_passe))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    return {"uai": row[0], "nom": row[1], "type": row[2], "degre": row[3]}

@app.get("/api/ecoles/{uai}/matieres")
def get_matieres_ecole(uai: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM matieres_etablissement WHERE uai = %s;", (uai,))
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO matieres_etablissement (uai, nom)
            SELECT %s, nom FROM matieres
            ON CONFLICT DO NOTHING;
        """, (uai,))
        conn.commit()
        
    cur.execute("SELECT id, nom FROM matieres_etablissement WHERE uai = %s ORDER BY nom;", (uai,))
    res = [{"id": r[0], "nom": r[1]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/ecoles/{uai}/matieres")
def add_matiere_ecole(uai: str, m: MatiereCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO matieres_etablissement (uai, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (uai, m.nom.strip()))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.put("/api/ecoles/{uai}/matieres/{mat_id}")
def update_matiere_ecole(uai: str, mat_id: int, m: MatiereEcoleUpdate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT nom FROM matieres_etablissement WHERE id = %s AND uai = %s;", (mat_id, uai))
    old = cur.fetchone()
    if old:
        nouveau = m.nom.strip()
        cur.execute("UPDATE matieres_etablissement SET nom = %s WHERE id = %s;", (nouveau, mat_id))
        cur.execute("UPDATE professeurs_etablissement SET matiere_ecole = %s WHERE uai = %s AND matiere_ecole = %s;", (nouveau, uai, old[0]))
        conn.commit()
    cur.close()
    conn.close()
    return {"status": "updated"}

@app.delete("/api/ecoles/{uai}/matieres/{mat_id}")
def delete_matiere_ecole(uai: str, mat_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM matieres_etablissement WHERE id = %s AND uai = %s;", (mat_id, uai))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

@app.get("/api/ecoles/{uai}/professeurs")
def get_postes_ecole(uai: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT pe.id,
               COALESCE(NULLIF(pe.matiere_ecole, ''), c.intitule, 'Non définie') as matiere_affichee,
               float8(pe.heures_poste)
        FROM professeurs_etablissement pe
        LEFT JOIN concours c ON pe.concours_id = c.id
        WHERE pe.uai = %s
        ORDER BY matiere_affichee, pe.id;
    """, (uai,))
    res = [{"id": r[0], "matiere_ecole": r[1], "heures_poste": r[2]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/ecoles/{uai}/professeurs")
def add_poste_ecole(uai: str, p: PosteEtabCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    matiere = p.matiere_ecole.strip()

    cur.execute(
        "INSERT INTO professeurs_etablissement (uai, nom, matiere_ecole, heures_poste) VALUES (%s, 'Poste', %s, %s);",
        (uai, matiere, p.heures_poste)
    )
    cur.execute("INSERT INTO matieres_etablissement (uai, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (uai, matiere))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.post("/api/ecoles/{uai}/professeurs/import")
def import_postes_ecole(uai: str, data: CSVImport):
    conn = get_db_connection()
    cur = conn.cursor()
    f = io.StringIO(data.csv_text.strip())
    reader = csv.reader(f, delimiter=';')
    ajoutes = 0
    for row in reader:
        if len(row) < 2:
            continue
        first_col = row[0].strip().lower()
        if first_col in ['matiere', 'matière', 'poste', 'nom']:
            continue
            
        if len(row) == 2:
            matiere_ecole = row[0].strip()
            heures = float(row[1].replace(',', '.')) if row[1].strip() else 18.0
        else:
            matiere_ecole = row[1].strip()
            heures = float(row[2].replace(',', '.')) if row[2].strip() else 18.0

        cur.execute(
            "INSERT INTO professeurs_etablissement (uai, nom, matiere_ecole, heures_poste) VALUES (%s, 'Poste', %s, %s);",
            (uai, matiere_ecole, heures)
        )
        cur.execute("INSERT INTO matieres_etablissement (uai, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (uai, matiere_ecole))
        ajoutes += 1
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "ajoutes": ajoutes}

@app.delete("/api/ecoles/professeurs/{poste_id}")
def delete_poste_ecole(poste_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM professeurs_etablissement WHERE id = %s;", (poste_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

# --- 3. BESOINS, DÉTECTION AUTO & QUALIFICATION DE MATIÈRE PAR LE RECTORAT ---
@app.get("/api/besoins")
def get_besoins():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, b.uai, e.nom,
               b.matiere_id, m.nom, COALESCE(NULLIF(b.matiere_declaree, ''), m.nom, 'Matière non spécifiée'),
               float8(b.heures), b.date_debut, b.date_fin, COALESCE(b.motif, 'Absence'),
               b.vu_rectorat, ST_Y(e.geom), ST_X(e.geom)
        FROM besoins b
        JOIN etablissements e ON b.uai = e.uai
        LEFT JOIN matieres m ON b.matiere_id = m.id
        ORDER BY b.vu_rectorat ASC, b.date_declaration DESC;
    """)
    res = [{
        "id": r[0], "uai": r[1], "nom_etablissement": r[2],
        "matiere_id": r[3], "matiere_officielle": r[4] or "",
        "matiere_declaree": r[5] or "",
        "matiere": r[4] if r[4] else (r[5] or ""),
        "reconnue": r[3] is not None,
        "heures": r[6], "date_debut": str(r[7]), "date_fin": str(r[8]),
        "motif": r[9], "vu_rectorat": r[10], "latitude": r[11], "longitude": r[12]
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/besoins")
def creer_besoin(b: BesoinCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    mat_saisie = b.matiere_declaree.strip()
    
    cur.execute("SELECT id, nom FROM matieres WHERE LOWER(TRIM(nom)) = LOWER(%s) LIMIT 1;", (mat_saisie,))
    match = cur.fetchone()
    matiere_id = match[0] if match else None
    mat_label = match[1] if match else mat_saisie
    
    cur.execute("""
        INSERT INTO besoins (uai, prof_absent_id, matiere_id, matiere_declaree, heures, date_debut, date_fin, motif, vu_rectorat)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE);
    """, (b.uai, b.prof_absent_id, matiere_id, mat_label, b.heures, b.date_debut, b.date_fin, b.motif))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "reconnue": matiere_id is not None}

@app.post("/api/besoins/{besoin_id}/resoudre-matiere")
def resoudre_matiere_besoin(besoin_id: int, req: ResoudreMatiereRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT uai, matiere_declaree FROM besoins WHERE id = %s;", (besoin_id,))
    b_row = cur.fetchone()
    if not b_row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Besoin introuvable")
    uai, ancienne_matiere = b_row[0], b_row[1]
    
    if req.mode == "associer":
        cur.execute("SELECT id, nom FROM matieres WHERE id = %s;", (req.matiere_id,))
        m_row = cur.fetchone()
        if not m_row:
            raise HTTPException(status_code=400, detail="Matière officielle introuvable")
        cible_id, nom_officiel = m_row[0], m_row[1]
        
        cur.execute("UPDATE besoins SET matiere_id = %s, matiere_declaree = %s WHERE id = %s;", (cible_id, nom_officiel, besoin_id))
        
        if req.corriger_ecole and ancienne_matiere:
            cur.execute("DELETE FROM matieres_etablissement WHERE uai = %s AND LOWER(TRIM(nom)) = LOWER(TRIM(%s));", (uai, ancienne_matiere))
            cur.execute("INSERT INTO matieres_etablissement (uai, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (uai, nom_officiel))
            cur.execute("UPDATE professeurs_etablissement SET matiere_ecole = %s WHERE uai = %s AND LOWER(TRIM(matiere_ecole)) = LOWER(TRIM(%s));", (nom_officiel, uai, ancienne_matiere))
            
    elif req.mode == "creer":
        nom_propre = req.nouveau_nom.strip()
        cur.execute("INSERT INTO matieres (nom) VALUES (%s) ON CONFLICT (nom) DO UPDATE SET nom = EXCLUDED.nom RETURNING id;", (nom_propre,))
        cible_id = cur.fetchone()[0]
        
        for cid in (req.concours_ids or []):
            cur.execute("INSERT INTO concours_matieres (concours_id, matiere_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (cid, cible_id))
            
        cur.execute("UPDATE besoins SET matiere_id = %s, matiere_declaree = %s WHERE id = %s;", (cible_id, nom_propre, besoin_id))
        if ancienne_matiere and ancienne_matiere != nom_propre:
            cur.execute("DELETE FROM matieres_etablissement WHERE uai = %s AND LOWER(TRIM(nom)) = LOWER(TRIM(%s));", (uai, ancienne_matiere))
            cur.execute("INSERT INTO matieres_etablissement (uai, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (uai, nom_propre))
            cur.execute("UPDATE professeurs_etablissement SET matiere_ecole = %s WHERE uai = %s AND LOWER(TRIM(matiere_ecole)) = LOWER(TRIM(%s));", (nom_propre, uai, ancienne_matiere))

    conn.commit()
    cur.close()
    conn.close()
    return {"status": "resolved"}

@app.put("/api/besoins/marquer-vus")
def marquer_besoins_vus():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE besoins SET vu_rectorat = TRUE WHERE vu_rectorat = FALSE;")
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/besoins/{besoin_id}")
def supprimer_besoin(besoin_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM besoins WHERE id = %s;", (besoin_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

# --- 4. REMPLAÇANTS (TZR & CONTRACTUELS) ---
@app.get("/api/remplacants")
def get_remplacants():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.nom, r.statut, r.concours_id, COALESCE(c.intitule, 'Non défini'),
               r.rattachement, r.type_adresse, float8(r.heures_max), float8(r.heures_actuelles),
               float8(r.heures_max - r.heures_actuelles) as restantes, float8(r.quotite),
               r.telephone, r.email, ST_Y(r.geom), ST_X(r.geom),
               ARRAY_AGG(m.nom) FILTER (WHERE m.nom IS NOT NULL) as matieres_possibles
        FROM remplacants r
        LEFT JOIN concours c ON r.concours_id = c.id
        LEFT JOIN concours_matieres cm ON c.id = cm.concours_id
        LEFT JOIN matieres m ON cm.matiere_id = m.id
        GROUP BY r.id, c.intitule
        ORDER BY r.nom;
    """)
    res = [{
        "id": r[0], "nom": r[1], "statut": r[2], "concours_id": r[3], "concours": r[4],
        "adresse": r[5], "type_adresse": r[6], "heures_max": r[7], "heures_actuelles": r[8],
        "heures_restantes": r[9], "quotite": r[10], "telephone": r[11], "email": r[12],
        "latitude": r[13], "longitude": r[14], "matieres": r[15] or []
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/remplacants")
def creer_remplacant(r: RemplacantCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT float8(heures_statutaires) FROM concours WHERE id = %s;", (r.concours_id,))
    row = cur.fetchone()
    base_h = row[0] if row else 18.0
    heures_max = round((base_h * r.quotite) / 100.0, 2)
    
    cur.execute("""
        INSERT INTO remplacants (nom, statut, concours_id, rattachement, type_adresse, heures_max, heures_actuelles, quotite, telephone, email, geom)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326));
    """, (r.nom, r.statut, r.concours_id, r.adresse_libelle, r.type_adresse, heures_max, r.heures_actuelles, r.quotite, r.telephone, r.email, r.longitude, r.latitude))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.put("/api/remplacants/{remp_id}")
def modifier_remplacant(remp_id: int, r: RemplacantCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT float8(heures_statutaires) FROM concours WHERE id = %s;", (r.concours_id,))
    row = cur.fetchone()
    base_h = row[0] if row else 18.0
    heures_max = round((base_h * r.quotite) / 100.0, 2)
    
    cur.execute("""
        UPDATE remplacants
        SET nom=%s, statut=%s, concours_id=%s, rattachement=%s, type_adresse=%s,
            heures_max=%s, heures_actuelles=%s, quotite=%s, telephone=%s, email=%s,
            geom=ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        WHERE id=%s;
    """, (r.nom, r.statut, r.concours_id, r.adresse_libelle, r.type_adresse, heures_max, r.heures_actuelles, r.quotite, r.telephone, r.email, r.longitude, r.latitude, remp_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "updated"}

@app.post("/api/remplacants/import")
def import_remplacants(data: CSVImport):
    conn = get_db_connection()
    cur = conn.cursor()
    f = io.StringIO(data.csv_text.strip())
    reader = csv.reader(f, delimiter=';')
    ajoutes = 0
    for row in reader:
        if len(row) < 4 or row[0].lower() == 'nom':
            continue
        nom, statut, concours_nom, rad = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
        quotite = float(row[4].replace(',', '.')) if len(row) > 4 and row[4].strip() else 100.0
        tel = row[5].strip() if len(row) > 5 else ""
        email = row[6].strip() if len(row) > 6 else ""
        
        cur.execute("SELECT id, float8(heures_statutaires) FROM concours WHERE LOWER(intitule) = LOWER(%s) LIMIT 1;", (concours_nom,))
        c_row = cur.fetchone()
        c_id = c_row[0] if c_row else None
        base_h = c_row[1] if c_row else 18.0
        h_max = round((base_h * quotite) / 100.0, 2)
        
        cur.execute("SELECT nom, ST_Y(geom), ST_X(geom) FROM etablissements WHERE uai = %s OR LOWER(nom) LIKE LOWER(%s) LIMIT 1;", (rad, f"%{rad}%"))
        e_row = cur.fetchone()
        if e_row:
            adresse_lib, lat, lng = e_row[0], e_row[1], e_row[2]
        else:
            adresse_lib, lat, lng = rad, 48.793, 2.396
            
        cur.execute("""
            INSERT INTO remplacants (nom, statut, concours_id, rattachement, type_adresse, heures_max, heures_actuelles, quotite, telephone, email, geom)
            VALUES (%s, %s, %s, %s, 'Rattachement', %s, 0, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326));
        """, (nom, statut, c_id, adresse_lib, h_max, quotite, tel, email, lng, lat))
        ajoutes += 1
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "ajoutes": ajoutes}

@app.delete("/api/remplacants/{remp_id}")
def supprimer_remplacant(remp_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM remplacants WHERE id = %s;", (remp_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}
def prochain_jour_ouvre_8h():
    now = datetime.now()
    # Si on est vendredi soir, samedi ou dimanche, on vise le lundi suivant
    jours_ajout = 1
    while (now + timedelta(days=jours_ajout)).weekday() >= 5:
        jours_ajout += 1
    cible = now + timedelta(days=jours_ajout)
    return cible.strftime("%Y%m%dT080000")

def calculer_tc_navitia(lat_dep, lng_dep, lat_arr, lng_arr):
    token = os.getenv("NAVITIA_TOKEN")
    if not token:
        return None, None
    try:
        dt = prochain_jour_ouvre_8h()
        url = f"https://api.navitia.io/v1/coverage/fr-idf/journeys?from={lng_dep};{lat_dep}&to={lng_arr};{lat_arr}&datetime={dt}&datetime_represents=arrival&count=1"
        req = urllib.request.Request(url)
        auth = base64.b64encode(f"{token}:".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if "journeys" in data and len(data["journeys"]) > 0:
                j = data["journeys"][0]
                duree_min = round(j["duration"] / 60)
                lignes = []
                for sec in j.get("sections", []):
                    if sec.get("type") == "public_transport" and "display_informations" in sec:
                        info = sec["display_informations"]
                        lignes.append(f"{info.get('commercial_mode', '')} {info.get('code', '')}".strip())
                resume_lignes = " ➔ ".join(lignes) if lignes else "Marche directe"
                return duree_min, resume_lignes
    except Exception as e:
        print("Erreur Navitia :", e)
    return None, None

# --- 5. MATCHING SPATIAL, POLYVALENCE & TEMPS DE TRAJET ---
@app.get("/api/match")
def match_remplacants(besoin_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT uai, matiere_id, float8(heures) FROM besoins WHERE id = %s;", (besoin_id,))
    b = cur.fetchone()
    if not b or not b[1]:
        cur.close()
        conn.close()
        return []
    uai, matiere_id, heures_req = b[0], b[1], b[2]
    
    cur.execute("""
        SELECT r.id, r.nom, r.statut, c.intitule, r.rattachement,
               float8(r.heures_max - r.heures_actuelles) as dispo,
               r.telephone, r.email, ST_Y(r.geom), ST_X(r.geom),
               ROUND((ST_Distance(r.geom::geography, e.geom::geography) / 1000.0)::numeric, 2) as dist_km,
               ST_Y(e.geom), ST_X(e.geom)
        FROM remplacants r
        JOIN concours c ON r.concours_id = c.id
        JOIN concours_matieres cm ON c.id = cm.concours_id
        JOIN etablissements e ON e.uai = %s
        WHERE cm.matiere_id = %s
          AND (r.heures_max - r.heures_actuelles) >= %s
        ORDER BY dist_km ASC;
    """, (uai, matiere_id, heures_req))
    
    rows = cur.fetchall()
    cur.close()
    conn.close()

    res = []
    for r in rows:
        tc_min, tc_lignes = calculer_tc_navitia(r[8], r[9], r[11], r[12])
        res.append({
            "id": r[0], "nom": r[1], "statut": r[2], "concours": r[3], "adresse": r[4],
            "heures_restantes": r[5], "telephone": r[6], "email": r[7],
            "latitude": r[8], "longitude": r[9], "distance_km": float(r[10]),
            "tc_minutes": tc_min, "tc_lignes": tc_lignes
        })
    return res

# --- 6. AFFECTATIONS & HISTORIQUE ---
@app.post("/api/affecter")
def affecter(req: AffectationRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.uai, b.matiere_id, b.heures, b.date_debut, b.date_fin,
               COALESCE(m.nom, b.matiere_declaree)
        FROM besoins b
        LEFT JOIN matieres m ON b.matiere_id = m.id
        WHERE b.id = %s;
    """, (req.besoin_id,))
    b = cur.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Besoin introuvable")
        
    cur.execute("""
        INSERT INTO affectations (remplacant_id, uai, matiere_id, matiere_nom, heures, date_debut, date_fin)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (req.remplacant_id, b[0], b[1], b[5], b[2], b[3], b[4]))
    
    cur.execute("UPDATE remplacants SET heures_actuelles = heures_actuelles + %s WHERE id = %s;", (b[2], req.remplacant_id))
    cur.execute("DELETE FROM besoins WHERE id = %s;", (req.besoin_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.get("/api/affectations")
def get_affectations():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.remplacant_id, r.nom, a.uai, e.nom,
               COALESCE(m.nom, NULLIF(a.matiere_nom, ''), 'Matière'),
               float8(a.heures), a.date_debut, a.date_fin
        FROM affectations a
        JOIN remplacants r ON a.remplacant_id = r.id
        JOIN etablissements e ON a.uai = e.uai
        LEFT JOIN matieres m ON a.matiere_id = m.id
        ORDER BY a.date_creation DESC;
    """)
    res = [{
        "id": r[0], "remplacant_id": r[1], "nom_prof": r[2], "uai": r[3],
        "nom_etablissement": r[4], "discipline": r[5],
        "heures": r[6], "date_debut": str(r[7]), "date_fin": str(r[8])
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.put("/api/affectations/{aff_id}")
def modifier_affectation(aff_id: int, up: AffectationUpdate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT remplacant_id, float8(heures) FROM affectations WHERE id = %s;", (aff_id,))
    old = cur.fetchone()
    if old:
        diff = up.heures - old[1]
        cur.execute("UPDATE remplacants SET heures_actuelles = GREATEST(0, heures_actuelles + %s) WHERE id = %s;", (diff, old[0]))
        cur.execute("UPDATE affectations SET heures = %s, date_debut = %s, date_fin = %s WHERE id = %s;", (up.heures, up.date_debut, up.date_fin, aff_id))
        conn.commit()
    cur.close()
    conn.close()
    return {"status": "updated"}

@app.delete("/api/affectations/{aff_id}")
def supprimer_affectation(aff_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT remplacant_id, float8(heures) FROM affectations WHERE id = %s;", (aff_id,))
    old = cur.fetchone()
    if old:
        cur.execute("UPDATE remplacants SET heures_actuelles = GREATEST(0, heures_actuelles - %s) WHERE id = %s;", (old[1], old[0]))
        cur.execute("DELETE FROM affectations WHERE id = %s;", (aff_id,))
        conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

@app.get("/api/remplacants/{remp_id}/historique")
def get_historique_remplacant(remp_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.nom, COALESCE(m.nom, NULLIF(a.matiere_nom, ''), '-'), float8(a.heures), a.date_debut, a.date_fin
        FROM affectations a
        JOIN etablissements e ON a.uai = e.uai
        LEFT JOIN matieres m ON a.matiere_id = m.id
        WHERE a.remplacant_id = %s
        ORDER BY a.date_debut DESC;
    """, (remp_id,))
    res = [{"etablissement": r[0], "discipline": r[1], "heures": r[2], "date_debut": str(r[3]), "date_fin": str(r[4])} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res