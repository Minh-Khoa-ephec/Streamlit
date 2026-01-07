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

# Mode normal (station locale) : 3 topics
TOPIC_RGB_R = "esp32/rgb/red"
TOPIC_RGB_G = "esp32/rgb/green"
TOPIC_RGB_B = "esp32/rgb/blue"

# Mode synchro (2 stations) : JSON unique par station
TOPIC_MINH_SET = "ESP/MINH"
TOPIC_RAD_SET  = "ESP/RAD"

# Switch synchro (optionnel côté Node-RED)
TOPIC_SYNC_SWITCH = "ESP/sync"   # payload: "1" / "0"


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
    if rc == 0:
        mqtt_state.connected = True
        client.subscribe(TOPIC_SENSORS)
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
            client.connect(BROKER, PORT, 60)
            client.loop_forever()
        except Exception as e:
            print("Erreur mqtt_loop:", e)
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


def publish_rgb_local_3topics(r, g, b) -> bool:
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


def publish_rgb_json(topic_set: str, r, g, b) -> bool:
    """Mode synchro : JSON unique {"r","g","b"} vers station cible."""
    payload = json.dumps({"r": int(r), "g": int(g), "b": int(b)})
    return mqtt_publish(topic_set, payload)


# ---------- Lancer le thread MQTT une seule fois ----------
if "mqtt_started" not in st.session_state:
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    st.session_state["mqtt_started"] = True
    st.session_state["history"] = []

# ---------- Auto-refresh ----------
st_autorefresh(interval=2000, key="mqtt_refresh")

# ---------- UI ----------
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


# ---------- Sidebar : RGB + Synchro ----------
st.sidebar.header("Contrôle LED RGB")

if "sync_mode" not in st.session_state:
    st.session_state["sync_mode"] = False

sync_mode = st.sidebar.toggle("Mode Synchro (2 stations)", value=st.session_state["sync_mode"])
st.session_state["sync_mode"] = sync_mode

# notifier Node-RED (optionnel)
if "prev_sync_mode" not in st.session_state:
    st.session_state["prev_sync_mode"] = sync_mode

if sync_mode != st.session_state["prev_sync_mode"]:
    mqtt_publish(TOPIC_SYNC_SWITCH, "1" if sync_mode else "0")
    st.session_state["prev_sync_mode"] = sync_mode


# --- Anti-spam: n'envoyer que si ça change ---
def should_send(key, r, g, b):
    last = st.session_state.get(key, (-1, -1, -1))
    cur = (r, g, b)
    if cur != last:
        st.session_state[key] = cur
        return True
    return False


if not sync_mode:
    # ===== MODE NORMAL : station locale (esp32/rgb/red|green|blue) =====
    st.sidebar.subheader("Station locale (MINH)")

    r = st.sidebar.slider("Rouge", 0, 255, 0, key="r_local")
    g = st.sidebar.slider("Vert", 0, 255, 0, key="g_local")
    b = st.sidebar.slider("Bleu", 0, 255, 0, key="b_local")

    if should_send("last_rgb_local", r, g, b):
        ok = publish_rgb_local_3topics(r, g, b)
        st.sidebar.caption("✅ Envoyé" if ok else "❌ Échec envoi")

else:
    # ===== MODE SYNCHRO : 2 stations indépendantes =====
    st.sidebar.subheader("Station MINH")
    r1 = st.sidebar.slider("R (MINH)", 0, 255, 0, key="r_minh")
    g1 = st.sidebar.slider("G (MINH)", 0, 255, 0, key="g_minh")
    b1 = st.sidebar.slider("B (MINH)", 0, 255, 0, key="b_minh")

    if should_send("last_rgb_minh", r1, g1, b1):
        ok = publish_rgb_json(TOPIC_MINH_SET, r1, g1, b1)
        st.sidebar.caption("✅ MINH envoyé" if ok else "❌ MINH échec")

    st.sidebar.divider()

    st.sidebar.subheader("Station RAD")
    r2 = st.sidebar.slider("R (RAD)", 0, 255, 0, key="r_rad")
    g2 = st.sidebar.slider("G (RAD)", 0, 255, 0, key="g_rad")
    b2 = st.sidebar.slider("B (RAD)", 0, 255, 0, key="b_rad")

    if should_send("last_rgb_rad", r2, g2, b2):
        ok = publish_rgb_json(TOPIC_RAD_SET, r2, g2, b2)
        st.sidebar.caption("✅ RAD envoyé" if ok else "❌ RAD échec")


st.write(
    f"**Mode RGB :** `{'SYNCHRO (2 stations)' if sync_mode else 'NORMAL (station locale)'}`  "
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

df = pd.DataFrame(history).set_index("time") if history else pd.DataFrame(columns=["temp", "hum", "lum"])
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
