import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Supervision - OCP Safi", page_icon="🌊", layout="wide")
st.title(" Supervision - Osmose Inverse (14 Trains)")

# --- CONSTANTES & PARAMÈTRES NOMINAUX ---
IDEAL_PROD = 208.33      # m3/h par train
IDEAL_RECOVERY = 46.0    # %
IDEAL_HP_PRESS = 70.0    # barg (avec ERD)
MAX_DP = 1.5             # bar
PROD_MAX_CIBLE = IDEAL_PROD * 14 # ~2916.6 m3/h

# Paramètres Énergétiques & VFD
PUISSANCE_NOMINALE = 783.0 # kW (considérée à 50 Hz)
FREQ_NOMINALE = 50.0 # Hz
VFD_MIN = 48.0 # Hz (Membrane propre)
VFD_MAX = 54.0 # Hz (Membrane colmatée max)
COUT_KWH = 1.0 # Tarif moyen estimé en MAD (à adapter)

CAPACITE_BAC = 40000.0 # m3

# --- SIMULATION DE DONNÉES EN TEMPS RÉEL ---
@st.cache_data(ttl=30)
def get_simulated_data():
    data = []
    for i in range(1, 15):
        # Simulation de l'encrassement (DP)
        dp = np.random.uniform(0.5, 1.4) 
        
        # Fréquence VFD proportionnelle au DP
        vfd_freq = VFD_MIN + ((dp - 0.5) / (MAX_DP - 0.5)) * (VFD_MAX - VFD_MIN)
        vfd_freq = np.clip(vfd_freq, VFD_MIN, VFD_MAX)
        
        # Calcul de la Puissance Absorbée (Loi du Cube des Affinités)
        puissance_actuelle = PUISSANCE_NOMINALE * (vfd_freq / FREQ_NOMINALE)**3
        puissance_pire_cas = PUISSANCE_NOMINALE * (VFD_MAX / FREQ_NOMINALE)**3
        economie_kw = puissance_pire_cas - puissance_actuelle
        
        data.append({
            "Train": f"Train {str(i).zfill(2)}",
            "Débit Feed (m3/h)": IDEAL_PROD / (IDEAL_RECOVERY / 100),
            "Pression HP (barg)": round(np.random.normal(IDEAL_HP_PRESS, 0.2), 2),
            "DP (bar)": round(dp, 2),
            "SDI": round(np.random.normal(2.1, 0.1), 2),
            "Fréq. VFD HP (Hz)": round(vfd_freq, 1),
            "Débit Perméat (m3/h)": IDEAL_PROD,
            "Puissance Absorbée (kW)": round(puissance_actuelle, 0),
            "Économie vs Max (kW)": round(economie_kw, 0),
            "Statut": "En marche"
        })
    return pd.DataFrame(data)

df_brut = get_simulated_data()

# --- SIDEBAR : NAVIGATION & SIMULATION ---
st.sidebar.header("Navigation")
view_mode = st.sidebar.radio("Vue d'Exploitation", ["Vue Globale ", "Détails par Train"])

st.sidebar.markdown("---")
st.sidebar.header("Simulateur de Scénarios")

st.sidebar.subheader(" Demande des Entités (m³/h)")
besoin_mc = st.sidebar.slider("Entité MC", 0, 750, 750, step=50)
besoin_mp1 = st.sidebar.slider("Entité MP1", 0, 870, 870, step=50)
besoin_mp2 = st.sidebar.slider("Entité MP2", 0, 850, 850, step=50)
demande_totale = besoin_mc + besoin_mp1 + besoin_mp2

st.sidebar.markdown("---")
st.sidebar.subheader("⏱️ Contexte Temporel & Stock")
heure_simulee = st.sidebar.time_input("Heure actuelle", datetime.time(2, 30))
niveau_bac_actuel = st.sidebar.slider("Niveau Bac Tampon (m³)", 0, int(CAPACITE_BAC), 25000, step=1000)

# --- MOTEUR DE DÉCISION  (ALGORITHME) ---
heure = heure_simulee.hour
if 23 <= heure or heure < 7:
    poste, couleur_poste, tarif_msg = "Creuses", "🟢", "Tarif Électricité : Très Bas"
elif 7 <= heure < 17:
    poste, couleur_poste, tarif_msg = "Pleines", "🟠", "Tarif Électricité : Élevé"
else: 
    poste, couleur_poste, tarif_msg = "Pointes", "🔴", "Tarif Électricité : Critique (Pointe)"

trains_requis_stricts = int(np.ceil(demande_totale / IDEAL_PROD))

if poste == "Creuses":
    objectif_trains = 14 if niveau_bac_actuel < 38000 else trains_requis_stricts
elif poste == "Pleines":
    objectif_trains = max(0, trains_requis_stricts - 1) if niveau_bac_actuel > 15000 else trains_requis_stricts
else: 
    objectif_trains = max(0, trains_requis_stricts - 2) if niveau_bac_actuel > 20000 else trains_requis_stricts

# On priorise l'arrêt des trains les plus encrassés
df_optimise = df_brut.sort_values(by="DP (bar)", ascending=True).copy()

for i in range(len(df_optimise)):
    if i >= objectif_trains:
        df_optimise.iloc[i, df_optimise.columns.get_loc("Statut")] = "🛑 Délestage (Éco)"
        df_optimise.iloc[i, df_optimise.columns.get_loc("Débit Perméat (m3/h)")] = 0
        df_optimise.iloc[i, df_optimise.columns.get_loc("Débit Feed (m3/h)")] = 0
        puissance_pire = PUISSANCE_NOMINALE * (VFD_MAX / FREQ_NOMINALE)**3
        df_optimise.iloc[i, df_optimise.columns.get_loc("Économie vs Max (kW)")] = round(puissance_pire, 0)
        df_optimise.iloc[i, df_optimise.columns.get_loc("Puissance Absorbée (kW)")] = 0
        df_optimise.iloc[i, df_optimise.columns.get_loc("Fréq. VFD HP (Hz)")] = 0

df_optimise = df_optimise.sort_values(by="Train")

# --- VUE 1 : GLOBALE ---
if view_mode == "Vue Globale ":
    
    prod_totale = df_optimise["Débit Perméat (m3/h)"].sum()
    feed_total = df_optimise["Débit Feed (m3/h)"].sum()
    puissance_totale = df_optimise["Puissance Absorbée (kW)"].sum()
    economie_totale_kw = df_optimise["Économie vs Max (kW)"].sum()
    
    st.header("Vue Globale de l'Usine (Capacité vs Production)")
    
    col1, col2, col3, col4 = st.columns(4)
    # Comparaison de la production actuelle avec la capacité maximale de l'usine
    col1.metric("Production Instantanée", f"{prod_totale:.1f} m³/h", f"Cible Max: {PROD_MAX_CIBLE:.1f} m³/h")
    col2.metric("Débit Brut (Feed) Total", f"{feed_total:.1f} m³/h")
    col3.metric("Niveau Bac Tampon", f"{niveau_bac_actuel} m³", f"{(niveau_bac_actuel/CAPACITE_BAC)*100:.1f} %")
    vfd_moyen = df_optimise[df_optimise["Statut"] == "En marche"]["Fréq. VFD HP (Hz)"].mean()
    col4.metric("Fréq. VFD Moyenne (Active)", f"{vfd_moyen:.1f} Hz" if not pd.isna(vfd_moyen) else "0.0 Hz")
    
    st.markdown("---")
    st.subheader(" Distribution & Bilan Hydraulique")
    dist_cols = st.columns(4)
    with dist_cols[0]: st.metric("Demande MC", f"{besoin_mc} m³/h")
    with dist_cols[1]: st.metric("Demande MP1", f"{besoin_mp1} m³/h")
    with dist_cols[2]: st.metric("Demande MP2", f"{besoin_mp2} m³/h")
    
    balance = prod_totale - demande_totale
    delta_color = "normal" if balance >= 0 else "inverse"
    with dist_cols[3]: st.metric("Bilan vers Bac (Surplus/Déficit)", f"{balance:+.1f} m³/h", delta_color=delta_color)

    st.markdown("---")
    st.header(" Bilan Financier & Stratégie ")
    
    col_roi1, col_roi2, col_roi3 = st.columns(3)
    col_roi1.metric("Puissance Actuelle Absorbée", f"{puissance_totale:.0f} kW", "Facture minimisée", delta_color="inverse")
    col_roi2.metric("Puissance Économisée", f"{economie_totale_kw:.0f} kW", "via Pilotage VFD & Délestage")
    col_roi3.metric("Gains Financiers (Proj. 24h)", f"{(economie_totale_kw * 24 * COUT_KWH):,.0f} MAD", "Basé sur 1 MAD/kWh")
    
    st.info(f"**Poste Actuel :** {couleur_poste} Heures {poste} ({tarif_msg}) | **Stratégie :** {objectif_trains}/14 Trains Actifs.")

    st.markdown("---")
    st.subheader("Détail des 14 Lignes d'Osmose Inverse")
    def color_status(val):
        return 'background-color: #ffcccc' if "Délestage" in val else 'background-color: #ccffcc'

    st.dataframe(
        df_optimise.style
        .map(color_status, subset=['Statut'])
        .background_gradient(subset=['Puissance Absorbée (kW)', 'DP (bar)'], cmap='Reds', vmin=0)
        .format({
            "Débit Feed (m3/h)": "{:.1f}",
            "Débit Perméat (m3/h)": "{:.1f}", 
            "Puissance Absorbée (kW)": "{:.0f}",
            "Économie vs Max (kW)": "+{:.0f}"
        }),
        height=550,
        use_container_width=True
    )

# --- VUE 2 : DÉTAILS PAR TRAIN ---
else:
    selected_train = st.sidebar.selectbox("Sélectionner un Train", df_optimise["Train"])
    train_data = df_optimise[df_optimise["Train"] == selected_train].iloc[0]
    
    st.header(f" Supervision Détaillée : {selected_train}")
    
    if "Délestage" in train_data['Statut']:
        st.warning("⚠️ Ce train est actuellement mis à l'arrêt par l'algorithme d'optimisation énergétique ")
    
    col1, col2, col3, col4 = st.columns(4)
    # L'ajout de :.2f force l'affichage à 2 décimales
    col1.metric("Débit RO Feed", f"{train_data['Débit Feed (m3/h)']:.2f} m³/h")
    col2.metric("Pression HP (ERD)", f"{train_data['Pression HP (barg)']:.2f} barg")
    col3.metric("Débit Perméat", f"{train_data['Débit Perméat (m3/h)']:.2f} m³/h")
    col4.metric("Fréquence VFD", f"{train_data['Fréq. VFD HP (Hz)']:.1f} Hz") # :.1f pour 1 décimale
    
    st.markdown("---")
    st.subheader(" État de Santé et Anticolmatage")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_dp = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = train_data['DP (bar)'],
            title = {'text': "Pression Différentielle (DP)"},
            gauge = {
                'axis': {'range': [0, 2]},
                'bar': {'color': "darkblue"},
                'steps' : [
                    {'range': [0, 0.8], 'color': "lightgreen"},
                    {'range': [0.8, 1.5], 'color': "yellow"},
                    {'range': [1.5, 2], 'color': "red"}],
                'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': MAX_DP}
            }))
        st.plotly_chart(fig_dp, use_container_width=True)
        
    with col_g2:
        fig_sdi = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = train_data['SDI'],
            title = {'text': "Indice SDI (Silt Density Index)"},
            gauge = {
                'axis': {'range': [0, 5]},
                'bar': {'color': "darkblue"},
                'steps' : [
                    {'range': [0, 3], 'color': "lightgreen"},
                    {'range': [3, 5], 'color': "red"}],
                'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 3.0}
            }))
        st.plotly_chart(fig_sdi, use_container_width=True)