import json
import time
import threading

import streamlit as st
import pandas as pd
import paho.mqtt.client as mqtt
from streamlit_autorefresh import st_autorefresh

# ================================================================
#                       CONFIG MQTT
# ================================================================
BROKER = "4.219.13.227"
PORT = 1883

# Capteurs météo (Node-RED)
TOPIC_SENSORS = "streamlit/brussels"

# MODE NORMAL (ESP local)
TOPIC_RGB_R = "esp32/rgb/red"
TOPIC_RGB_G = "esp32/rgb/green"
TOPIC_RGB_B = "esp32/rgb/blue"

# MODE SYNCHRO (Streamlit -> Node-RED -> ESP distant)
TOPIC_REMOTE_SET = "ESP/MINH envoi"

# Switch synchro
TOPIC_SYNC_SWITCH = "ESP/sync"   # "1" / "0"

# ================================================================
#                    ÉTAT GLOBAL MQTT
# ================================================================
class MqttState:
    def __init__(self):
        self.last = None
        self.connected = False


if "mqtt_state" not in st.session_state:
    st.session_state["mqtt_state"] = MqttState()

mqtt_state: MqttState = st.session_state["mqtt_state"]

# ================================================================
#                    CALLBACKS MQTT (CAPTEURS UNIQUEMENT)
# ================================================================
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
        if msg.topic == TOPIC_SENSORS:
            data = json.loads(msg.payload.decode("utf-8"))
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
        except Exception:
            mqtt_state.connected = False
            time.sleep(5)

# ================================================================
#                    FONCTIONS PUBLISH
# ================================================================
def mqtt_publish(topic, payload):
    try:
        c = mqtt.Client()
        c.connect(BROKER, PORT, 60)
        c.publish(topic, payload)
        c.disconnect()
        return True
    except Exception:
        return False


def publish_rgb_local(r, g, b):
    c = mqtt.Client()
    c.connect(BROKER, PORT, 60)
    c.publish(TOPIC_RGB_R, str(r))
    c.publish(TOPIC_RGB_G, str(g))
    c.publish(TOPIC_RGB_B, str(b))
    c.disconnect()


def publish_rgb_sync(r, g, b):
    payload = json.dumps({
        "src": "MINH",
        "r": int(r),
        "g": int(g),
        "b": int(b)
    })
    mqtt_publish(TOPIC_REMOTE_SET, payload)

# ================================================================
#                    THREAD MQTT
# ================================================================
if "mqtt_started" not in st.session_state:
    threading.Thread(target=mqtt_loop, daemon=True).start()
    st.session_state["mqtt_started"] = True
    st.session_state["history"] = []

st_autorefresh(interval=2000, key="refresh")

# ================================================================
#                           UI
# ================================================================
st.set_page_config(page_title="Station météo", layout="wide")
st.title("Station météo – Commande LED RGB")

if mqtt_state.connected:
    st.success("MQTT connecté")
else:
    st.warning("MQTT déconnecté")

# ------------------- Données météo -------------------
data = mqtt_state.last
temp = data.get("temperature") if data else None
hum  = data.get("humidity") if data else None
lum  = data.get("lum") if data else None

col1, col2, col3 = st.columns(3)
col1.metric("Température", "-" if temp is None else f"{temp:.1f} °C")
col2.metric("Humidité", "-" if hum is None else f"{hum:.1f} %")
col3.metric("Luminosité", "-" if lum is None else f"{lum}")

# ================================================================
#                   SIDEBAR – LED RGB
# ================================================================
st.sidebar.header("Contrôle LED RGB")

if "sync_mode" not in st.session_state:
    st.session_state["sync_mode"] = False

sync_mode = st.sidebar.toggle("Mode Synchro", value=st.session_state["sync_mode"])
st.session_state["sync_mode"] = sync_mode

# notifier Node-RED si changement
if "prev_sync" not in st.session_state:
    st.session_state["prev_sync"] = sync_mode

if sync_mode != st.session_state["prev_sync"]:
    mqtt_publish(TOPIC_SYNC_SWITCH, "1" if sync_mode else "0")
    st.session_state["prev_sync"] = sync_mode

# ------------------- Sliders -------------------
if not sync_mode:
    st.sidebar.subheader("Station locale (ESP local)")
    r = st.sidebar.slider("Rouge", 0, 255, 0)
    g = st.sidebar.slider("Vert", 0, 255, 0)
    b = st.sidebar.slider("Bleu", 0, 255, 0)
    publish_rgb_local(r, g, b)

    st.sidebar.info("Mode NORMAL : ESP local uniquement")

else:
    st.sidebar.subheader("Station distante (via Node-RED)")
    r = st.sidebar.slider("Rouge", 0, 255, 0, key="r_sync")
    g = st.sidebar.slider("Vert", 0, 255, 0, key="g_sync")
    b = st.sidebar.slider("Bleu", 0, 255, 0, key="b_sync")
    publish_rgb_sync(r, g, b)

    st.sidebar.warning("Mode SYNCHRO : ESP distant uniquement")

st.markdown(
    f"**Mode actif :** `{'SYNCHRO' if sync_mode else 'NORMAL'}` | **Broker :** `{BROKER}`"
)


