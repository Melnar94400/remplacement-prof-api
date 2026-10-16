import pandas as pd
import psycopg2

conn = psycopg2.connect(dbname="rectorat", user="postgres", password="admin", host="localhost")
cur = conn.cursor()

cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

cur.execute("""
    DROP TABLE IF EXISTS etablissements;
    CREATE TABLE etablissements (
        uai VARCHAR(8) PRIMARY KEY,
        nom VARCHAR(255),
        type VARCHAR(50),
        degre VARCHAR(50),
        geom geometry(Point, 4326)
    );
""")

cur.execute("""
    DROP TABLE IF EXISTS professeurs;
    CREATE TABLE professeurs (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(100),
        statut VARCHAR(50),
        discipline VARCHAR(100),
        rattachement VARCHAR(255),
        disponible BOOLEAN,
        geom geometry(Point, 4326)
    );
""")

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

print("Importation des professeurs...")
profs = [
    ("M. Dupont", "TZR", "Physique-Chimie", "Lycée Jean Macé", True, 2.395, 48.785),
    ("Mme. Martin", "Contractuel", "Physique-Chimie", "Adresse perso", True, 2.380, 48.790),
    ("M. Bernard", "TZR", "SVT", "Collège Rabelais", True, 2.390, 48.798)
]
for p in profs:
    cur.execute("""
        INSERT INTO professeurs (nom, statut, discipline, rattachement, disponible, geom)
        VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """, p)

conn.commit()
cur.close()
conn.close()
print("Base de données PostGIS initialisée avec succès !")