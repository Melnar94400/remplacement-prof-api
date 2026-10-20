const API_URL = "https://remplacement-prof-api.onrender.com/api";

let referentiel = { concours: [], matieres: [], liaisons: [] };
let etablissementsData = [];
let remplacantsData = [];
let besoinsData = [];
let affectationsData = [];
let ecoleConnectee = null;
let profsEcoleActuelle = [];
let besoinActifContext = null;
let autocompleteTimeout = null;

let map, layerPrimaire, layerSecondaire, layerProfs;

// --- INITIALISATION AU CHARGEMENT ---
function initApp() {
    chargerReferentiel();
    chargerEtablissements();
}
initApp();

function ouvrirModal(id) { document.getElementById(id).style.display = "flex"; }
function fermerModal(id) { document.getElementById(id).style.display = "none"; }

function deconnexion() {
    ecoleConnectee = null;
    document.getElementById('menu-rectorat').style.display = "none";
    document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
    document.getElementById('view-accueil').classList.add('active');
}

function switchTab(tabId) {
    document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.getElementById('view-' + tabId).classList.add('active');
    document.getElementById('nav-' + tabId).classList.add('active');
    if (tabId === 'map') initMap();
}

// --- 1. CHARGEMENT DU RÉFÉRENTIEL (CONCOURS & MATIÈRES) ---
function chargerReferentiel() {
    fetch(`${API_URL}/referentiel`).then(r => r.json()).then(data => {
        referentiel = data;
        remplirSelectsReferentiel();
        afficherTableReferentiel();
    });
}

function remplirSelectsReferentiel() {
    const selConcours = ['pe-concours', 'add-concours', 'ref-select-concours'];
    selConcours.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = "";
        referentiel.concours.forEach(c => el.appendChild(new Option(`${c.intitule} (${c.heures}h)`, c.id)));
    });

    const selMatieres = ['ecole-besoin-matiere', 'ref-select-matiere'];
    selMatieres.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = "";
        referentiel.matieres.forEach(m => el.appendChild(new Option(m.nom, m.id)));
    });
}

function afficherTableReferentiel() {
    const tbody = document.getElementById('table-referentiel-body');
    if (!tbody) return;
    tbody.innerHTML = "";
    referentiel.concours.forEach(c => {
        const mats = referentiel.liaisons.filter(l => l.concours_id === c.id);
        const badgesHtml = mats.map(m => 
            `<span class="badge blue">${m.matiere} <span style="cursor:pointer; margin-left:5px; color:#c00;" onclick="retirerLiaison(${c.id}, ${m.matiere_id})">×</span></span>`
        ).join(" ");
        tbody.innerHTML += `<tr>
            <td><strong>${c.intitule}</strong> <span class="badge">${c.type}</span></td>
            <td>${c.heures}h</td>
            <td>${badgesHtml || '<em style="color:#999;">Aucune matière associée</em>'}</td>
        </tr>`;
    });
}

function ajouterLiaisonConcoursMatiere() {
    const concours_id = parseInt(document.getElementById('ref-select-concours').value);
    const matiere_id = parseInt(document.getElementById('ref-select-matiere').value);
    fetch(`${API_URL}/referentiel/liaisons`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ concours_id, matiere_id })
    }).then(() => chargerReferentiel());
}

function retirerLiaison(concours_id, matiere_id) {
    fetch(`${API_URL}/referentiel/liaisons/${concours_id}/${matiere_id}`, { method: 'DELETE' })
        .then(() => chargerReferentiel());
}

function creerConcours() {
    const data = {
        type_concours: document.getElementById('new-conc-type').value,
        intitule: document.getElementById('new-conc-nom').value,
        heures_statutaires: parseFloat(document.getElementById('new-conc-heures').value)
    };
    fetch(`${API_URL}/referentiel/concours`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
        .then(() => { fermerModal('modal-add-concours'); chargerReferentiel(); });
}

function creerMatiere() {
    const nom = document.getElementById('new-mat-nom').value;
    fetch(`${API_URL}/referentiel/matieres`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nom }) })
        .then(() => { fermerModal('modal-add-matiere'); chargerReferentiel(); });
}

// --- 2. ESPACE ÉTABLISSEMENT (COMPTE ÉCOLE) ---
function chargerEtablissements() {
    fetch(`${API_URL}/etablissements`).then(r => r.json()).then(data => {
        etablissementsData = data;
        afficherTableEtabs(data);
        chargerCarteEtablissements();
    });
}

function chercherEcoleLogin(val) {
    const list = document.getElementById('login-ecole-list');
    list.innerHTML = "";
    if (val.length < 2) return;
    etablissementsData.filter(e => e.nom.toLowerCase().includes(val.toLowerCase()) || e.uai.toLowerCase().includes(val.toLowerCase()))
        .slice(0, 6).forEach(e => {
            const div = document.createElement('div');
            div.innerHTML = `<strong>${e.nom}</strong> <small>(${e.uai})</small>`;
            div.onclick = () => {
                document.getElementById('login-ecole-uai').value = e.uai;
                document.getElementById('login-ecole-selected').innerText = `📍 ${e.nom} (${e.uai})`;
                document.getElementById('login-ecole-search').value = "";
                list.innerHTML = "";
            };
            list.appendChild(div);
        });
}

function validerLoginEcole() {
    const uai = document.getElementById('login-ecole-uai').value;
    const mot_de_passe = document.getElementById('login-ecole-mdp').value;
    if (!uai) return alert("Veuillez sélectionner votre établissement.");

    fetch(`${API_URL}/login/ecole`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uai, mot_de_passe })
    }).then(r => {
        if (!r.ok) throw new Error("Mot de passe incorrect");
        return r.json();
    }).then(ecole => {
        ecoleConnectee = ecole;
        fermerModal('modal-login-ecole');
        document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
        document.getElementById('view-espace-ecole').classList.add('active');
        document.getElementById('ecole-titre-nom').innerText = ecole.nom;
        document.getElementById('ecole-titre-uai').innerText = `UAI : ${ecole.uai}`;

        const today = new Date(); const future = new Date(); future.setDate(today.getDate() + 21);
        document.getElementById('ecole-besoin-debut').value = today.toISOString().split('T')[0];
        document.getElementById('ecole-besoin-fin').value = future.toISOString().split('T')[0];

        chargerDonneesEcoleConnectee();
    }).catch(err => alert(err.message));
}

function chargerDonneesEcoleConnectee() {
    if (!ecoleConnectee) return;
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs`).then(r => r.json()).then(profs => {
        profsEcoleActuelle = profs;
        const tbody = document.getElementById('ecole-table-profs');
        const selProf = document.getElementById('ecole-besoin-prof');
        tbody.innerHTML = "";
        selProf.innerHTML = "";

        profs.forEach(p => {
            tbody.innerHTML += `<tr>
                <td><strong>${p.nom}</strong></td>
                <td><span class="badge">${p.concours}</span></td>
                <td>${p.heures_poste}h</td>
                <td><button class="btn-small btn-danger" onclick="ecoleSupprimerProf(${p.id})">🗑️</button></td>
            </tr>`;
            selProf.appendChild(new Option(`${p.nom} (${p.concours} - ${p.heures_poste}h)`, p.id));
        });
        autoRemplirHeuresProf();
    });

    // Suivi des demandes et affectations de l'école
    Promise.all([
        fetch(`${API_URL}/besoins`).then(r => r.json()),
        fetch(`${API_URL}/affectations`).then(r => r.json())
    ]).then(([besoins, affectations]) => {
        const tbody = document.getElementById('ecole-table-suivi');
        tbody.innerHTML = "";
        besoins.filter(b => b.uai === ecoleConnectee.uai).forEach(b => {
            tbody.innerHTML += `<tr>
                <td><strong>${b.prof_absent_nom}</strong> <small>(${b.motif})</small></td>
                <td>${b.matiere}</td>
                <td>${b.date_debut} ➔ ${b.date_fin}</td>
                <td>${b.heures}h</td>
                <td><span class="badge red">⏳ En attente Rectorat</span></td>
            </tr>`;
        });
        affectations.filter(a => a.uai === ecoleConnectee.uai).forEach(a => {
            tbody.innerHTML += `<tr>
                <td><strong>${a.prof_remplace}</strong></td>
                <td>${a.discipline}</td>
                <td>${a.date_debut} ➔ ${a.date_fin}</td>
                <td>${a.heures}h</td>
                <td><span class="badge green">✅ Remplacé par ${a.nom_prof}</span></td>
            </tr>`;
        });
    });
}

function autoRemplirHeuresProf() {
    const profId = parseInt(document.getElementById('ecole-besoin-prof').value);
    const prof = profsEcoleActuelle.find(p => p.id === profId);
    if (prof) {
        document.getElementById('ecole-besoin-heures').value = prof.heures_poste;
        // Pré-sélectionne la première matière correspondant au concours du prof absent
        const liaison = referentiel.liaisons.find(l => l.concours_id === prof.concours_id);
        if (liaison) document.getElementById('ecole-besoin-matiere').value = liaison.matiere_id;
    }
}

function ecoleAjouterProf() {
    const data = {
        nom: document.getElementById('pe-nom').value,
        concours_id: parseInt(document.getElementById('pe-concours').value),
        heures_poste: parseFloat(document.getElementById('pe-heures').value)
    };
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    }).then(() => {
        document.getElementById('pe-nom').value = "";
        fermerModal('modal-add-prof-ecole');
        chargerDonneesEcoleConnectee();
    });
}

function ecoleImporterCSV() {
    const csv_text = document.getElementById('csv-prof-ecole').value;
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs/import`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv_text })
    }).then(r => r.json()).then(res => {
        alert(`${res.ajoutes} professeurs importés avec succès.`);
        fermerModal('modal-import-prof-ecole');
        chargerDonneesEcoleConnectee();
    });
}

function ecoleSupprimerProf(id) {
    if (confirm("Retirer ce professeur de l'établissement ?")) {
        fetch(`${API_URL}/ecoles/professeurs/${id}`, { method: 'DELETE' }).then(() => chargerDonneesEcoleConnectee());
    }
}

function ecoleDeclarerBesoin() {
    const prof_absent_id = parseInt(document.getElementById('ecole-besoin-prof').value);
    if (!prof_absent_id) return alert("Ajoutez et sélectionnez d'abord le professeur absent.");
    const data = {
        uai: ecoleConnectee.uai,
        prof_absent_id: prof_absent_id,
        matiere_id: parseInt(document.getElementById('ecole-besoin-matiere').value),
        heures: parseFloat(document.getElementById('ecole-besoin-heures').value),
        date_debut: document.getElementById('ecole-besoin-debut').value,
        date_fin: document.getElementById('ecole-besoin-fin').value,
        motif: document.getElementById('ecole-besoin-motif').value
    };
    fetch(`${API_URL}/besoins`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    }).then(() => {
        alert("Alerte transmise au Rectorat !");
        chargerDonneesEcoleConnectee();
    });
}

// --- 3. ESPACE RECTORAT : BESOINS, ALERTES & ÉCOLES ---
function loginRectorat() {
    document.getElementById('menu-rectorat').style.display = "flex";
    switchTab('besoins');
    chargerBesoins();
    chargerEtablissements();
    chargerRemplacants();
    chargerAffectations();
    chargerReferentiel();
}

function chargerBesoins() {
    fetch(`${API_URL}/besoins`).then(r => r.json()).then(besoins => {
        besoinsData = besoins;
        const tbody = document.getElementById('table-besoins-body');
        tbody.innerHTML = "";
        let nbNouveaux = 0;

        besoins.forEach(b => {
            if (!b.vu_rectorat) nbNouveaux++;
            tbody.innerHTML += `<tr class="${!b.vu_rectorat ? 'unseen-alert' : ''}">
                <td>${!b.vu_rectorat ? '<span class="badge red">🔔 NOUVEAU</span>' : '<span class="badge">Vu</span>'}</td>
                <td><strong>${b.nom_etablissement}</strong></td>
                <td>${b.prof_absent_nom} <small>(${b.motif})</small></td>
                <td><span class="badge blue">${b.matiere}</span></td>
                <td>${b.date_debut} ➔ ${b.date_fin}</td>
                <td><strong>${b.heures}h</strong></td>
                <td>
                    <button class="btn-small btn" onclick="lancerMatching(${b.id}, ${b.latitude}, ${b.longitude}, '${b.nom_etablissement.replace(/'/g, "\\'")}', '${b.matiere.replace(/'/g, "\\'")}', ${b.heures}, '${b.prof_absent_nom.replace(/'/g, "\\'")}')">🗺️ Trouver un remplaçant</button>
                    <button class="btn-small btn-danger" onclick="supprimerBesoin(${b.id})">🗑️</button>
                </td>
            </tr>`;
        });

        const badge = document.getElementById('alert-badge');
        if (nbNouveaux > 0) { badge.style.display = "inline-block"; badge.innerText = nbNouveaux; }
        else { badge.style.display = "none"; }
    });
}

function marquerAlertesLues() {
    fetch(`${API_URL}/besoins/marquer-vus`, { method: 'PUT' }).then(() => chargerBesoins());
}

function supprimerBesoin(id) {
    if (confirm("Supprimer cette demande ?")) fetch(`${API_URL}/besoins/${id}`, { method: 'DELETE' }).then(() => chargerBesoins());
}

function afficherTableEtabs(liste) {
    const tbody = document.getElementById('table-etabs-body');
    if (!tbody) return;
    tbody.innerHTML = "";
    liste.forEach(e => {
        tbody.innerHTML += `<tr>
            <td><code>${e.uai}</code></td>
            <td><strong>${e.nom}</strong></td>
            <td><span class="badge">${e.type}</span></td>
            <td><span class="badge blue">${e.nb_profs} prof(s)</span></td>
            <td>${e.nb_besoins > 0 ? `<span class="badge red">${e.nb_besoins} besoin(s)</span>` : '<span class="badge green">0</span>'}</td>
            <td><button class="btn-small btn" onclick="ouvrirFicheEtab('${e.uai}')">👁️ Voir la fiche</button></td>
        </tr>`;
    });
}

function filtrerTableEtabs(val) {
    const filtre = etablissementsData.filter(e => e.nom.toLowerCase().includes(val.toLowerCase()) || e.uai.toLowerCase().includes(val.toLowerCase()));
    afficherTableEtabs(filtre);
}

function ouvrirFicheEtab(uai) {
    const e = etablissementsData.find(x => x.uai === uai);
    if (!e) return;
    document.getElementById('fe-nom').innerText = e.nom;
    document.getElementById('fe-meta').innerText = `UAI : ${e.uai} | Catégorie : ${e.type} (${e.degre})`;

    fetch(`${API_URL}/ecoles/${uai}/professeurs`).then(r => r.json()).then(profs => {
        const tb = document.getElementById('fe-profs');
        tb.innerHTML = profs.length ? "" : "<tr><td colspan='3'>Aucun professeur enregistré</td></tr>";
        profs.forEach(p => tb.innerHTML += `<tr><td><strong>${p.nom}</strong></td><td>${p.concours}</td><td>${p.heures_poste}h</td></tr>`);
    });

    const tbBesoins = document.getElementById('fe-besoins');
    const bEtab = besoinsData.filter(b => b.uai === uai);
    tbBesoins.innerHTML = bEtab.length ? "" : "<tr><td colspan='4'>Aucun besoin en attente</td></tr>";
    bEtab.forEach(b => tbBesoins.innerHTML += `<tr><td>${b.prof_absent_nom}</td><td>${b.matiere}</td><td>${b.date_debut} ➔ ${b.date_fin}</td><td>${b.heures}h</td></tr>`);

    ouvrirModal('modal-fiche-etab');
}

// --- 4. VIVIER REMPLAÇANTS (TZR & CONTRACTUELS) ---
function chargerRemplacants() {
    fetch(`${API_URL}/remplacants`).then(r => r.json()).then(profs => {
        remplacantsData = profs;
        const tbody = document.getElementById('table-profs-body');
        if (tbody) tbody.innerHTML = "";
        if (layerProfs) layerProfs.clearLayers();

        profs.forEach(p => {
            const matBadges = p.matieres.map(m => `<span class="badge blue">${m}</span>`).join(" ");
            if (tbody) {
                tbody.innerHTML += `<tr>
                    <td><strong>${p.nom}</strong><br><small>${p.telephone || ''} ${p.email || ''}</small></td>
                    <td><span class="badge">${p.statut}</span></td>
                    <td><strong>${p.concours}</strong><br>${matBadges}</td>
                    <td>${p.adresse}</td>
                    <td><span class="badge ${p.heures_restantes > 0 ? 'green' : 'red'}">${p.heures_restantes}h / ${p.heures_max}h</span></td>
                    <td>
                        <button class="btn-small btn" onclick="afficherFicheRemplacant(${p.id})">👁️</button>
                        <button class="btn-small btn-warning" onclick="editerRemplacant(${p.id})">✏️</button>
                        <button class="btn-small btn-danger" onclick="supprimerRemplacant(${p.id})">🗑️</button>
                    </td>
                </tr>`;
            }
            if (p.latitude && layerProfs) {
                L.marker([p.latitude, p.longitude], {
                    icon: L.icon({
                        iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-${p.heures_restantes > 0 ? "green" : "grey"}.png`,
                        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                        iconSize: [25, 41], iconAnchor: [12, 41]
                    })
                }).bindPopup(`<strong>${p.nom} (${p.statut})</strong><br>${p.concours}<br>Dispo : ${p.heures_restantes}h`).addTo(layerProfs);
            }
        });
    });
}

function ouvrirModalRemplacant() {
    document.getElementById('edit-remp-id').value = "";
    document.getElementById('form-remp-title').innerText = "➕ Ajouter un remplaçant";
    ['add-nom', 'add-telephone', 'add-email', 'add-adresse', 'add-lat', 'add-lng'].forEach(id => document.getElementById(id).value = "");
    document.getElementById('add-heures-actuelles').value = 0;
    document.getElementById('add-quotite').value = 100;
    ouvrirModal('modal-remplacant');
}

function updateFormRemplacantUI() {
    const statut = document.getElementById('add-statut').value;
    document.getElementById('label-adresse').innerText = statut === "TZR" ? "Établissement de rattachement (RAD)" : "Adresse personnelle";
}

function chercherAdresseOuRAD(val) {
    const listDiv = document.getElementById('autocomplete-list');
    listDiv.innerHTML = "";
    if (val.length < 3) return;
    if (document.getElementById('add-statut').value === "TZR") {
        etablissementsData.filter(e => e.nom.toLowerCase().includes(val.toLowerCase())).slice(0, 5).forEach(m => {
            const d = document.createElement('div'); d.innerHTML = `<strong>${m.nom}</strong>`;
            d.onclick = () => {
                document.getElementById('add-adresse').value = m.nom;
                document.getElementById('add-lat').value = m.latitude;
                document.getElementById('add-lng').value = m.longitude;
                listDiv.innerHTML = "";
            };
            listDiv.appendChild(d);
        });
    } else {
        clearTimeout(autocompleteTimeout);
        autocompleteTimeout = setTimeout(() => {
            fetch(`https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(val)}&autocomplete=1&limit=5`)
                .then(r => r.json()).then(data => {
                    if (data.features) data.features.forEach(f => {
                        const d = document.createElement('div'); d.innerHTML = `<strong>${f.properties.label}</strong>`;
                        d.onclick = () => {
                            document.getElementById('add-adresse').value = f.properties.label;
                            document.getElementById('add-lng').value = f.geometry.coordinates[0];
                            document.getElementById('add-lat').value = f.geometry.coordinates[1];
                            listDiv.innerHTML = "";
                        };
                        listDiv.appendChild(d);
                    });
                });
        }, 300);
    }
}

function sauvegarderRemplacant() {
    const lat = document.getElementById('add-lat').value;
    if (!lat) return alert("Veuillez sélectionner un établissement ou une adresse dans la liste déroulante.");
    const rempId = document.getElementById('edit-remp-id').value;
    const method = rempId ? 'PUT' : 'POST';
    const url = rempId ? `${API_URL}/remplacants/${rempId}` : `${API_URL}/remplacants`;

    const body = {
        nom: document.getElementById('add-nom').value,
        statut: document.getElementById('add-statut').value,
        concours_id: parseInt(document.getElementById('add-concours').value),
        adresse_libelle: document.getElementById('add-adresse').value,
        type_adresse: document.getElementById('add-statut').value === "TZR" ? "Rattachement" : "Personnelle",
        latitude: parseFloat(lat),
        longitude: parseFloat(document.getElementById('add-lng').value),
        quotite: parseFloat(document.getElementById('add-quotite').value),
        heures_actuelles: parseFloat(document.getElementById('add-heures-actuelles').value),
        telephone: document.getElementById('add-telephone').value,
        email: document.getElementById('add-email').value
    };
    fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(() => { fermerModal('modal-remplacant'); chargerRemplacants(); });
}

function editerRemplacant(id) {
    const p = remplacantsData.find(x => x.id === id);
    if (!p) return;
    document.getElementById('edit-remp-id').value = p.id;
    document.getElementById('form-remp-title').innerText = `✏️ Modifier : ${p.nom}`;
    document.getElementById('add-nom').value = p.nom;
    document.getElementById('add-statut').value = p.statut;
    document.getElementById('add-concours').value = p.concours_id;
    document.getElementById('add-quotite').value = p.quotite;
    document.getElementById('add-telephone').value = p.telephone || "";
    document.getElementById('add-email').value = p.email || "";
    document.getElementById('add-heures-actuelles').value = p.heures_actuelles;
    document.getElementById('add-adresse').value = p.adresse;
    document.getElementById('add-lat').value = p.latitude;
    document.getElementById('add-lng').value = p.longitude;
    ouvrirModal('modal-remplacant');
}

function importerRemplacantsCSV() {
    const csv_text = document.getElementById('csv-remplacants').value;
    fetch(`${API_URL}/remplacants/import`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv_text })
    }).then(r => r.json()).then(res => {
        alert(`${res.ajoutes} remplaçants importés avec succès.`);
        fermerModal('modal-import-remplacants');
        chargerRemplacants();
    });
}

function supprimerRemplacant(id) {
    if (confirm("Supprimer cette fiche remplaçant ?")) fetch(`${API_URL}/remplacants/${id}`, { method: 'DELETE' }).then(() => chargerRemplacants());
}

function afficherFicheRemplacant(id) {
    const p = remplacantsData.find(x => x.id === id);
    if (!p) return;
    document.getElementById('fr-nom').innerText = p.nom;
    document.getElementById('fr-badges').innerHTML = `<span class="badge">${p.statut}</span> <span class="badge blue">${p.concours}</span> <span class="badge green">Dispo : ${p.heures_restantes}h / ${p.heures_max}h</span>`;
    document.getElementById('fr-email').innerText = p.email || '-';
    document.getElementById('fr-tel').innerText = p.telephone || '-';
    document.getElementById('fr-adresse').innerText = p.adresse;
    document.getElementById('fr-matieres').innerHTML = p.matieres.map(m => `<span class="badge blue">${m}</span>`).join(" ");

    fetch(`${API_URL}/remplacants/${id}/historique`).then(r => r.json()).then(hist => {
        const tb = document.getElementById('fr-historique');
        tb.innerHTML = hist.length ? "" : "<tr><td colspan='5'>Aucune affectation</td></tr>";
        hist.forEach(h => tb.innerHTML += `<tr><td>${h.date_debut} ➔ ${h.date_fin}</td><td><strong>${h.etablissement}</strong></td><td>${h.prof_remplace}</td><td>${h.discipline}</td><td>${h.heures}h</td></tr>`);
        ouvrirModal('modal-fiche-remp');
    });
}

// --- 5. CARTE & MATCHING DU PLUS PROCHE AU PLUS ÉLOIGNÉ ---
function initMap() {
    if (!map) {
        map = L.map('map').setView([48.793, 2.396], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', { maxZoom: 20 }).addTo(map);
        layerPrimaire = L.featureGroup().addTo(map);
        layerSecondaire = L.featureGroup().addTo(map);
        layerProfs = L.featureGroup().addTo(map);
        L.control.layers(null, {
            "🏫 Écoles primaires": layerPrimaire,
            "🎓 Collèges & Lycées": layerSecondaire,
            "👨‍🏫 Remplaçants (TZR/Contractuels)": layerProfs
        }, { position: 'topright' }).addTo(map);
        chargerCarteEtablissements();
        chargerRemplacants();
    }
    setTimeout(() => map.invalidateSize(), 200);
}

function chargerCarteEtablissements() {
    if (!layerPrimaire) return;
    layerPrimaire.clearLayers();
    layerSecondaire.clearLayers();
    etablissementsData.forEach(etab => {
        if (etab.degre === "Autre") return;
        L.marker([etab.latitude, etab.longitude], {
            icon: L.icon({
                iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-${etab.degre === "Secondaire" ? "red" : "blue"}.png`,
                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                iconSize: [25, 41], iconAnchor: [12, 41]
            })
        }).bindPopup(`<strong>${etab.nom}</strong><br>UAI : ${etab.uai}`).addTo(etab.degre === "Secondaire" ? layerSecondaire : layerPrimaire);
    });
}

function lancerMatching(besoin_id, lat, lng, nomEtab, matiere, heures, profAbsent) {
    besoinActifContext = besoin_id;
    switchTab('map');
    setTimeout(() => map.setView([lat, lng], 14), 250);

    fetch(`${API_URL}/match?besoin_id=${besoin_id}`).then(r => r.json()).then(profs => {
        const box = document.getElementById('search-results');
        let html = `<div style="background:#f0f4f8; padding:12px; border-radius:6px; border-left:4px solid var(--primary); margin-bottom:15px;">
            <strong>${nomEtab}</strong><br>
            Remplacement de : <b>${profAbsent}</b><br>
            Matière : <span class="badge blue">${matiere}</span> (<b>${heures}h</b>)
        </div>`;

        if (profs.length === 0) {
            html += `<p style="color:var(--danger); font-weight:bold;">Aucun remplaçant disponible habilité pour cette matière avec ${heures}h libres.</p>`;
        } else {
            html += `<p style="font-size:12px; color:#555;">Classés du plus proche au plus éloigné :</p>`;
            profs.forEach((p, idx) => {
                html += `<div class="card" style="padding:12px; margin-bottom:10px; border:1px solid #ddd;">
                    <div style="display:flex; justify-content:space-between;">
                        <strong>#${idx + 1} ${p.nom}</strong>
                        <span class="badge orange">📍 ${p.distance_km} km</span>
                    </div>
                    <small>${p.statut} — ${p.concours}</small><br>
                    <small>Rattachement : ${p.adresse}</small><br>
                    <span class="badge green" style="margin-top:5px;">Disponibilité : ${p.heures_restantes}h</span>
                    <button class="btn btn-success" style="width:100%; margin-top:8px;" onclick="validerAffectation(${p.id})">✅ Affecter ce professeur</button>
                </div>`;
            });
        }
        box.innerHTML = html;
    });
}

function validerAffectation(remplacant_id) {
    fetch(`${API_URL}/affecter`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remplacant_id, besoin_id: besoinActifContext })
    }).then(() => {
        document.getElementById('search-results').innerHTML = `<div class="card" style="background:#d4edda; color:#155724;">✅ Affectation enregistrée avec succès !</div>`;
        chargerBesoins();
        chargerAffectations();
        chargerRemplacants();
        chargerEtablissements();
    });
}

// --- 6. HISTORIQUE DES AFFECTATIONS ---
function chargerAffectations() {
    fetch(`${API_URL}/affectations`).then(r => r.json()).then(data => {
        affectationsData = data;
        const tbody = document.getElementById('table-affectations-body');
        if (!tbody) return;
        tbody.innerHTML = "";
        data.forEach(a => {
            tbody.innerHTML += `<tr>
                <td><strong>${a.nom_prof}</strong></td>
                <td>${a.nom_etablissement}</td>
                <td>${a.prof_remplace}</td>
                <td><span class="badge blue">${a.discipline}</span></td>
                <td>${a.date_debut} ➔ ${a.date_fin}</td>
                <td><strong>${a.heures}h</strong></td>
                <td>
                    <button class="btn-small btn-warning" onclick="ouvrirEditAff(${a.id}, '${a.nom_prof.replace(/'/g, "\\'")}', ${a.heures}, '${a.date_debut}', '${a.date_fin}')">✏️</button>
                    <button class="btn-small btn-danger" onclick="supprimerAffectation(${a.id})">🗑️</button>
                </td>
            </tr>`;
        });
    });
}

function ouvrirEditAff(id, nomProf, heures, debut, fin) {
    document.getElementById('edit-aff-id').value = id;
    document.getElementById('edit-aff-titre').innerText = nomProf;
    document.getElementById('edit-aff-heures').value = heures;
    document.getElementById('edit-aff-debut').value = debut;
    document.getElementById('edit-aff-fin').value = fin;
    ouvrirModal('modal-edit-aff');
}

function sauvegarderModifAffectation() {
    const id = document.getElementById('edit-aff-id').value;
    const body = {
        heures: parseFloat(document.getElementById('edit-aff-heures').value),
        date_debut: document.getElementById('edit-aff-debut').value,
        date_fin: document.getElementById('edit-aff-fin').value
    };
    fetch(`${API_URL}/affectations/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(() => { fermerModal('modal-edit-aff'); chargerAffectations(); chargerRemplacants(); });
}

function supprimerAffectation(id) {
    if (confirm("Annuler cette affectation et restituer les heures au remplaçant ?")) {
        fetch(`${API_URL}/affectations/${id}`, { method: 'DELETE' }).then(() => { chargerAffectations(); chargerRemplacants(); });
    }
}