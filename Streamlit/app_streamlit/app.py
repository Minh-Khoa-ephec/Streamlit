import json
import time
import threading

import streamlit as st
import pandas as pd
import paho.mqtt.client as mqtt
from streamlit_autorefresh import st_autorefresh 

# ---------- Config MQTT ----------
BROKER = "4.219.13.227"
PORT = 1883

TOPIC_SENSORS   = "streamlit/brussels"  # ce que Node-RED publie pour les capteurs
TOPIC_RGB_R     = "esp32/rgb/red"       # ce que l'ESP32 écoute
TOPIC_RGB_G     = "esp32/rgb/green"
TOPIC_RGB_B     = "esp32/rgb/blue"


# ---------- État global MQTT (capteurs) ----------

class MqttState:
    def __init__(self):
        self.last = None        # dernière trame reçue (dict)
        self.connected = False  # état connexion broker


# On stocke l'état dans session_state pour le garder malgré les reruns
if "mqtt_state" not in st.session_state:
    st.session_state["mqtt_state"] = MqttState()

mqtt_state: MqttState = st.session_state["mqtt_state"]


# ---------- Callbacks MQTT (réception capteurs) ----------

def on_connect(client, userdata, flags, rc):
    print("Code retour CONNEXION MQTT =", rc)
    if rc == 0:
        mqtt_state.connected = True
        client.subscribe(TOPIC_SENSORS)
        print(f"OK connecté, abonné à {TOPIC_SENSORS}")
    else:
        mqtt_state.connected = False
        print("Échec connexion MQTT, code rc =", rc)


def on_disconnect(client, userdata, rc):
    print("MQTT déconnecté (rc =", rc, ")")
    mqtt_state.connected = False


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        print("Message reçu sur", msg.topic, ":", payload)
        data = json.loads(payload)
        if "ts" not in data:
            data["ts"] = time.time()
        mqtt_state.last = data
    except Exception as e:
        print("Erreur MQTT:", e)


def mqtt_loop():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    while True:
        try:
            print(f"Connexion au broker MQTT {BROKER} {PORT}")
            client.connect(BROKER, PORT, 60)
            client.loop_forever()
        except Exception as e:
            print("Erreur dans mqtt_loop:", e)
            mqtt_state.connected = False
            time.sleep(5)


# ---------- MQTT publication RGB ----------

def publish_rgb(r, g, b):
    """Envoie les valeurs RGB vers l'ESP32 via MQTT."""
    try:
        pub = mqtt.Client()
        pub.connect(BROKER, PORT, 60)

        # On envoie les valeurs sous forme de texte, l'ESP32 fait atoi()
        pub.publish(TOPIC_RGB_R, str(r))
        pub.publish(TOPIC_RGB_G, str(g))
        pub.publish(TOPIC_RGB_B, str(b))

        pub.disconnect()
        print(f"RGB envoyé : R={r} G={g} B={b}")
    except Exception as e:
        print("Erreur publish RGB:", e)


# ---------- Lancer le thread MQTT une seule fois ----------
if "mqtt_started" not in st.session_state:
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    st.session_state["mqtt_started"] = True
    st.session_state["history"] = []   # pour les graphes


# ---------- Auto-refresh de la page toutes les 2 secondes ----------
st_autorefresh(interval=2000, key="mqtt_refresh")


# ---------- UI STREAMLIT ----------
st.set_page_config(page_title="Météo Bruxelles", page_icon="☁️", layout="wide")

st.title("Projet Final(2025-2026) - A3111 Industrie 4.0 et A304 Systèmes Embarqués 2")
st.header("Station Météo TRAN")

# Indicateur d'état MQTT (capteurs)
if mqtt_state.connected:
    st.success(f"MQTT connecté au broker {BROKER}:{PORT}")
else:
    st.warning(f"MQTT non connecté ou en attente de données depuis {BROKER}:{PORT}")

# Dernière trame capteurs (peut être None)
data = mqtt_state.last

# Valeurs par défaut
city = "Bruxelles"
temp = None
hum  = None
lum  = None
ts   = time.time()

if data is not None:
    city = data.get("city", "Bruxelles")
    temp = data.get("temperature")
    hum  = data.get("humidity")
    lum  = data.get("lum")
    ts   = data.get("ts", time.time())


def fmt_metric(val, unit="", decimals=1):
    if val is None:
        return "-"
    if isinstance(val, (int, float)):
        fmt = f"{{:.{decimals}f}}"
        return fmt.format(val) + (f" {unit}" if unit else "")
    return str(val)


# ---------- Colonne principale : mesures + JSON ----------
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader(f"Conditions actuelles – {city}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Température", fmt_metric(temp, "°C", 1))
    with c2:
        st.metric("Humidité", fmt_metric(hum, "%", 1))
    with c3:
        st.metric("Luminosité", fmt_metric(lum, "", 0))

    # Ressenti
    if temp is None:
        feeling = "Inconnu (en attente de données)"
    else:
        if temp >= 25:
            feeling = "Chaud"
        elif temp >= 10:
            feeling = "Doux"
        else:
            feeling = "Frais"

    # Jour / nuit en fonction de la luminosité
    if lum is None:
        period = "Inconnu (en attente de données LDR)"
    else:
        is_day = lum > 50   
        period = "Jour" if is_day else "Nuit"

    st.write("")
    st.markdown(f"**Ressenti :** {feeling}")
    st.markdown(f"**Période :** {period}")

with col2:
    st.subheader("Dernière trame reçue")
    if data is None:
        st.json({"info": "Aucune donnée reçue pour l'instant"})
    else:
        st.json(data)


# ---------- Sliders RGB + envoi vers l'ESP32 ----------
st.sidebar.header("Contrôle LED RGB")

r_val = st.sidebar.slider("Rouge", 0, 255, 0)
g_val = st.sidebar.slider("Vert",  0, 255, 0)
b_val = st.sidebar.slider("Bleu",  0, 255, 0)

st.sidebar.write("Valeurs RGB sélectionnées :", r_val, g_val, b_val)

if r_val is not None or g_val is not None or b_val is not None:
    publish_rgb(r_val, g_val, b_val)

st.sidebar.caption("Les valeurs sont envoyées vers l'ESP32")


# ---------- Historique pour les graphes ----------
history = st.session_state["history"]

# On ajoute un point uniquement si on a des données capteurs
if data is not None:
    history.append(
        {
            "time": pd.to_datetime(ts, unit="s"),
            "temp": temp,
            "hum": hum,
            "lum": lum,
        }
    )
    MAX_POINTS = 500
    if len(history) > MAX_POINTS:
        history = history[-MAX_POINTS:]
    st.session_state["history"] = history

# DataFrame même si vide
if history:
    df = pd.DataFrame(history).set_index("time")
else:
    df = pd.DataFrame(columns=["temp", "hum", "lum"])
    df.index.name = "time"

st.subheader("Évolution des mesures (Bruxelles)")

tab1, tab2, tab3 = st.tabs(["Température", "Humidité", "Luminosité"])

with tab1:
    if "temp" in df and not df["temp"].dropna().empty:
        st.line_chart(df[["temp"]])
    else:
        st.info("Aucune donnée de température reçue pour l'instant.")

with tab2:
    if "hum" in df and not df["hum"].dropna().empty:
        st.line_chart(df[["hum"]])
    else:
        st.info("Aucune donnée d'humidité reçue pour l'instant.")

with tab3:
    if "lum" in df and not df["lum"].dropna().empty:
        st.line_chart(df[["lum"]])
    else:
        st.info("Aucune donnée de luminosité reçue pour l'instant.")