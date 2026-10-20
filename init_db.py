import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host="aws-0-eu-west-1.pooler.supabase.com",
    port="6543",
    database="postgres",
    user="postgres.scacemkfeugwaugxprhh",
    password=os.getenv("SUPABASE_PASSWORD"),
    sslmode="require"
)
cur = conn.cursor()

print("1. Création de l'extension PostGIS et nettoyage des tables...")
cur.execute("""
    CREATE EXTENSION IF NOT EXISTS postgis;

    DROP TABLE IF EXISTS affectations CASCADE;
    DROP TABLE IF EXISTS besoins CASCADE;
    DROP TABLE IF EXISTS remplacants CASCADE;
    DROP TABLE IF EXISTS professeurs_etablissement CASCADE;
    DROP TABLE IF EXISTS professeurs CASCADE;
    DROP TABLE IF EXISTS concours_matieres CASCADE;
    DROP TABLE IF EXISTS matieres CASCADE;
    DROP TABLE IF EXISTS concours CASCADE;
    DROP TABLE IF EXISTS etablissements CASCADE;
""")

print("2. Création du nouveau schéma relationnel (V10)...")
cur.execute("""
    -- 1. Table des concours / titres de recrutement
    CREATE TABLE concours (
        id SERIAL PRIMARY KEY,
        type_concours VARCHAR(50), -- CAPES, Agrégation, CAPLP, CAPET, Contractuel
        intitule VARCHAR(150) UNIQUE NOT NULL,
        heures_statutaires NUMERIC(4,1) DEFAULT 18.0
    );

    -- 2. Table des matières enseignées dans les établissements
    CREATE TABLE matieres (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(100) UNIQUE NOT NULL
    );

    -- 3. Table de liaison N-N (Un concours permet d'enseigner X matières)
    CREATE TABLE concours_matieres (
        concours_id INTEGER REFERENCES concours(id) ON DELETE CASCADE,
        matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
        PRIMARY KEY (concours_id, matiere_id)
    );

    -- 4. Table des établissements (avec mot de passe pour le compte école)
    CREATE TABLE etablissements (
        uai VARCHAR(8) PRIMARY KEY,
        nom VARCHAR(255),
        type VARCHAR(50),
        degre VARCHAR(50),
        mot_de_passe VARCHAR(100) DEFAULT '1234',
        geom geometry(Point, 4326)
    );

    -- 5. Professeurs en poste dans l'établissement
    CREATE TABLE professeurs_etablissement (
        id SERIAL PRIMARY KEY,
        uai VARCHAR(8) REFERENCES etablissements(uai) ON DELETE CASCADE,
        nom VARCHAR(100) NOT NULL,
        concours_id INTEGER REFERENCES concours(id) ON DELETE SET NULL,
        heures_poste NUMERIC(5,2) DEFAULT 18.0
    );

    -- 6. Vivier du Rectorat (TZR et Contractuels)
    CREATE TABLE remplacants (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(100) NOT NULL,
        statut VARCHAR(50) NOT NULL, -- TZR ou Contractuel
        concours_id INTEGER REFERENCES concours(id) ON DELETE SET NULL,
        rattachement VARCHAR(255),
        type_adresse VARCHAR(50) DEFAULT 'Rattachement',
        heures_max NUMERIC(5,2) DEFAULT 18.0,
        heures_actuelles NUMERIC(5,2) DEFAULT 0.0,
        quotite NUMERIC(5,2) DEFAULT 100.0,
        telephone VARCHAR(20) DEFAULT '',
        email VARCHAR(100) DEFAULT '',
        geom geometry(Point, 4326)
    );

    -- 7. Besoins déclarés par les chefs d'établissement
    CREATE TABLE besoins (
        id SERIAL PRIMARY KEY,
        uai VARCHAR(8) REFERENCES etablissements(uai) ON DELETE CASCADE,
        prof_absent_id INTEGER REFERENCES professeurs_etablissement(id) ON DELETE SET NULL,
        matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
        heures NUMERIC(5,2),
        date_debut DATE,
        date_fin DATE,
        motif VARCHAR(255) DEFAULT 'Congé maladie',
        vu_rectorat BOOLEAN DEFAULT FALSE,
         date_declaration TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 8. Historique des affectations
    CREATE TABLE affectations (
        id SERIAL PRIMARY KEY,
        remplacant_id INTEGER REFERENCES remplacants(id) ON DELETE CASCADE,
        uai VARCHAR(8) REFERENCES etablissements(uai) ON DELETE CASCADE,
        matiere_id INTEGER REFERENCES matieres(id) ON DELETE SET NULL,
        prof_remplace_nom VARCHAR(100) DEFAULT '',
        heures NUMERIC(5,2),
        date_debut DATE,
        date_fin DATE,
        date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")

print("3. Initialisation du référentiel évolutif (Concours & Matières)...")
concours_init = [
    ("CAPES", "CAPES Physique-Chimie", 18.0),
    ("Agrégation", "Agrégation Physique-Chimie", 15.0),
    ("CAPES", "CAPES SVT", 18.0),
    ("Agrégation", "Agrégation SVT", 15.0),
    ("CAPES", "CAPES Mathématiques", 18.0),
    ("Agrégation", "Agrégation Mathématiques", 15.0),
    ("CAPLP", "CAPLP Maths-Sciences", 18.0),
    ("CAPET", "CAPET Biotechnologies", 18.0),
    ("CAPET", "CAPET SII (Technologie / Ingénierie)", 18.0),
    ("CAPES", "CAPES Lettres Modernes", 18.0),
    ("CAPES", "CAPES Histoire-Géographie", 18.0),
    ("CAPES", "CAPES Anglais", 18.0)
]
for t, intitule, h in concours_init:
    cur.execute("INSERT INTO concours (type_concours, intitule, heures_statutaires) VALUES (%s, %s, %s);", (t, intitule, h))

matieres_init = [
    "Physique-Chimie",
    "SVT",
    "Sciences et Technologie (Cycle 3)",
    "Enseignement Scientifique (Lycée)",
    "SNT (Sciences Numériques et Technologie)",
    "Mathématiques",
    "Biotechnologies / Santé-Environnement (PSE)",
    "Technologie",
    "Français",
    "Histoire-Géographie-EMC",
    "Anglais"
]
for m in matieres_init:
    cur.execute("INSERT INTO matieres (nom) VALUES (%s);", (m,))

# Création des correspondances initiales (N-N)
liaisons = [
    ("CAPES Physique-Chimie", ["Physique-Chimie", "Sciences et Technologie (Cycle 3)", "Enseignement Scientifique (Lycée)", "SNT (Sciences Numériques et Technologie)"]),
    ("Agrégation Physique-Chimie", ["Physique-Chimie", "Enseignement Scientifique (Lycée)", "SNT (Sciences Numériques et Technologie)"]),
    ("CAPES SVT", ["SVT", "Sciences et Technologie (Cycle 3)", "Enseignement Scientifique (Lycée)", "Biotechnologies / Santé-Environnement (PSE)"]),
    ("Agrégation SVT", ["SVT", "Enseignement Scientifique (Lycée)"]),
    ("CAPES Mathématiques", ["Mathématiques", "SNT (Sciences Numériques et Technologie)"]),
    ("Agrégation Mathématiques", ["Mathématiques", "SNT (Sciences Numériques et Technologie)"]),
    ("CAPLP Maths-Sciences", ["Mathématiques", "Physique-Chimie", "Sciences et Technologie (Cycle 3)", "SNT (Sciences Numériques et Technologie)"]),
    ("CAPET Biotechnologies", ["SVT", "Biotechnologies / Santé-Environnement (PSE)", "Sciences et Technologie (Cycle 3)"]),
    ("CAPET SII (Technologie / Ingénierie)", ["Technologie", "Sciences et Technologie (Cycle 3)", "SNT (Sciences Numériques et Technologie)"]),
    ("CAPES Lettres Modernes", ["Français"]),
    ("CAPES Histoire-Géographie", ["Histoire-Géographie-EMC"]),
    ("CAPES Anglais", ["Anglais"])
]

for conc_nom, mats in liaisons:
    for mat_nom in mats:
        cur.execute("""
            INSERT INTO concours_matieres (concours_id, matiere_id)
            SELECT c.id, m.id FROM concours c, matieres m
            WHERE c.intitule = %s AND m.nom = %s
            ON CONFLICT DO NOTHING;
        """, (conc_nom, mat_nom))

print("4. Importation des établissements de Vitry-sur-Seine...")
with open('fr-en-annuaire-education.csv', 'r', encoding='utf-8-sig') as f:
    premiere_ligne = f.readline()
    sep = ';' if premiere_ligne.count(';') > premiere_ligne.count(',') else ','

df = pd.read_csv('fr-en-annuaire-education.csv', sep=sep, low_memory=False, encoding='utf-8-sig')
df.columns = [c.strip().lower() for c in df.columns]

def trouver_col(candidats):
    for c in candidats:
        if c in df.columns:
            return c
    raise KeyError(f"Colonnes introuvables parmi {candidats}. Colonnes du CSV : {list(df.columns)[:15]}")

col_uai = trouver_col(['identifiant_de_l_etablissement', 'numero_uai', 'uai'])
col_nom = trouver_col(['nom_etablissement', 'appellation_officielle', 'nom'])
col_type = trouver_col(['type_etablissement', 'nature_uai_libe', 'type'])
col_lat = trouver_col(['latitude', 'lat'])
col_lng = trouver_col(['longitude', 'lng', 'lon'])

# Filtrage sur Vitry-sur-Seine (par nom de commune ou code postal 94400)
if 'nom_commune' in df.columns:
     masque_vitry = df['nom_commune'].astype(str).str.contains('vitry-sur-seine', case=False, na=False)
elif 'libelle_commune' in df.columns:
    masque_vitry = df['libelle_commune'].astype(str).str.contains('vitry-sur-seine', case=False, na=False)
elif 'code_postal' in df.columns:
    masque_vitry = df['code_postal'].astype(str).str.contains('94400', na=False)
else:
    masque_vitry = pd.Series([True] * len(df))

df_vitry = df[masque_vitry & df[col_lat].notna() & df[col_lng].notna()]

nb_importes = 0
for _, row in df_vitry.iterrows():
    uai = str(row[col_uai]).strip()
    nom = str(row[col_nom]).strip()
    type_etab = str(row[col_type]).strip()
    
    if any(k in type_etab.lower() for k in ['collège', 'college', 'lycée', 'lycee']):
        degre = 'Secondaire'
    elif any(k in type_etab.lower() for k in ['ecole', 'école', 'maternelle', 'élémentaire']):
        degre = 'Primaire'
    else:
        degre = 'Autre'
        
    lat = float(str(row[col_lat]).replace(',', '.'))
    lng = float(str(row[col_lng]).replace(',', '.'))
    
    cur.execute("""
        INSERT INTO etablissements (uai, nom, type, degre, mot_de_passe, geom)
        VALUES (%s, %s, %s, %s, '1234', ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        ON CONFLICT (uai) DO NOTHING;
    """, (uai, nom, type_etab, degre, lng, lat))
    nb_importes += 1

conn.commit()
cur.close()
conn.close()
print(f"✅ Base de données Supabase V10 initialisée avec succès ({nb_importes} établissements importés) !")