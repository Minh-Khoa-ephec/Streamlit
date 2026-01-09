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

TOPIC_SENSORS = "streamlit/brussels"  # ce que Node-RED publie pour les capteurs

# Mode NORMAL (station locale MINH) : 3 topics
TOPIC_RGB_R = "esp32/rgb/red"
TOPIC_RGB_G = "esp32/rgb/green"
TOPIC_RGB_B = "esp32/rgb/blue"

# Mode SYNCHRO : on contrôle UNIQUEMENT la station distante
TOPIC_REMOTE_SET = "ESP/RAD"   

# Switch synchro (Node-RED peut activer ses règles si tu veux)
TOPIC_SYNC_SWITCH = "ESP/sync"         # payload: "1" / "0"


# ---------- État global MQTT (capteurs) ----------
class MqttState:
    def __init__(self):
        self.last = None
        self.connected = False

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

def on_disconnect(client, userdata, rc):
    mqtt_state.connected = False

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
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


# ---------- Publication MQTT ----------
def mqtt_publish(topic: str, payload: str) -> bool:
    try:
        pub = mqtt.Client()
        pub.connect(BROKER, PORT, 60)
        pub.publish(topic, payload)
        pub.disconnect()
        return True
    except Exception as e:
        print("Erreur publish:", e)
        return False


def publish_rgb_local(r, g, b) -> bool:
    """Mode normal : 3 topics, texte (atoi côté ESP32)."""
    try:
        pub = mqtt.Client()
        pub.connect(BROKER, PORT, 60)
        pub.publish(TOPIC_RGB_R, str(r))
        pub.publish(TOPIC_RGB_G, str(g))
        pub.publish(TOPIC_RGB_B, str(b))
        pub.disconnect()
        return True
    except Exception as e:
        print("Erreur publish RGB local:", e)
        return False


def publish_rgb_remote_json(r, g, b) -> bool:
    """Mode synchro : JSON unique vers station distante (avec src pour anti-boucle)."""
    payload = json.dumps({"src": "MINH", "r": int(r), "g": int(g), "b": int(b)})
    return mqtt_publish(TOPIC_REMOTE_SET, payload)



# ---------- Lancer le thread MQTT une seule fois ----------
if "mqtt_started" not in st.session_state:
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    st.session_state["mqtt_started"] = True
    st.session_state["history"] = []

# ---------- Auto-refresh ----------
st_autorefresh(interval=2000, key="mqtt_refresh")

# ---------- UI STREAMLIT ----------
st.set_page_config(page_title="Météo Bruxelles", page_icon="☁️", layout="wide")

st.title("Projet Final(2025-2026) - A3111 Industrie 4.0 et A304 Systèmes Embarqués 2")
st.header("Station Météo TRAN")

if mqtt_state.connected:
    st.success(f"MQTT connecté au broker {BROKER}:{PORT}")
else:
    st.warning(f"MQTT non connecté ou en attente de données depuis {BROKER}:{PORT}")

data = mqtt_state.last

city = "Bruxelles"
temp = None
hum = None
lum = None
ts = time.time()

if data is not None:
    city = data.get("city", "Bruxelles")
    temp = data.get("temperature")
    hum = data.get("humidity")
    lum = data.get("lum")
    ts = data.get("ts", time.time())


def fmt_metric(val, unit="", decimals=1):
    if val is None:
        return "-"
    if isinstance(val, (int, float)):
        fmt = f"{{:.{decimals}f}}"
        return fmt.format(val) + (f" {unit}" if unit else "")
    return str(val)


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

    if temp is None:
        feeling = "Inconnu (en attente de données)"
    else:
        if temp >= 25:
            feeling = "Chaud"
        elif temp >= 10:
            feeling = "Doux"
        else:
            feeling = "Frais"

    if lum is None:
        period = "Inconnu (en attente de données LDR)"
    else:
        period = "Jour" if lum > 50 else "Nuit"

    st.write("")
    st.markdown(f"**Ressenti :** {feeling}")
    st.markdown(f"**Période :** {period}")

with col2:
    st.subheader("Dernière trame reçue")
    st.json(data if data is not None else {"info": "Aucune donnée reçue pour l'instant"})


# ---------- Sidebar : Contrôle LED RGB + Mode Synchro ----------
st.sidebar.header("Contrôle LED RGB")

if "sync_mode" not in st.session_state:
    st.session_state["sync_mode"] = False

sync_mode = st.sidebar.toggle(
    "Mode Synchro (je contrôle la LED de RAD)",
    value=st.session_state["sync_mode"]
)
st.session_state["sync_mode"] = sync_mode

# notifier Node-RED quand le switch change
if "prev_sync_mode" not in st.session_state:
    st.session_state["prev_sync_mode"] = sync_mode

if sync_mode != st.session_state["prev_sync_mode"]:
    mqtt_publish(TOPIC_SYNC_SWITCH, "1" if sync_mode else "0")
    st.session_state["prev_sync_mode"] = sync_mode

# Anti-spam : envoi seulement si changement
if "last_rgb_sent" not in st.session_state:
    st.session_state["last_rgb_sent"] = (-1, -1, -1)

def send_if_changed(r, g, b, send_fn, label_ok):
    cur = (r, g, b)
    if cur != st.session_state["last_rgb_sent"]:
        ok = send_fn(r, g, b)
        if ok:
            st.session_state["last_rgb_sent"] = cur
            st.sidebar.caption(f"✅ {label_ok}")
        else:
            st.sidebar.caption(" Échec d'envoi (broker ?)")

if not sync_mode:
    # ===== MODE NORMAL : contrôle LED LOCALE (MINH) =====
    st.sidebar.subheader("Station locale (MINH)")
    r_val = st.sidebar.slider("Rouge", 0, 255, 0, key="r_local")
    g_val = st.sidebar.slider("Vert", 0, 255, 0, key="g_local")
    b_val = st.sidebar.slider("Bleu", 0, 255, 0, key="b_local")

    send_if_changed(r_val, g_val, b_val, publish_rgb_local, "Valeurs envoyées (LOCAL)")

    st.sidebar.info("Mode NORMAL : tu contrôles ta LED MINH.")
else:
    # ===== MODE SYNCHRO : contrôle LED DISTANTE (RAD) =====
    st.sidebar.subheader("Station distante (RAD)")
    r_val = st.sidebar.slider("Rouge (RAD)", 0, 255, 0, key="r_remote")
    g_val = st.sidebar.slider("Vert (RAD)", 0, 255, 0, key="g_remote")
    b_val = st.sidebar.slider("Bleu (RAD)", 0, 255, 0, key="b_remote")

    send_if_changed(r_val, g_val, b_val, publish_rgb_remote_json, "Valeurs envoyées (RAD)")

    st.sidebar.warning("Mode SYNCHRO : tu NE contrôles PLUS ta LED MINH.\nTu contrôles UNIQUEMENT la LED de RAD.")

st.write(
    f"**Mode RGB :** `{'SYNCHRO (contrôle RAD)' if sync_mode else 'NORMAL (contrôle MINH)'}`  "
    f"| **Broker :** `{BROKER}:{PORT}`"
)


# ---------- Historique ----------
history = st.session_state["history"]

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

