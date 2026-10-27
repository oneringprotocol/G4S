# TotalSecure Tracking Platform WebSocket API Docs

## Overview

TotalSecure Tracking Platform provides a WebSocket endpoint for live device updates, live position updates, and event notifications.

Recommended endpoint:

`/api/socket`

Example full URL:

`wss://tracking.totalsecureme.com/api/socket`

Use `ws://` only for local or non-TLS environments.

---

## Important Authentication Rule

The TotalSecure Tracking Platform WebSocket endpoint accepts only the platform session cookie.

It does not authenticate with:
- Bearer token
- Basic auth header
- `token` query parameter

Platform behavior:
- REST login can use `POST /api/session`
- REST session validation can use `GET /api/session?token=...`
- WebSocket connection requires the session cookie returned by login, typically `JSESSIONID`

---

## Connection Flow

### Option 1 - Direct platform login, then WebSocket connect

1. Call `POST /api/session` with form data:
   - `email`
   - `password`
2. Read the `Set-Cookie` response header and extract `JSESSIONID`
3. Open WebSocket connection to `/api/socket`
4. Send the cookie in the WebSocket handshake
5. Start consuming live messages

This is the native platform flow.

### Option 2 - Backend-assisted login for frontend apps

If the frontend logs in through this Django backend, it currently receives an API token, not the platform session cookie.

That means the frontend cannot open the platform WebSocket directly unless one of these is added:
- backend returns the platform session cookie safely for WebSocket use
- backend exposes its own WebSocket/SSE proxy
- backend creates a short-lived endpoint that upgrades or proxies the platform stream

Without one of those changes, REST calls can work while WebSocket connection still fails with unauthorized access.

---

## Login Request

### Create platform session

**POST** `/api/session`

Headers:

```http
Content-Type: application/x-www-form-urlencoded
Accept: application/json
```

Body:

```text
email=YOUR_EMAIL&password=YOUR_PASSWORD
```

Example curl:

```bash
curl -i -X POST "https://tracking.totalsecureme.com/api/session" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Accept: application/json" \
  --data "email=YOUR_EMAIL&password=YOUR_PASSWORD"
```

Expected behavior:
- response body contains the user object
- response headers include `Set-Cookie`
- `Set-Cookie` contains `JSESSIONID=...`

Typical response header shape:

```http
Set-Cookie: JSESSIONID=abc123xyz...; Path=/; HttpOnly; SameSite=Lax
```

---

## WebSocket Endpoint

**GET / Upgrade** `/api/socket`

Example:

```text
wss://tracking.totalsecureme.com/api/socket
```

Required cookie during handshake:

```http
Cookie: JSESSIONID=<session-id-from-login>
```

---

## Message Format

Each WebSocket message uses a common JSON envelope.

```json
{
  "devices": [...],
  "positions": [...],
  "events": [...]
}
```

Notes:
- A message can contain one or more of these keys
- If there is no data for a type, that key can be omitted
- Most messages contain a single object type
- Consumers must check for key existence before processing

Recommended client handling pattern:
- if `devices` exists, update device cache/state
- if `positions` exists, update live map marker/state
- if `events` exists, trigger event-specific UI or business logic

---

## JavaScript Example

Browser WebSocket APIs do not let you set custom headers manually in all cases. If the platform cookie is already stored for the same origin and allowed by browser cookie policy, the browser will send it automatically during the WebSocket handshake.

```javascript
const socket = new WebSocket('wss://tracking.totalsecureme.com/api/socket');

socket.onopen = () => {
  console.log('Connected to TotalSecure Tracking Platform WebSocket');
};

socket.onmessage = (event) => {
  const payload = JSON.parse(event.data);

  if (payload.devices) {
    console.log('Device updates:', payload.devices);
  }

  if (payload.positions) {
    console.log('Position updates:', payload.positions);
  }

  if (payload.events) {
    console.log('Event updates:', payload.events);
  }
};

socket.onerror = (error) => {
  console.error('WebSocket error:', error);
};

socket.onclose = (event) => {
  console.log('WebSocket closed:', event.code, event.reason);
};
```

Important browser note:
- this works only when the login request and WebSocket request share cookie scope correctly
- cross-origin frontend setups may need cookie/CORS/session configuration review
- if the frontend talks only to the Django API and never gets the platform cookie, direct WebSocket connection will not work

---

## Python Example

Python clients can send the cookie explicitly.

```python
import asyncio
import json
import aiohttp

BASE_URL = "https://tracking.totalsecureme.com/api"
EMAIL = "YOUR_EMAIL"
PASSWORD = "YOUR_PASSWORD"


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/session",
            data={"email": EMAIL, "password": PASSWORD},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        ) as response:
            response.raise_for_status()
            await response.json()

        jsessionid = None
        for cookie in session.cookie_jar:
            if cookie.key == "JSESSIONID":
                jsessionid = cookie.value
                break

        if not jsessionid:
            raise RuntimeError("JSESSIONID cookie not found after login")

        ws_headers = {
            "Cookie": f"JSESSIONID={jsessionid}"
        }

        async with session.ws_connect(
            f"{BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://')}/socket",
            headers=ws_headers,
        ) as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    print(json.dumps(payload, indent=2))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break


asyncio.run(main())
```

---

## Node.js Example

In Node.js, headers can be attached directly.

```javascript
import fetch from 'node-fetch';
import WebSocket from 'ws';

const API_BASE = 'https://tracking.totalsecureme.com/api';

async function connect() {
  const response = await fetch(`${API_BASE}/session`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Accept': 'application/json',
    },
    body: new URLSearchParams({
      email: 'YOUR_EMAIL',
      password: 'YOUR_PASSWORD',
    }),
  });

  if (!response.ok) {
    throw new Error(`Login failed: ${response.status}`);
  }

  const setCookie = response.headers.raw()['set-cookie'] || [];
  const sessionCookie = setCookie.find((value) => value.startsWith('JSESSIONID='));

  if (!sessionCookie) {
    throw new Error('JSESSIONID cookie not found');
  }

  const jsessionid = sessionCookie.split(';')[0];

  const socket = new WebSocket('wss://tracking.totalsecureme.com/api/socket', {
    headers: {
      Cookie: jsessionid,
    },
  });

  socket.on('open', () => {
    console.log('Connected');
  });

  socket.on('message', (data) => {
    const payload = JSON.parse(data.toString());
    console.log(payload);
  });

  socket.on('close', () => {
    console.log('Closed');
  });

  socket.on('error', (error) => {
    console.error(error);
  });
}

connect().catch(console.error);
```

---

## Sample Payloads Observed in Issue #7

The following payloads are based on the examples documented in GitHub issue #7.

### 1. Device position update from OsmAnd protocol

Source note:
- protocol: `osmand`
- ingest port mentioned in issue: `5055`

```json
{
  "positions": [
    {
      "id": 22372715,
      "attributes": {
        "distance": 69.48457728306444,
        "totalDistance": 96828.74416857414,
        "motion": true
      },
      "deviceId": 9080,
      "protocol": "osmand",
      "serverTime": "2025-08-19T03:01:33.777+00:00",
      "deviceTime": "2025-08-19T03:01:33.000+00:00",
      "fixTime": "2025-08-19T03:01:33.000+00:00",
      "outdated": false,
      "valid": true,
      "latitude": 8.448725353179041,
      "longitude": 77.01179248407506,
      "altitude": 0,
      "speed": 50,
      "course": 0,
      "address": null,
      "accuracy": 0,
      "network": null,
      "geofenceIds": null
    }
  ]
}
```

### 2. Device state update

```json
{
  "devices": [
    {
      "id": 9080,
      "attributes": {},
      "groupId": 0,
      "calendarId": 0,
      "name": "bus001",
      "uniqueId": "bus001",
      "status": "online",
      "lastUpdate": "2025-08-19T03:01:41.712+00:00",
      "positionId": 22372715,
      "phone": null,
      "model": "BUS",
      "contact": null,
      "category": null,
      "disabled": false,
      "expirationTime": null
    }
  ]
}
```

### 3. RFID / driverChanged event

```json
{
  "events": [
    {
      "attributes": {
        "driverUniqueId": "B600430091058E01",
        "message": "Driver B600430091058E01 has changed in [Test] FMC130 RFID at 2025-08-19 17:52:21\n"
      },
      "deviceId": 61,
      "eventTime": "2025-08-19T12:22:21.000+00:00",
      "geofenceId": 0,
      "id": 29623,
      "maintenanceId": 0,
      "positionId": 251244,
      "type": "driverChanged"
    }
  ]
}
```

### 4. Position payload including RFID-related attributes

```json
{
  "positions": [
    {
      "accuracy": 0,
      "address": null,
      "altitude": 0,
      "attributes": {
        "battery": 4.148,
        "batteryCurrent": 0.036000000000000004,
        "distance": 0,
        "driverUniqueId": "B600430091058E01",
        "event": 78,
        "hdop": 0,
        "hours": 19456000,
        "ignition": true,
        "io69": 2,
        "motion": true,
        "odometer": 5342,
        "operator": 40495,
        "pdop": 0,
        "power": 12.284,
        "priority": 1,
        "rssi": 4,
        "sat": 0,
        "sleepMode": 0,
        "totalDistance": 6593.46626763097
      },
      "course": 0,
      "deviceId": 61,
      "deviceTime": "2025-08-19T12:22:21.000+00:00",
      "fixTime": "2025-08-19T12:22:21.000+00:00",
      "geofenceIds": [6]
    }
  ]
}
```

### 5. Geofence enter event

```json
{
  "events": [
    {
      "attributes": {
        "message": "bus001 has entered geofence Geofence at 2025-08-19 14:33:30"
      },
      "deviceId": 9080,
      "eventTime": "2025-08-19T14:33:30.000+00:00",
      "geofenceId": 623,
      "id": 10789982,
      "maintenanceId": 0,
      "positionId": 22633726,
      "type": "geofenceEnter"
    }
  ]
}
```

### 6. Position update while inside geofence

```json
{
  "positions": [
    {
      "accuracy": 0,
      "address": null,
      "altitude": 0,
      "attributes": {
        "distance": 69.6991226884715,
        "motion": true,
        "totalDistance": 152559.50973921965
      },
      "course": 0,
      "deviceId": 9080,
      "deviceTime": "2025-08-19T14:33:30.000+00:00",
      "fixTime": "2025-08-19T14:33:30.000+00:00",
      "geofenceIds": [623],
      "id": 22633726,
      "latitude": 8.444485618025753,
      "longitude": 77.01649630930385,
      "network": null,
      "outdated": false,
      "protocol": "osmand",
      "serverTime": "2025-08-19T14:33:30.760+00:00",
      "speed": 50,
      "valid": true
    }
  ]
}
```

### 7. Geofence exit event

```json
{
  "events": [
    {
      "attributes": {
        "message": "bus001 has exited geofence Geofence at 2025-08-19 14:33:54"
      },
      "deviceId": 9080,
      "eventTime": "2025-08-19T14:33:54.000+00:00",
      "geofenceId": 623,
      "id": 10790042,
      "maintenanceId": 0,
      "positionId": 22633865,
      "type": "geofenceExit"
    }
  ]
}
```

---

## Fields Commonly Used by Consumers

### Device object

Useful fields:
- `id`
- `name`
- `uniqueId`
- `status`
- `lastUpdate`
- `positionId`
- `model`
- `disabled`

### Position object

Useful fields:
- `id`
- `deviceId`
- `protocol`
- `serverTime`
- `deviceTime`
- `fixTime`
- `latitude`
- `longitude`
- `speed`
- `course`
- `valid`
- `outdated`
- `geofenceIds`
- `attributes`

Frequently useful nested attributes:
- `motion`
- `distance`
- `totalDistance`
- `ignition`
- `driverUniqueId`
- `battery`
- `power`
- `odometer`

### Event object

Useful fields:
- `id`
- `deviceId`
- `type`
- `eventTime`
- `positionId`
- `geofenceId`
- `maintenanceId`
- `attributes.message`
- `attributes.driverUniqueId`

---

## Recommended Processing Rules

1. Parse the message once
2. Branch by top-level keys: `devices`, `positions`, `events`
3. Treat `attributes` as extensible and protocol-dependent
4. Do not hardcode a fixed `attributes` schema for all devices
5. Use `event.type` for event routing logic
6. Use `deviceId` as the main correlation key
7. Use `positionId` when linking an event back to its underlying position
8. Expect sparse payloads; not all fields appear every time

---

## Failure Cases to Expect

### 1. Unauthorized WebSocket connection

Likely causes:
- no `JSESSIONID` cookie sent
- cookie expired
- frontend only has REST API token, not platform session cookie

### 2. Empty or partial payloads

This is normal when only one object type changes. A message might contain only `events` or only `positions`.

### 3. Browser cookie issues

If the frontend and platform API are on different origins, cookie policy can block the session from being sent during WebSocket handshake.

### 4. Reconnect scenarios

Clients should reconnect automatically on disconnect and refresh the session when needed.

---

## Suggested Frontend Integration Strategy

If the product needs live tracking in browser clients, the cleanest approaches are:

### Approach A - Frontend authenticates directly with the platform
Use direct login to the platform so the browser owns the platform session cookie, then open `/api/socket`.

### Approach B - Backend proxy for live stream
Keep current backend token flow for the app, and let the Django backend expose a separate live stream endpoint that internally maintains the platform session and forwards events.

Approach B is usually safer when the app should not expose direct platform authentication behavior to the browser.

---

## Quick Reference

### Login

```bash
curl -i -X POST "https://tracking.totalsecureme.com/api/session" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "email=YOUR_EMAIL&password=YOUR_PASSWORD"
```

### WebSocket

```text
wss://tracking.totalsecureme.com/api/socket
```

### Required auth

```http
Cookie: JSESSIONID=<session-id>
```

### Message envelope

```json
{
  "devices": [...],
  "positions": [...],
  "events": [...]
}
```
