# AURUM Plug & Play – Quickstart

Dieses Dokument führt dich durch die Ersteinrichtung von AURUM auf einem
neuen Raspberry Pi mit Home Assistant OS. Zielgruppe: PV-Besitzer, die
**noch kein Home Assistant** laufen haben und schnell zu einem Ergebnis
kommen wollen.

**Geschätzte Zeit:** ~45 Minuten (ohne Inverter-spezifische Pairing-Zeit)

---

## Was du brauchst

| Item | Empfehlung |
|---|---|
| Raspberry Pi | Pi 4 (4 GB) oder Pi 5 (4 GB / 8 GB) |
| SD-Karte | 32 GB+ A2-Klasse (SanDisk Extreme, Samsung Evo Plus) |
| Netzteil | Original Pi-Netzteil (5 V / 3 A bzw. 5 V / 5 A für Pi 5) |
| Netzwerk | Ethernet **empfohlen** (WLAN-Setup ist nachträglich lästig) |
| Zweiter Rechner | Mit SD-Kartenleser für das Flashen |

**Wichtig:** Pi, Inverter und Smart Plugs müssen im gleichen Netzwerk sein,
damit Auto-Discovery funktioniert.

---

## Schritt 1 – Home Assistant OS installieren

1. Auf dem zweiten Rechner [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installieren.
2. Imager öffnen → „CHOOSE DEVICE" → Raspberry Pi 4 oder 5.
3. „CHOOSE OS" → „Other specific-purpose OS" → „Home assistants and home automation" → „Home Assistant" → passende Version (Pi 4 oder Pi 5).
4. „CHOOSE STORAGE" → deine SD-Karte.
5. „NEXT" → „NO" (keine OS-Anpassungen nötig) → „YES" (Flashen starten).
6. Nach dem Flashen: SD-Karte in den Pi stecken, Ethernet einstecken, Strom an.
7. **10-15 Minuten warten** – HA OS zieht sich online und installiert sich.

Sobald die LED-Aktivität nachlässt, vom Zweitrechner im Browser öffnen:

👉 **http://homeassistant.local:8123**

Falls das nicht geht: IP des Pi im Router nachsehen und direkt eingeben.

---

## Schritt 2 – Home Assistant erstmalig einrichten

1. Benutzer-Account anlegen (Nutzername, Passwort – **Passwort merken!**)
2. Standort setzen (wichtig für Solar-Prognose & Zeitzone).
3. Einheiten-System auswählen (Metrisch).
4. Geräte-Erkennung überspringen (machen wir gleich gezielt).

Du landest auf dem Standard-Dashboard „Übersicht".

---

## Schritt 3 – Integrationen für deine Hardware hinzufügen

**Einstellungen → Geräte & Dienste → + Integration hinzufügen**

### 3a. PV-Wechselrichter

| Marke | Integration | Setup |
|---|---|---|
| **Fronius** | „Fronius" | Wird meist automatisch erkannt (mDNS). Sonst IP eingeben. |
| **SMA** | „SMA Solar" oder „SMA Sunny WebBox" | IP + Benutzername („User"/„Installer") + Passwort. |
| **Kostal** | „Kostal Plenticore Solar Inverter" | IP + Passwort. |
| **SolarEdge** | „SolarEdge" | API-Key aus dem SolarEdge-Monitoring-Portal. |
| **Huawei** | „Huawei Solar" (via HACS) | Modbus-IP + Slave-ID. |
| **Victron** | „Victron VenusOS MQTT" | MQTT-Broker muss vorher laufen. |

### 3b. Batteriespeicher

- Meistens **automatisch verfügbar** über die Inverter-Integration oben
  (Fronius Symo Hybrid, SMA Sunny Boy Storage, Kostal Plenticore).
- **Tesla Powerwall:** eigene Integration „Powerwall", Gateway-IP eingeben.
- **Zendure Solarflow:** via HACS „Zendure Integration".

### 3c. Smart Plugs (Verbraucher)

| Marke | Integration |
|---|---|
| **Shelly** (Plus Plug S, Plus 1PM, Pro 3EM) | „Shelly" – mDNS-Discovery |
| **Tasmota-Geräte** | „Tasmota" – MQTT empfohlen |
| **TP-Link Kasa / Tapo** | „TP-Link Smart Home" |
| **Sonoff Zigbee** | „Zigbee Home Automation" + Coordinator-Stick |

**Tipp:** Im Zweifel erst alle Smart Plugs ans Strom, dann im Router (Fritzbox & Co.) nachschauen, welche neuen Geräte im Netz sind – die IP verrät meistens den Hersteller.

### 3d. Strompreis (optional, aber empfohlen)

Für preisbewusstes Scheduling (günstigen Netzstrom nutzen, wenn wenig PV):

- **Tibber:** Integration „Tibber" → API-Token aus tibber.com.
- **aWATTar:** HACS-Integration „aWATTar".
- **Nord Pool:** HACS-Integration „Nord Pool".
- **EPEX Spot:** HACS-Integration „EPEX Spot Price".

---

## Schritt 4 – AURUM installieren

> Wenn du das Image mit `tools/quickstart.sh` aufgesetzt hast, ist AURUM bereits installiert – **weiter zu Schritt 5**.

Nur falls AURUM noch fehlt (z. B. bei einer Standard-HAOS-Installation):

### 4a. HACS installieren

1. Im HA-Menü „Add-on Store" → **Advanced SSH & Web Terminal** installieren + starten.
2. Terminal öffnen, ausführen:
   ```bash
   wget -O - https://get.hacs.xyz | bash -
   ```
3. HA neu starten.
4. HACS konfigurieren (GitHub-OAuth-Flow durchlaufen).

### 4b. AURUM über HACS installieren

1. HACS → „Integrationen" → ⋮ → „Benutzerdefinierte Repositories".
2. URL `https://github.com/cm-makes/aurum-ha`, Kategorie „Integration" → Hinzufügen.
3. AURUM suchen, Download, HA neu starten.

**Alternativ – eine einzige Zeile für alles (HACS + AURUM + Theme + Dashboard):**

```bash
wget -O - https://raw.githubusercontent.com/cm-makes/aurum-ha/main/tools/quickstart.sh | bash
```

---

## Schritt 5 – AURUM konfigurieren

**Einstellungen → Geräte & Dienste → + Integration hinzufügen → AURUM**

**Step 1 – Energie-Quellen:**
- **Netz-Leistungssensor** (Pflicht): z. B. `sensor.fronius_grid_power`
  (positiv = Bezug, negativ = Einspeisung – wichtig!)
- **PV-Leistungssensor** (empfohlen): z. B. `sensor.fronius_pv_power`
- **Akku-SOC-Sensor** (empfohlen, wenn Batterie vorhanden)
- **Strompreis-Sensor** (optional)

**Step 2 – Akku-Einstellungen:**
- Akkukapazität (Wh) – aus dem Datenblatt
- Ziel-SOC: 80 % (Standardempfehlung)
- Min-SOC: 15 % (Tiefentladeschutz)
- Update-Intervall: 30 s

Nach „Senden" läuft AURUM.

---

## Schritt 6 – Verbraucher hinzufügen

**Einstellungen → AURUM → Konfigurieren → Gerät hinzufügen**

Pro Gerät:
| Feld | Beispiel |
|---|---|
| Name | `Waschmaschine` |
| Switch-Entität | `switch.shelly_waschmaschine` |
| Nominalleistung | `2200` (W) |
| Priorität | `50` (0-100, höher = wichtiger) |

**Empfohlene Priorities:**
- Warmwasser / Heizstab: **90**
- Heizlüfter: **80**
- Wärmepumpe (Smart-Plug-gesteuert): **70**
- Spül-/Waschmaschine: **50**
- Pool-Pumpe: **30**
- E-Bike laden: **20**

---

## Schritt 7 – Dashboard nutzen

Nach dem Neustart sollte in der Seitenleiste **„AURUM"** erscheinen
(mit dem Overlay aus `quickstart.sh`).

Alternativ manuell:
1. Einstellungen → Dashboards → „Dashboard hinzufügen".
2. Titel „AURUM", Icon `mdi:solar-power-variant`.
3. In das neue Dashboard den Inhalt aus
   [`image_overlay/config/dashboards/aurum.yaml`](https://github.com/cm-makes/aurum-ha/blob/main/image_overlay/config/dashboards/aurum.yaml)
   kopieren (⋮ → „Roher Konfigurations-Editor").

---

## Häufige Probleme

**Problem:** „Dashboard zeigt nur `unknown` Werte"
→ Du hast die AURUM-Integration noch nicht konfiguriert (Schritt 5). Das Dashboard
  basiert auf `sensor.aurum_*` Entitäten, die erst nach der Integration existieren.

**Problem:** „Keine Geräte im Dropdown"
→ Die Smart-Plug-Integration wurde noch nicht eingerichtet (Schritt 3c). Erst diese
  konfigurieren, dann das AURUM-Gerät hinzufügen.

**Problem:** „PV zeigt 0 W obwohl Sonne scheint"
→ Vorzeichen-Konvention prüfen. AURUM erwartet: PV-Leistung **positiv**, Netz **positiv = Bezug**.
  Bei manchen Invertern ist das gedreht – im HA-Entity-Inspektor schauen.

**Problem:** „Mushroom-Karten werden nicht angezeigt"
→ HACS → Frontend → Mushroom installieren + HA einmal neu laden (Strg+F5).

---

## Support

- GitHub Issues: https://github.com/cm-makes/aurum-ha/issues
- GitHub Discussions: https://github.com/cm-makes/aurum-ha/discussions

---

## Was kommt als Nächstes

Die nächste Version (Phase 2 des P&P-Plans) bringt einen **AURUM Onboarding
Wizard** als eigenes Panel in der HA-Seitenleiste, der die Schritte 3-6 zu
einem ≤10-Minuten-Klick-Flow zusammenfasst – inkl. Auto-Discovery von
Invertern und Smart Plugs.
