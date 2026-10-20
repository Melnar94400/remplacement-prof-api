const API_URL = "https://remplacement-prof-api.onrender.com/api";

let referentiel = { concours: [], matieres: [], liaisons: [] };
let etablissementsData = [];
let remplacantsData = [];
let besoinsData = [];
let affectationsData = [];
let ecoleConnectee = null;
let matieresEcoleActuelle = [];
let postesEcoleActuelle = [];
let besoinActifContext = null;
let autocompleteTimeout = null;

// Couches de la carte dédiées au besoin sélectionné
let map, layerBesoinsEtabs, layerFocusEtab, layerFocusProfs, layerItineraire;
let candidatsMatchingActuels = [];
let ecoleMatchingActuelle = null;

function esc(str) {
    return String(str || '').replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

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
    if (tabId === 'besoins') {
        initMap();
    }
}

// --- 1. CHARGEMENT DU RÉFÉRENTIEL OFFICIEL (RECTORAT) ---
function chargerReferentiel() {
    fetch(`${API_URL}/referentiel`).then(r => r.json()).then(data => {
        referentiel = data;
        remplirSelectsReferentiel();
        afficherTableReferentiel();
    });
}

function remplirSelectsReferentiel() {
    ['add-concours', 'ref-select-concours'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = "";
        referentiel.concours.forEach(c => el.appendChild(new Option(`${c.intitule} (${c.heures}h)`, c.id)));
    });

    ['ref-select-matiere', 'res-select-officielle'].forEach(id => {
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

// --- 2. ESPACE ÉTABLISSEMENT (COMPTE ÉCOLE, MATIÈRES & POSTES) ---
function chargerEtablissements() {
    fetch(`${API_URL}/etablissements`).then(r => r.json()).then(data => {
        etablissementsData = data;
        afficherTableEtabs(data);
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

    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/matieres`).then(r => r.json()).then(mats => {
        matieresEcoleActuelle = mats;
        const tbMat = document.getElementById('ecole-table-matieres');
        const selMatPoste = document.getElementById('pe-matiere');
        const dlMat = document.getElementById('datalist-matieres-ecole');
        tbMat.innerHTML = "";
        selMatPoste.innerHTML = "";
        dlMat.innerHTML = "";

        mats.forEach(m => {
            tbMat.innerHTML += `<tr>
                <td><strong>${m.nom}</strong></td>
                <td>
                    <button class="btn-small btn-warning" onclick="ecoleRenommerMatiere(${m.id}, '${esc(m.nom)}')">✏️</button>
                    <button class="btn-small btn-danger" onclick="ecoleSupprimerMatiere(${m.id})">🗑️</button>
                </td>
            </tr>`;
            selMatPoste.appendChild(new Option(m.nom, m.nom));
            dlMat.appendChild(new Option(m.nom, m.nom));
        });
    });

    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs`).then(r => r.json()).then(postes => {
        postesEcoleActuelle = postes;
        const tbody = document.getElementById('ecole-table-postes');
        const selPoste = document.getElementById('ecole-besoin-poste');
        tbody.innerHTML = "";
        selPoste.innerHTML = `<option value="">-- Choisir un poste ou saisir la matière ci-dessous --</option>`;

        postes.forEach(p => {
            tbody.innerHTML += `<tr>
                <td><span class="badge blue">${p.matiere_ecole}</span></td>
                <td><strong>${p.heures_poste}h</strong></td>
                <td><button class="btn-small btn-danger" onclick="ecoleSupprimerPoste(${p.id})">🗑️</button></td>
            </tr>`;
            selPoste.appendChild(new Option(`${p.matiere_ecole} (${p.heures_poste}h)`, p.id));
        });
        if (postes.length > 0) {
            selPoste.value = postes[0].id;
            autoRemplirDepuisPosteEcole();
        }
    });

    Promise.all([
        fetch(`${API_URL}/besoins`).then(r => r.json()),
        fetch(`${API_URL}/affectations`).then(r => r.json())
    ]).then(([besoins, affectations]) => {
        const tbody = document.getElementById('ecole-table-suivi');
        tbody.innerHTML = "";
        besoins.filter(b => b.uai === ecoleConnectee.uai).forEach(b => {
            const matAffichee = b.matiere || b.matiere_declaree || '-';
            tbody.innerHTML += `<tr>
                <td><strong>${matAffichee}</strong> ${b.reconnue === false ? '<span class="badge orange">Qualification Rectorat en cours</span>' : ''}</td>
                <td>${b.motif || 'Absence'}</td>
                <td>${b.date_debut} ➔ ${b.date_fin}</td>
                <td><strong>${b.heures}h</strong></td>
                <td><span class="badge red">⏳ En attente Rectorat</span></td>
            </tr>`;
        });
        affectations.filter(a => a.uai === ecoleConnectee.uai).forEach(a => {
            tbody.innerHTML += `<tr>
                <td><strong>${a.discipline}</strong></td>
                <td>Remplacement affecté</td>
                <td>${a.date_debut} ➔ ${a.date_fin}</td>
                <td><strong>${a.heures}h</strong></td>
                <td><span class="badge green">✅ Couvert par ${a.nom_prof}</span></td>
            </tr>`;
        });
    });
}

function ecoleAjouterMatiere() {
    const nom = document.getElementById('ecole-new-matiere').value.trim();
    if (!nom) return;
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/matieres`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nom })
    }).then(() => {
        document.getElementById('ecole-new-matiere').value = "";
        chargerDonneesEcoleConnectee();
    });
}

function ecoleRenommerMatiere(mat_id, ancienNom) {
    const nouveau = prompt("Modifier l'intitulé de la matière dans l'établissement :", ancienNom);
    if (!nouveau || nouveau.trim() === ancienNom) return;
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/matieres/${mat_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nom: nouveau.trim() })
    }).then(() => chargerDonneesEcoleConnectee());
}

function ecoleSupprimerMatiere(mat_id) {
    if (confirm("Supprimer cette matière de votre établissement ?")) {
        fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/matieres/${mat_id}`, { method: 'DELETE' })
            .then(() => chargerDonneesEcoleConnectee());
    }
}

function autoRemplirDepuisPosteEcole() {
    const posteId = parseInt(document.getElementById('ecole-besoin-poste').value);
    const poste = postesEcoleActuelle.find(p => p.id === posteId);
    if (poste) {
        document.getElementById('ecole-besoin-heures').value = poste.heures_poste;
        document.getElementById('ecole-besoin-matiere').value = poste.matiere_ecole;
    }
}

function ecoleAjouterPoste() {
    const data = {
        matiere_ecole: document.getElementById('pe-matiere').value,
        heures_poste: parseFloat(document.getElementById('pe-heures').value)
    };
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    }).then(() => {
        fermerModal('modal-add-poste-ecole');
        chargerDonneesEcoleConnectee();
    });
}

function ecoleImporterCSV() {
    const csv_text = document.getElementById('csv-postes-ecole').value;
    fetch(`${API_URL}/ecoles/${ecoleConnectee.uai}/professeurs/import`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv_text })
    }).then(r => r.json()).then(res => {
        alert(`${res.ajoutes} poste(s) importé(s) avec succès.`);
        fermerModal('modal-import-postes-ecole');
        chargerDonneesEcoleConnectee();
    });
}

function ecoleSupprimerPoste(id) {
    if (confirm("Supprimer ce poste de l'établissement ?")) {
        fetch(`${API_URL}/ecoles/professeurs/${id}`, { method: 'DELETE' }).then(() => chargerDonneesEcoleConnectee());
    }
}

function ecoleDeclarerBesoin() {
    const valPoste = document.getElementById('ecole-besoin-poste').value;
    const prof_absent_id = valPoste ? parseInt(valPoste) : null;
    const matiere_declaree = document.getElementById('ecole-besoin-matiere').value.trim();
    if (!matiere_declaree) return alert("Veuillez indiquer la matière à assurer.");

    const data = {
        uai: ecoleConnectee.uai,
        prof_absent_id: prof_absent_id,
        matiere_declaree: matiere_declaree,
        heures: parseFloat(document.getElementById('ecole-besoin-heures').value),
        date_debut: document.getElementById('ecole-besoin-debut').value,
        date_fin: document.getElementById('ecole-besoin-fin').value,
        motif: document.getElementById('ecole-besoin-motif').value
    };
    fetch(`${API_URL}/besoins`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    }).then(r => {
        if (!r.ok) throw new Error("Erreur lors de l'enregistrement du besoin.");
        return r.json();
    }).then(() => {
        alert("Alerte transmise au Rectorat !");
        chargerDonneesEcoleConnectee();
    }).catch(err => alert(err.message));
}

// --- 3. ESPACE RECTORAT : INTERFACE UNIFIÉE BESOINS + CARTE ---
function loginRectorat() {
    document.getElementById('menu-rectorat').style.display = "flex";
    switchTab('besoins');
    retourListeBesoins();
    chargerReferentiel();
    chargerBesoins();
    chargerEtablissements();
    chargerRemplacants();
    chargerAffectations();
}

function initMap() {
    if (!map) {
        map = L.map('map').setView([48.793, 2.396], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', { maxZoom: 20 }).addTo(map);
        layerBesoinsEtabs = L.featureGroup().addTo(map);
        layerFocusEtab = L.featureGroup().addTo(map);
        layerFocusProfs = L.featureGroup().addTo(map);
        layerItineraire = L.featureGroup().addTo(map);
    }
    setTimeout(() => map.invalidateSize(), 200);
}

function chargerBesoins() {
    fetch(`${API_URL}/besoins`).then(r => r.json()).then(besoins => {
        if (!Array.isArray(besoins)) return;
        besoinsData = besoins;
        const container = document.getElementById('liste-besoins-cards');
        container.innerHTML = "";
        let nbNouveaux = 0;

        if (besoins.length === 0) {
            container.innerHTML = `<p style="color:#666; font-size:13px; text-align:center; margin-top:30px;">🎉 Aucun besoin de remplacement en attente.</p>`;
        }

        besoins.forEach(b => {
            if (!b.vu_rectorat) nbNouveaux++;
            
            const matOfficielle = b.matiere_officielle || b.matiere || "";
            const matDeclaree = b.matiere_declaree || b.matiere || "";
            const estReconnue = (b.reconnue !== undefined) ? b.reconnue : (b.matiere_id != null);

            let matiereHtml = "";
            let boutonAction = "";

            if (estReconnue) {
                matiereHtml = `<span class="badge blue">✅ ${matOfficielle}</span>
                               <button class="btn-small btn-warning" title="Modifier la matière" onclick="ouvrirModalResoudreMatiere(${b.id}, '${esc(matDeclaree)}')">✏️</button>`;
                boutonAction = `<button class="btn-small btn" style="padding:6px 10px;" onclick="lancerMatching(${b.id}, ${b.latitude}, ${b.longitude}, '${esc(b.nom_etablissement)}', '${esc(matOfficielle)}', ${b.heures})">🔍 Afficher remplaçants & carte</button>`;
            } else {
                matiereHtml = `<span class="badge orange">⚠️ Non reconnue : "${matDeclaree}"</span>`;
                boutonAction = `<button class="btn-small btn-warning" style="padding:6px 10px;" onclick="ouvrirModalResoudreMatiere(${b.id}, '${esc(matDeclaree)}')">🔧 Qualifier la matière</button>`;
            }

            container.innerHTML += `<div class="besoin-card ${!b.vu_rectorat ? 'unseen' : ''}">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">
                    <strong>🏫 ${b.nom_etablissement}</strong>
                    ${!b.vu_rectorat ? '<span class="badge red">🔔 NOUVEAU</span>' : ''}
                </div>
                <div style="margin-bottom:6px;">
                    ${matiereHtml} <span class="badge">⏱️ ${b.heures}h/sem</span>
                </div>
                <div style="font-size:12px; color:#555; margin-bottom:10px;">
                    📅 ${b.date_debut} ➔ ${b.date_fin} &nbsp;|&nbsp; 💬 ${b.motif || 'Absence'}
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    ${boutonAction}
                    <button class="btn-small btn-danger" onclick="supprimerBesoin(${b.id})" title="Supprimer ce besoin">🗑️</button>
                </div>
            </div>`;
        });

        const badge = document.getElementById('alert-badge');
        if (nbNouveaux > 0) { badge.style.display = "inline-block"; badge.innerText = nbNouveaux; }
        else { badge.style.display = "none"; }

        if (document.getElementById('panel-liste-besoins').style.display !== 'none') {
            afficherCarteBesoinsGenerale();
        }
    });
}

function afficherCarteBesoinsGenerale() {
    if (!map || !layerBesoinsEtabs) return;
    layerBesoinsEtabs.clearLayers();
    layerFocusEtab.clearLayers();
    layerFocusProfs.clearLayers();
    layerItineraire.clearLayers();

    const markers = [];
    besoinsData.forEach(b => {
        if (!b.latitude || !b.longitude) return;
        const matOfficielle = b.matiere_officielle || b.matiere || b.matiere_declaree || "";
        const estReconnue = (b.reconnue !== undefined) ? b.reconnue : (b.matiere_id != null);

        const m = L.marker([b.latitude, b.longitude], {
            icon: L.icon({
                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                iconSize: [25, 41], iconAnchor: [12, 41]
            })
        }).bindPopup(`<strong>${b.nom_etablissement}</strong><br>Besoin : ${matOfficielle} (${b.heures}h)`).addTo(layerBesoinsEtabs);

        if (estReconnue) {
            m.on('click', () => lancerMatching(b.id, b.latitude, b.longitude, b.nom_etablissement, matOfficielle, b.heures));
        }
        markers.push(m);
    });

    if (markers.length > 0) {
        map.fitBounds(L.featureGroup(markers).getBounds(), { padding: [50, 50], maxZoom: 14 });
    } else {
        map.setView([48.793, 2.396], 13);
    }
}

function retourListeBesoins() {
    document.getElementById('panel-matching-profs').style.display = "none";
    document.getElementById('panel-liste-besoins').style.display = "block";
    afficherCarteBesoinsGenerale();
}

function ouvrirModalResoudreMatiere(besoin_id, matiereDeclaree) {
    document.getElementById('res-besoin-id').value = besoin_id;
    document.getElementById('res-matiere-declaree').innerText = matiereDeclaree;
    document.getElementById('res-nouveau-nom').value = matiereDeclaree;

    remplirSelectsReferentiel();

    const boxConcours = document.getElementById('res-liste-concours');
    boxConcours.innerHTML = "";
    referentiel.concours.forEach(c => {
        boxConcours.innerHTML += `<label class="checkbox-item">
            <input type="checkbox" class="res-concours-cb" value="${c.id}" style="width:auto;">
            <span><strong>${c.intitule}</strong> (${c.type})</span>
        </label>`;
    });

    ouvrirModal('modal-resoudre-matiere');
}

function validerResolutionMatiere(mode) {
    const besoin_id = parseInt(document.getElementById('res-besoin-id').value);
    let payload = { mode };

    if (mode === 'associer') {
        payload.matiere_id = parseInt(document.getElementById('res-select-officielle').value);
        payload.corriger_ecole = document.getElementById('res-corriger-ecole').checked;
    } else {
        const nouveau_nom = document.getElementById('res-nouveau-nom').value.trim();
        if (!nouveau_nom) return alert("Veuillez saisir le nom officiel de la matière.");
        const concours_ids = Array.from(document.querySelectorAll('.res-concours-cb:checked')).map(cb => parseInt(cb.value));
        if (concours_ids.length === 0) return alert("Veuillez cocher au moins un concours habilité à enseigner cette matière.");
        payload.nouveau_nom = nouveau_nom;
        payload.concours_ids = concours_ids;
    }

    fetch(`${API_URL}/besoins/${besoin_id}/resoudre-matiere`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(() => {
        fermerModal('modal-resoudre-matiere');
        chargerReferentiel();
        chargerBesoins();
        chargerRemplacants();
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
        const nbPostes = e.nb_postes !== undefined ? e.nb_postes : (e.nb_profs || 0);
        const totHeures = e.total_heures !== undefined ? `${e.total_heures}h` : '';
        tbody.innerHTML += `<tr>
            <td><code>${e.uai}</code></td>
            <td><strong>${e.nom}</strong></td>
            <td><span class="badge">${e.type}</span></td>
            <td><span class="badge blue">${nbPostes} poste(s) ${totHeures ? '— ' + totHeures : ''}</span></td>
            <td>${e.nb_besoins > 0 ? `<span class="badge red">${e.nb_besoins} besoin(s)</span>` : '<span class="badge green">0</span>'}</td>
            <td><button class="btn-small btn" onclick="ouvrirFicheEtab('${esc(e.uai)}')">👁️ Voir les postes</button></td>
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
    const nbPostes = e.nb_postes !== undefined ? e.nb_postes : (e.nb_profs || 0);
    const totHeures = e.total_heures !== undefined ? `${e.total_heures}h` : '';
    document.getElementById('fe-nom').innerText = e.nom;
    document.getElementById('fe-meta').innerText = `UAI : ${e.uai} | Catégorie : ${e.type} (${e.degre}) | Dotation : ${nbPostes} poste(s) ${totHeures}`;

    fetch(`${API_URL}/ecoles/${uai}/professeurs`).then(r => r.json()).then(postes => {
        const tb = document.getElementById('fe-postes');
        tb.innerHTML = postes.length ? "" : "<tr><td colspan='2'>Aucun poste renseigné</td></tr>";
        postes.forEach(p => tb.innerHTML += `<tr><td><span class="badge blue">${p.matiere_ecole}</span></td><td><strong>${p.heures_poste}h</strong></td></tr>`);
    });

    const tbBesoins = document.getElementById('fe-besoins');
    const bEtab = besoinsData.filter(b => b.uai === uai);
    tbBesoins.innerHTML = bEtab.length ? "" : "<tr><td colspan='4'>Aucun besoin en attente</td></tr>";
    bEtab.forEach(b => tbBesoins.innerHTML += `<tr><td><strong>${b.matiere || b.matiere_declaree}</strong></td><td>${b.motif || 'Absence'}</td><td>${b.date_debut} ➔ ${b.date_fin}</td><td><strong>${b.heures}h</strong></td></tr>`);

    ouvrirModal('modal-fiche-etab');
}

// --- 4. VIVIER REMPLAÇANTS (TZR & CONTRACTUELS) ---
function chargerRemplacants() {
    fetch(`${API_URL}/remplacants`).then(r => r.json()).then(profs => {
        remplacantsData = profs;
        const tbody = document.getElementById('table-profs-body');
        if (!tbody) return;
        tbody.innerHTML = "";

        profs.forEach(p => {
            const matBadges = (p.matieres || []).map(m => `<span class="badge blue">${m}</span>`).join(" ");
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
    document.getElementById('fr-matieres').innerHTML = (p.matieres || []).map(m => `<span class="badge blue">${m}</span>`).join(" ");

    fetch(`${API_URL}/remplacants/${id}/historique`).then(r => r.json()).then(hist => {
        const tb = document.getElementById('fr-historique');
        tb.innerHTML = hist.length ? "" : "<tr><td colspan='4'>Aucune affectation</td></tr>";
        hist.forEach(h => tb.innerHTML += `<tr><td>${h.date_debut} ➔ ${h.date_fin}</td><td><strong>${h.etablissement}</strong></td><td><span class="badge blue">${h.discipline}</span></td><td><strong>${h.heures}h</strong></td></tr>`);
        ouvrirModal('modal-fiche-remp');
    });
}

// --- 5. MATCHING CIBLÉ : AFFICHE UNIQUEMENT L'ÉCOLE ET LES REMPLAÇANTS COMPATIBLES ---
async function calculerTempsOSRM(profil, lat1, lng1, lat2, lng2) {
    const serveur = profil === 'car' ? 'routed-car' : (profil === 'bike' ? 'routed-bike' : 'routed-foot');
    const url = `https://routing.openstreetmap.de/${serveur}/route/v1/driving/${lng1},${lat1};${lng2},${lat2}?overview=full&geometries=geojson`;
    try {
        const r = await fetch(url);
        const data = await r.json();
        if (data.routes && data.routes.length > 0) {
            let minutes = Math.round(data.routes[0].duration / 60);
            if (profil === 'car') minutes = Math.round(minutes * 1.35) + 3;
            return { minutes: Math.max(1, minutes), geometry: data.routes[0].geometry };
        }
    } catch (e) { console.warn("Erreur OSRM", profil, e); }
    return { minutes: null, geometry: null };
}

function genererLienGoogleTransit8h(lat1, lng1, lat2, lng2, timestamp8h) {
    if (timestamp8h) {
        return `https://www.google.com/maps/dir/${lat1},${lng1}/${lat2},${lng2}/data=!4m6!4m5!2m3!6e1!7e2!8j${timestamp8h}!3e3`;
    }
    return `https://www.google.com/maps/dir/?api=1&origin=${lat1},${lng1}&destination=${lat2},${lng2}&travelmode=transit`;
}

async function lancerMatching(besoin_id, lat, lng, nomEtab, matiere, heures) {
    besoinActifContext = besoin_id;
    ecoleMatchingActuelle = { lat, lng, nomEtab, matiere, heures };

    document.getElementById('panel-liste-besoins').style.display = "none";
    document.getElementById('panel-matching-profs').style.display = "block";

    initMap();
    layerBesoinsEtabs.clearLayers();
    layerFocusEtab.clearLayers();
    layerFocusProfs.clearLayers();
    layerItineraire.clearLayers();

    const markerEcole = L.marker([lat, lng], {
        icon: L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
            iconSize: [25, 41], iconAnchor: [12, 41]
        })
    }).bindPopup(`<strong>🏫 ${nomEtab}</strong><br>Besoin : ${matiere} (${heures}h)`).addTo(layerFocusEtab);
    markerEcole.openPopup();
    map.setView([lat, lng], 14);

    const box = document.getElementById('search-results');
    box.innerHTML = `<p>⏳ Recherche des enseignants disponibles et calcul des temps de trajet (arrivée 8h00)...</p>`;

    const profs = await fetch(`${API_URL}/match?besoin_id=${besoin_id}`).then(r => r.json());
    candidatsMatchingActuels = Array.isArray(profs) ? profs : [];

    if (candidatsMatchingActuels.length === 0) {
        box.innerHTML = `<div style="background:#f0f4f8; padding:12px; border-radius:6px; border-left:4px solid var(--primary); margin-bottom:15px;">
            <strong>🏫 ${nomEtab}</strong><br>Matière : <span class="badge blue">${matiere}</span> (<b>${heures}h</b>)
        </div>
        <p style="color:var(--danger); font-weight:bold;">Aucun remplaçant disponible habilité pour cette matière avec ${heures}h libres.</p>`;
        return;
    }

    const tousLesMarqueurs = [markerEcole];
    candidatsMatchingActuels.forEach(p => {
        if (p.latitude && p.longitude) {
            const mp = L.marker([p.latitude, p.longitude], {
                icon: L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                    iconSize: [25, 41], iconAnchor: [12, 41]
                })
            }).bindPopup(`<strong>👨‍🏫 ${p.nom} (${p.statut})</strong><br>${p.concours}<br>Départ : ${p.adresse}<br>Dispo : ${p.heures_restantes}h`).addTo(layerFocusProfs);
            tousLesMarqueurs.push(mp);
        }
    });

    map.fitBounds(L.featureGroup(tousLesMarqueurs).getBounds(), { padding: [50, 50], maxZoom: 14 });

    await Promise.all(candidatsMatchingActuels.map(async (p) => {
        const [car, bike, foot] = await Promise.all([
            calculerTempsOSRM('car', p.latitude, p.longitude, lat, lng),
            calculerTempsOSRM('bike', p.latitude, p.longitude, lat, lng),
            calculerTempsOSRM('foot', p.latitude, p.longitude, lat, lng)
        ]);
        p.car_min = car.minutes; p.car_geom = car.geometry;
        p.bike_min = bike.minutes; p.bike_geom = bike.geometry;
        p.foot_min = foot.minutes; p.foot_geom = foot.geometry;

        if (p.tc_minutes === null || p.tc_minutes === undefined) {
            p.tc_estime = Math.round(8 + (p.distance_km * 3.8));
        } else {
            p.tc_estime = p.tc_minutes;
        }
    }));

    afficherCandidatsTries('distance');
}

function afficherCandidatsTries(critereTri) {
    const { lat, lng, nomEtab, matiere, heures } = ecoleMatchingActuelle;
    const box = document.getElementById('search-results');

    const liste = [...candidatsMatchingActuels].sort((a, b) => {
        if (critereTri === 'tc') return (a.tc_estime || 999) - (b.tc_estime || 999);
        if (critereTri === 'car') return (a.car_min || 999) - (b.car_min || 999);
        if (critereTri === 'bike') return (a.bike_min || 999) - (b.bike_min || 999);
        if (critereTri === 'foot') return (a.foot_min || 999) - (b.foot_min || 999);
        return a.distance_km - b.distance_km;
    });

    const dateRef = (liste[0] && liste[0].tc_date_label) ? liste[0].tc_date_label : "Jour d'école à 08h00";

    let html = `<div style="background:#f0f4f8; padding:12px; border-radius:6px; border-left:4px solid var(--primary); margin-bottom:12px;">
        <strong>🏫 ${nomEtab}</strong><br>
        Matière : <span class="badge blue">${matiere}</span> (<b>${heures}h</b>)<br>
        <small style="color:#444;">🕒 Réf. horaires : <b>${dateRef}</b></small>
    </div>
    <div class="form-group" style="margin-bottom:15px;">
        <label>Trier les remplaçants par :</label>
        <select onchange="afficherCandidatsTries(this.value)" style="font-weight:bold;">
            <option value="distance" ${critereTri==='distance'?'selected':''}>📍 Distance vol d'oiseau</option>
            <option value="tc" ${critereTri==='tc'?'selected':''}>🚇 Transports en commun (Arrivée 8h00)</option>
            <option value="car" ${critereTri==='car'?'selected':''}>🚗 Voiture (Trafic 8h00)</option>
            <option value="bike" ${critereTri==='bike'?'selected':''}>🚲 Vélo</option>
            <option value="foot" ${critereTri==='foot'?'selected':''}>🚶 À pied</option>
        </select>
    </div>
    <p style="font-size:11px; color:#666; margin-top:-8px;">💡 Cliquez sur 🚗, 🚲 ou 🚶 pour tracer l'itinéraire sur la carte.</p>`;

    liste.forEach((p, idx) => {
        const lienTC = genererLienGoogleTransit8h(p.latitude, p.longitude, lat, lng, p.tc_timestamp_8h);
        const labelTC = p.tc_minutes !== null && p.tc_minutes !== undefined
            ? `🚇 <b>${p.tc_minutes} min</b> <small>(${p.tc_lignes})</small>`
            : `🚇 ~<b>${p.tc_estime} min</b> <small>(Estimé)</small>`;

        html += `<div class="card" style="padding:12px; margin-bottom:12px; border:1px solid #ddd;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong>#${idx + 1} ${p.nom}</strong>
                <span class="badge orange">📍 ${p.distance_km} km</span>
            </div>
            <small>${p.statut} — ${p.concours}</small><br>
            <small>Départ (${p.statut === 'TZR' ? 'RAD' : 'Domicile'}) : <b>${p.adresse}</b></small>

            <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:4px; margin:8px 0; text-align:center;">
                <button class="badge" style="border:1px solid #ccc; cursor:pointer; background:#fff;" onclick="tracerItineraire(${p.id}, 'car')" title="Tracer le trajet voiture">
                    🚗 ${p.car_min ? p.car_min + ' min' : '-'}
                </button>
                <button class="badge" style="border:1px solid #ccc; cursor:pointer; background:#fff;" onclick="tracerItineraire(${p.id}, 'bike')" title="Tracer le trajet vélo">
                    🚲 ${p.bike_min ? p.bike_min + ' min' : '-'}
                </button>
                <button class="badge" style="border:1px solid #ccc; cursor:pointer; background:#fff;" onclick="tracerItineraire(${p.id}, 'foot')" title="Tracer le trajet à pied">
                    🚶 ${p.foot_min ? p.foot_min + ' min' : '-'}
                </button>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; background:#eef5ff; padding:6px 8px; border-radius:4px; font-size:12px; margin-bottom:8px;">
                <span>${labelTC}</span>
                <a href="${lienTC}" target="_blank" style="color:var(--primary); font-weight:bold; text-decoration:none;">Horaires 8h ↗</a>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span class="badge green">Dispo : ${p.heures_restantes}h</span>
                <button class="btn-small btn-success" style="padding:6px 12px;" onclick="validerAffectation(${p.id})">✅ Affecter</button>
            </div>
        </div>`;
    });

    box.innerHTML = html;
}

function tracerItineraire(profId, mode) {
    const p = candidatsMatchingActuels.find(x => x.id === profId);
    if (!p || !layerItineraire) return;
    layerItineraire.clearLayers();

    const geom = mode === 'car' ? p.car_geom : (mode === 'bike' ? p.bike_geom : p.foot_geom);
    const couleur = mode === 'car' ? '#00448f' : (mode === 'bike' ? '#28a745' : '#fd7e14');
    const labelMode = mode === 'car' ? '🚗 Voiture (8h00)' : (mode === 'bike' ? '🚲 Vélo' : '🚶 À pied');
    const duree = mode === 'car' ? p.car_min : (mode === 'bike' ? p.bike_min : p.foot_min);

    if (geom) {
        const ligne = L.geoJSON(geom, {
            style: { color: couleur, weight: 5, opacity: 0.85, dashArray: mode === 'foot' ? '6, 8' : null }
        }).bindPopup(`<b>${p.nom} ➔ ${ecoleMatchingActuelle.nomEtab}</b><br>${labelMode} : <b>${duree} min</b>`).addTo(layerItineraire);
        ligne.openPopup();
        map.fitBounds(ligne.getBounds(), { padding: [40, 40] });
    }
}

function validerAffectation(remplacant_id) {
    fetch(`${API_URL}/affecter`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ remplacant_id, besoin_id: besoinActifContext })
    }).then(() => {
        alert("✅ Affectation enregistrée avec succès !");
        retourListeBesoins();
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
                <td><span class="badge blue">${a.discipline}</span></td>
                <td>${a.date_debut} ➔ ${a.date_fin}</td>
                <td><strong>${a.heures}h</strong></td>
                <td>
                    <button class="btn-small btn-warning" onclick="ouvrirEditAff(${a.id}, '${esc(a.nom_prof)}', ${a.heures}, '${a.date_debut}', '${a.date_fin}')">✏️</button>
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