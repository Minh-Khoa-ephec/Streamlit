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

TOPIC_SENSORS = "streamlit/brussels"  # capteurs via Node-RED

# Mode NORMAL (station locale MINH)  ✅ on envoie maintenant EN 1 SEUL JSON (plus fiable)
TOPIC_RGB_SET = "esp32/rgb/set"  # JSON {"r":..,"g":..,"b":..}

# Mode SYNCHRO : on publie sur ESP/MINH (Node-RED route vers ESP/RAD)
TOPIC_REMOTE_SET = "ESP/MINH envoi"

# Réception synchro (RAD -> Node-RED -> MINH) revient aussi sur ESP/MINH
TOPIC_REMOTE_RX = "ESP/MINH reception"

# Switch synchro (Node-RED + ESP32)
TOPIC_SYNC_SWITCH = "ESP/sync"  # payload "1" / "0"


# ---------- État global MQTT ----------
class MqttState:
    def __init__(self):
        self.last = None
        self.connected = False
        self.last_sync_rx = None  # dernière trame synchro reçue


if "mqtt_state" not in st.session_state:
    st.session_state["mqtt_state"] = MqttState()

mqtt_state: MqttState = st.session_state["mqtt_state"]


# ---------- Callbacks MQTT (réception) ----------
def on_connect(client, userdata, flags, rc):
    print("Code retour CONNEXION MQTT =", rc)
    if rc == 0:
        mqtt_state.connected = True
        client.subscribe(TOPIC_SENSORS)
        client.subscribe(TOPIC_REMOTE_RX)
        print(f"OK connecté, abonné à {TOPIC_SENSORS} et {TOPIC_REMOTE_RX}")
    else:
        mqtt_state.connected = False


def on_disconnect(client, userdata, rc):
    mqtt_state.connected = False


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        topic = msg.topic

        # capteurs
        if topic == TOPIC_SENSORS:
            data = json.loads(payload)
            if "ts" not in data:
                data["ts"] = time.time()
            mqtt_state.last = data
            return

        # synchro RX
        if topic == TOPIC_REMOTE_RX:
            try:
                data = json.loads(payload)
            except Exception:
                data = {"raw": payload}

            if isinstance(data, dict) and "ts" not in data:
                data["ts"] = time.time()

            mqtt_state.last_sync_rx = data
            return

    except Exception as e:
        print("Erreur MQTT:", e)


def mqtt_loop():
    """Thread de réception MQTT (persistant)."""
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


# ============================================================
# ✅ PUBLICATION MQTT AMÉLIORÉE : client persistant (zéro reconnect à chaque slider)
# ============================================================
def get_pub_client():
    """Client MQTT persistant pour publier rapidement (évite les retards/pertes)."""
    if "mqtt_pub" not in st.session_state:
        c = mqtt.Client()
        c.connect(BROKER, PORT, 60)
        c.loop_start()
        st.session_state["mqtt_pub"] = c
    return st.session_state["mqtt_pub"]


def mqtt_publish_fast(topic: str, payload: str, qos: int = 1, retain: bool = False) -> bool:
    try:
        c = get_pub_client()
        info = c.publish(topic, payload, qos=qos, retain=retain)
        info.wait_for_publish(timeout=1.0)
        return True
    except Exception as e:
        print("publish_fast error:", e)
        # reset si souci
        try:
            if "mqtt_pub" in st.session_state:
                st.session_state["mqtt_pub"].loop_stop()
                st.session_state["mqtt_pub"].disconnect()
        except Exception:
            pass
        st.session_state.pop("mqtt_pub", None)
        return False


def publish_rgb_local(r, g, b) -> bool:
    """
    ✅ Mode normal : 1 seul topic JSON (esp32/rgb/set) -> beaucoup plus fiable et instantané
    Format côté ESP32: {"r":..,"g":..,"b":..}
    """
    rgb = {"r": int(r), "g": int(g), "b": int(b)}
    payload = json.dumps(rgb, separators=(",", ":"))
    return mqtt_publish_fast(TOPIC_RGB_SET, payload, qos=1, retain=False)


def publish_rgb_remote_json(r, g, b) -> bool:
    """
    Mode synchro : JSON unique vers ESP/MINH (Node-RED route vers ESP/RAD)
    Format EXACT demandé :
    {"Synchro":true,"LED":true,"R":102,"G":0,"B":0}
    - Synchro = true (car fonction utilisée uniquement en mode synchro)
    - LED = true tant qu'au moins un slider != 0
    """
    r_i, g_i, b_i = int(r), int(g), int(b)
    led_on = (r_i != 0) or (g_i != 0) or (b_i != 0)

    payload_obj = {
        "Synchro": True,
        "LED": led_on,
        "R": r_i,
        "G": g_i,
        "B": b_i
    }

    payload = json.dumps(payload_obj, separators=(",", ":"))
    return mqtt_publish_fast(TOPIC_REMOTE_SET, payload, qos=1, retain=False)


# ---------- Lancer le thread MQTT ----------
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
sync_rx = mqtt_state.last_sync_rx

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
    st.subheader("Dernière trame reçue (capteurs)")
    st.json(data if data is not None else {"info": "Aucune donnée reçue pour l'instant"})

    st.subheader("Dernière trame reçue (synchro ESP/MINH)")
    st.json(sync_rx if sync_rx is not None else {"info": "Aucune trame synchro reçue pour l'instant"})


# ---------- Sidebar : Contrôle LED ----------
st.sidebar.header("Contrôle LED RGB")

# état synchro
if "sync_mode" not in st.session_state:
    st.session_state["sync_mode"] = False

sync_mode = st.sidebar.toggle(
    "Mode Synchro (sliders -> ESP/MINH -> Node-RED -> ESP/RAD)",
    value=st.session_state["sync_mode"]
)
st.session_state["sync_mode"] = sync_mode

# mémoriser l'ancien état du switch
if "prev_sync_mode" not in st.session_state:
    st.session_state["prev_sync_mode"] = sync_mode

# Anti-spam (logique "envoyer seulement si ça change")
if "last_rgb_sent_local" not in st.session_state:
    st.session_state["last_rgb_sent_local"] = None
if "last_rgb_sent_remote" not in st.session_state:
    st.session_state["last_rgb_sent_remote"] = None

# ✅ petit throttle pour éviter 50 publishes/sec quand tu glisses (sans casser le reste)
if "last_send_ms" not in st.session_state:
    st.session_state["last_send_ms"] = 0


def send_if_changed(r, g, b, send_fn, label_ok, key_state):
    """✅ Envoie uniquement si (r,g,b) a changé."""
    cur = (int(r), int(g), int(b))
    if st.session_state.get(key_state) != cur:
        ok = send_fn(r, g, b)
        if ok:
            st.session_state[key_state] = cur
            st.sidebar.caption(f"✅ {label_ok} : {cur}")
        else:
            st.sidebar.caption("❌ Échec d'envoi (broker ?)")

def send_throttled(r, g, b, send_fn, label_ok, key_state, min_interval_ms=80):
    now_ms = int(time.time() * 1000)
    if now_ms - st.session_state["last_send_ms"] < min_interval_ms:
        return
    st.session_state["last_send_ms"] = now_ms
    send_if_changed(r, g, b, send_fn, label_ok, key_state)


# ✅ quand on active/désactive le mode synchro : publier le switch + envoyer une trame initiale
if sync_mode != st.session_state["prev_sync_mode"]:
    mqtt_publish_fast(TOPIC_SYNC_SWITCH, "1" if sync_mode else "0", qos=1, retain=False)
    st.session_state["prev_sync_mode"] = sync_mode

    # reset anti-spam sur le mode actif
    if sync_mode:
        st.session_state["last_rgb_sent_remote"] = None
        # envoi initial
        r0 = st.session_state.get("r_remote", 0)
        g0 = st.session_state.get("g_remote", 0)
        b0 = st.session_state.get("b_remote", 0)
        send_if_changed(r0, g0, b0, publish_rgb_remote_json,
                        "Valeurs envoyées (INIT SYNCHRO)", "last_rgb_sent_remote")
    else:
        st.session_state["last_rgb_sent_local"] = None
        # envoi initial local
        r0 = st.session_state.get("r_local", 0)
        g0 = st.session_state.get("g_local", 0)
        b0 = st.session_state.get("b_local", 0)
        send_if_changed(r0, g0, b0, publish_rgb_local,
                        "Valeurs envoyées (INIT LOCAL)", "last_rgb_sent_local")


if not sync_mode:
    # ===== MODE NORMAL : contrôle LED LOCALE (MINH) =====
    st.sidebar.subheader("Station locale (MINH)")
    r_val = st.sidebar.slider("Rouge", 0, 255, 0, key="r_local")
    g_val = st.sidebar.slider("Vert", 0, 255, 0, key="g_local")
    b_val = st.sidebar.slider("Bleu", 0, 255, 0, key="b_local")

    # ✅ publish fiable + rapide
    send_throttled(r_val, g_val, b_val, publish_rgb_local,
                   "Valeurs envoyées (LOCAL)", "last_rgb_sent_local")

    st.sidebar.info("Mode NORMAL : contrôles LED MINH.")
else:
    # ===== MODE SYNCHRO : contrôle LED DISTANTE (RAD) =====
    st.sidebar.subheader("Station distante (RAD)")
    r_val = st.sidebar.slider("Rouge (RAD)", 0, 255, 0, key="r_remote")
    g_val = st.sidebar.slider("Vert (RAD)", 0, 255, 0, key="g_remote")
    b_val = st.sidebar.slider("Bleu (RAD)", 0, 255, 0, key="b_remote")

    send_throttled(r_val, g_val, b_val, publish_rgb_remote_json,
                   "Valeurs envoyées (ESP/MINH -> ESP/RAD)", "last_rgb_sent_remote")

    st.sidebar.warning("Mode SYNCHRO : contrôle UNIQUEMENT la LED de RAD (via Node-RED).")

st.write(
    f"**Mode RGB :** `{'SYNCHRO (sliders -> RAD)' if sync_mode else 'NORMAL (sliders -> MINH)'}`  "
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





