import os
import csv
import io
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
from dotenv import load_dotenv

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

class LiaisonCreate(BaseModel):
    concours_id: int
    matiere_id: int

class ProfEtabCreate(BaseModel):
    nom: str
    concours_id: int
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
    prof_absent_id: int
    matiere_id: int
    heures: float
    date_debut: str
    date_fin: str
    motif: Optional[str] = "Absence"

class AffectationRequest(BaseModel):
    remplacant_id: int
    besoin_id: int

class AffectationUpdate(BaseModel):
    heures: float
    date_debut: str
    date_fin: str

# --- 1. RÉFÉRENTIEL ÉVOLUTIF (CONCOURS & MATIÈRES) ---
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
    cur.execute("INSERT INTO matieres (nom) VALUES (%s) ON CONFLICT DO NOTHING;", (m.nom,))
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

# --- 2. ÉTABLISSEMENTS & COMPTES ÉCOLES ---
@app.get("/api/etablissements")
def get_etablissements():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.uai, e.nom, e.type, e.degre, ST_Y(e.geom), ST_X(e.geom),
               (SELECT COUNT(*) FROM professeurs_etablissement pe WHERE pe.uai = e.uai) as nb_profs,
               (SELECT COUNT(*) FROM besoins b WHERE b.uai = e.uai) as nb_besoins
        FROM etablissements e
        ORDER BY e.nom;
    """)
    res = [{
        "uai": r[0], "nom": r[1], "type": r[2], "degre": r[3],
        "latitude": r[4], "longitude": r[5], "nb_profs": r[6], "nb_besoins": r[7]
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

@app.get("/api/ecoles/{uai}/professeurs")
def get_profs_ecole(uai: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT pe.id, pe.nom, pe.concours_id, COALESCE(c.intitule, 'Non défini'), float8(pe.heures_poste)
        FROM professeurs_etablissement pe
        LEFT JOIN concours c ON pe.concours_id = c.id
        WHERE pe.uai = %s
        ORDER BY pe.nom;
    """, (uai,))
    res = [{"id": r[0], "nom": r[1], "concours_id": r[2], "concours": r[3], "heures_poste": r[4]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/ecoles/{uai}/professeurs")
def add_prof_ecole(uai: str, p: ProfEtabCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO professeurs_etablissement (uai, nom, concours_id, heures_poste) VALUES (%s, %s, %s, %s);",
        (uai, p.nom, p.concours_id, p.heures_poste)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

@app.post("/api/ecoles/{uai}/professeurs/import")
def import_profs_ecole(uai: str, data: CSVImport):
    conn = get_db_connection()
    cur = conn.cursor()
    f = io.StringIO(data.csv_text.strip())
    reader = csv.reader(f, delimiter=';')
    ajoutes = 0
    for row in reader:
        if len(row) < 2 or row[0].lower() == 'nom':
            continue
        nom = row[0].strip()
        concours_nom = row[1].strip()
        heures = float(row[2].replace(',', '.')) if len(row) > 2 and row[2].strip() else 18.0
        
        cur.execute("SELECT id FROM concours WHERE LOWER(intitule) = LOWER(%s) LIMIT 1;", (concours_nom,))
        c_row = cur.fetchone()
        c_id = c_row[0] if c_row else None
        
        cur.execute(
            "INSERT INTO professeurs_etablissement (uai, nom, concours_id, heures_poste) VALUES (%s, %s, %s, %s);",
            (uai, nom, c_id, heures)
        )
        ajoutes += 1
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "ajoutes": ajoutes}

@app.delete("/api/ecoles/professeurs/{prof_id}")
def delete_prof_ecole(prof_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM professeurs_etablissement WHERE id = %s;", (prof_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted"}

# --- 3. BESOINS & ALERTES RECTORAT ---
@app.get("/api/besoins")
def get_besoins():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, b.uai, e.nom, b.prof_absent_id, COALESCE(pe.nom, 'Poste vacant'),
               b.matiere_id, m.nom, float8(b.heures), b.date_debut, b.date_fin, b.motif,
               b.vu_rectorat, ST_Y(e.geom), ST_X(e.geom)
        FROM besoins b
        JOIN etablissements e ON b.uai = e.uai
        JOIN matieres m ON b.matiere_id = m.id
        LEFT JOIN professeurs_etablissement pe ON b.prof_absent_id = pe.id
        ORDER BY b.vu_rectorat ASC, b.date_declaration DESC;
    """)
    res = [{
        "id": r[0], "uai": r[1], "nom_etablissement": r[2], "prof_absent_id": r[3],
        "prof_absent_nom": r[4], "matiere_id": r[5], "matiere": r[6], "heures": r[7],
        "date_debut": str(r[8]), "date_fin": str(r[9]), "motif": r[10],
        "vu_rectorat": r[11], "latitude": r[12], "longitude": r[13]
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

@app.post("/api/besoins")
def creer_besoin(b: BesoinCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO besoins (uai, prof_absent_id, matiere_id, heures, date_debut, date_fin, motif, vu_rectorat)
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE);
    """, (b.uai, b.prof_absent_id, b.matiere_id, b.heures, b.date_debut, b.date_fin, b.motif))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}

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
        # Format attendu : Nom;Statut;Concours;UAI_ou_Nom_RAD;Quotite;Telephone;Email
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

# --- 5. MATCHING SPATIAL & POLYVALENCE (DU PLUS PROCHE AU PLUS ÉLOIGNÉ) ---
@app.get("/api/match")
def match_remplacants(besoin_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT uai, matiere_id, float8(heures) FROM besoins WHERE id = %s;", (besoin_id,))
    b = cur.fetchone()
    if not b:
        cur.close()
        conn.close()
        return []
    uai, matiere_id, heures_req = b[0], b[1], b[2]
    
    cur.execute("""
        SELECT r.id, r.nom, r.statut, c.intitule, r.rattachement,
               float8(r.heures_max - r.heures_actuelles) as dispo,
               r.telephone, r.email, ST_Y(r.geom), ST_X(r.geom),
               ROUND((ST_Distance(r.geom::geography, e.geom::geography) / 1000.0)::numeric, 2) as dist_km
        FROM remplacants r
        JOIN concours c ON r.concours_id = c.id
        JOIN concours_matieres cm ON c.id = cm.concours_id
        JOIN etablissements e ON e.uai = %s
        WHERE cm.matiere_id = %s
          AND (r.heures_max - r.heures_actuelles) >= %s
        ORDER BY dist_km ASC;
    """, (uai, matiere_id, heures_req))
    
    res = [{
        "id": r[0], "nom": r[1], "statut": r[2], "concours": r[3], "adresse": r[4],
        "heures_restantes": r[5], "telephone": r[6], "email": r[7],
        "latitude": r[8], "longitude": r[9], "distance_km": float(r[10])
    } for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res

# --- 6. AFFECTATIONS & HISTORIQUE ---
@app.post("/api/affecter")
def affecter(req: AffectationRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.uai, b.matiere_id, b.heures, b.date_debut, b.date_fin, COALESCE(pe.nom, 'Poste vacant')
        FROM besoins b
        LEFT JOIN professeurs_etablissement pe ON b.prof_absent_id = pe.id
        WHERE b.id = %s;
    """, (req.besoin_id,))
    b = cur.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Besoin introuvable")
        
    cur.execute("""
        INSERT INTO affectations (remplacant_id, uai, matiere_id, prof_remplace_nom, heures, date_debut, date_fin)
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
        SELECT a.id, a.remplacant_id, r.nom, a.uai, e.nom, COALESCE(m.nom, 'Matière'),
               a.prof_remplace_nom, float8(a.heures), a.date_debut, a.date_fin
        FROM affectations a
        JOIN remplacants r ON a.remplacant_id = r.id
        JOIN etablissements e ON a.uai = e.uai
        LEFT JOIN matieres m ON a.matiere_id = m.id
        ORDER BY a.date_creation DESC;
    """)
    res = [{
        "id": r[0], "remplacant_id": r[1], "nom_prof": r[2], "uai": r[3],
        "nom_etablissement": r[4], "discipline": r[5], "prof_remplace": r[6],
        "heures": r[7], "date_debut": str(r[8]), "date_fin": str(r[9])
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
        SELECT e.nom, COALESCE(m.nom, '-'), a.prof_remplace_nom, float8(a.heures), a.date_debut, a.date_fin
        FROM affectations a
        JOIN etablissements e ON a.uai = e.uai
        LEFT JOIN matieres m ON a.matiere_id = m.id
        WHERE a.remplacant_id = %s
        ORDER BY a.date_debut DESC;
    """, (remp_id,))
    res = [{"etablissement": r[0], "discipline": r[1], "prof_remplace": r[2], "heures": r[3], "date_debut": str(r[4]), "date_fin": str(r[5])} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return res