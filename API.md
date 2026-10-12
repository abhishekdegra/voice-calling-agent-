# TeleCMI (PIOPIY) Telephony API Reference

This document outlines the telephony integration specifications for **TeleCMI (PIOPIY)** used by the Welfog AI Voice Calling Agent.

---

## 1. Credentials & Endpoints

Configuration values should be set in your `.env` file (see `.env.example`).

- **Dashboard / Portal**: `https://console.telecmi.com/` (Access using your TeleCMI administrator credentials)
- **SBC (Session Border Controller)**: `sbcind.telecmi.com`
- **REST Base URL**: `https://rest.telecmi.com`
- **App ID (Numeric)**: Set via `TELECMI_APP_ID` in `.env`
- **App Secret**: Set via `TELECMI_APP_SECRET` in `.env`

### SIP Users Configuration

| Parameter | Description |
|---|---|
| **User ID** | Your TeleCMI SIP Agent ID (e.g. `5002_<APP_ID>`) |
| **Password** | Your TeleCMI SIP Agent Password (set via `TELECMI_USER_PASSWORD`) |

---

## 2. Browser WebRTC Phone (PIOPIY SDK)

The browser web client initializes the PIOPIY WebRTC SDK to simulate agent or customer calls:

### Step 1: Login / SIP Registration
```js
piopiy.login("<USER_ID>", "<USER_PASSWORD>", "sbcind.telecmi.com");
```

### Step 2: Outbound Dialing
Dial numbers with country code prefix `91` for Indian numbers (e.g., `9876543210` → `919876543210`):
```js
piopiy.call("919876543210");
```

Passing custom lead metadata with the call:
```js
piopiy.call("919876543210", { extra_param: "<leadId>" });
```

---

## 3. TeleCMI REST Endpoints

### 1. App Authentication Token
Generates a short-lived bearer token for accessing TeleCMI call feeds and services:

```http
POST /v2/token
Content-Type: application/json

{
  "appid": "<YOUR_APP_ID>",
  "secret": "<YOUR_APP_SECRET>"
}
```

### 2. Agent Login & Call Logs Authentication
Used to authenticate agent credentials against TeleCMI REST service:

```http
POST /v2/user/login
Content-Type: application/json

{
  "id": "<YOUR_USER_ID>",
  "password": "<YOUR_USER_PASSWORD>"
}
```

### 3. Outbound PCMO Streaming Call
Commands TeleCMI to initiate an outbound phone call and connect live bidirectional audio via WebSocket:

```http
POST /v2/global_pcmo_make_call
Content-Type: application/json
Authorization: Bearer <APP_TOKEN>

{
  "appid": "<YOUR_APP_ID>",
  "from": "<YOUR_CALLER_ID>",
  "to": 919876543210,
  "action": [
    {
      "action": "stream",
      "url": "wss://your-domain.com/ws/telecmi"
    }
  ]
}
```

### 4. Fetch Call Recording
```http
GET /v2/play?appid=<YOUR_APP_ID>&secret=<YOUR_APP_SECRET>&file=<RECORDING_FILENAME>
```
