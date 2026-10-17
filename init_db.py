import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# 1. CONNEXION À SUPABASE
conn = psycopg2.connect(
    host="db.scacemkfeugwaugxprhh.supabase.co",
    port="5432",
    database="postgres",
    user="postgres",
    password=os.getenv("SUPABASE_PASSWORD") 
)
cur = conn.cursor()

# 2. ACTIVATION DE POSTGIS
cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

# 3. CRÉATION DES TABLES AVEC LE SCHÉMA COMPLET (V6)
cur.execute("""
    DROP TABLE IF EXISTS besoins;
    DROP TABLE IF EXISTS professeurs;
    DROP TABLE IF EXISTS etablissements;

    CREATE TABLE etablissements (
        uai VARCHAR(8) PRIMARY KEY,
        nom VARCHAR(255),
        type VARCHAR(50),
        degre VARCHAR(50),
        geom geometry(Point, 4326)
    );

    CREATE TABLE professeurs (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(100),
        statut VARCHAR(50),
        corps VARCHAR(50) DEFAULT 'Certifié',
        discipline VARCHAR(100),
        rattachement VARCHAR(255),
        type_adresse VARCHAR(50) DEFAULT 'Rattachement',
        heures_max NUMERIC(5,2) DEFAULT 18.0,
        heures_actuelles NUMERIC(5,2) DEFAULT 0.0,
        quotite NUMERIC(5,2) DEFAULT 100.0,
        telephone VARCHAR(20) DEFAULT '',
        email VARCHAR(100) DEFAULT '',
        disponible BOOLEAN DEFAULT TRUE,
        geom geometry(Point, 4326)
    );

    CREATE TABLE besoins (
        id SERIAL PRIMARY KEY,
        uai VARCHAR(8) REFERENCES etablissements(uai),
        discipline VARCHAR(100),
        heures NUMERIC(5,2),
        date_declaration TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")

# 4. IMPORTATION DES ÉTABLISSEMENTS DE VITRY-SUR-SEINE
print("Importation des établissements...")
df = pd.read_csv("fr-en-annuaire-education.csv", sep=";", dtype={"Code_postal": str}, low_memory=False)
df_secteur = df[df["Nom_commune"] == "Vitry-sur-Seine"].copy().dropna(subset=["latitude", "longitude"])

for _, row in df_secteur.iterrows():
    degre = "Primaire" if row["Type_etablissement"] == "Ecole" else ("Secondaire" if row["Type_etablissement"] in ["Collège", "Lycée"] else "Autre")
    if degre != "Autre":
        cur.execute("""
            INSERT INTO etablissements (uai, nom, type, degre, geom)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        """, (row["Identifiant_de_l_etablissement"], row["Nom_etablissement"], row["Type_etablissement"], degre, row["longitude"], row["latitude"]))

conn.commit()
cur.close()
conn.close()
print("Base de données Supabase initialisée avec la structure finale !")