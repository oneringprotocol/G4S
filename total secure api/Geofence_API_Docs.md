# Geofence API Docs

## Overview

The tracking platform supports the following geofence types:

- Circle
- Polygon
- Polyline

The geofence geometry is provided through the `area` field using WKT-style strings.

Important: coordinate order in this API is:

`latitude longitude`

Not GeoJSON-style `longitude latitude`.

## Base Endpoint

`/api/geofences`

## Authentication

Use Basic Authentication when calling the API.

---

## Geofence Object

Example geofence payload structure:

```json
{
  "id": 123,
  "name": "School Main Gate",
  "description": "Main gate geofence",
  "area": "CIRCLE (10.5276 76.2144, 100)",
  "calendarId": 0,
  "attributes": {
    "type": "entry_zone"
  }
}
```

Fields:

- `id` - Geofence ID
- `name` - Geofence name
- `description` - Optional description
- `area` - Geofence geometry definition
- `calendarId` - Calendar linkage, use `0` for always active
- `attributes` - Optional custom metadata

---

## API Endpoints

### 1. Get all geofences

**GET** `/api/geofences`

Optional query parameters:

- `all`
- `userId`
- `deviceId`
- `groupId`
- `refresh`

Example:

```bash
curl -u username:password \
  -X GET "http://your-server:8082/api/geofences"
```

### 2. Get geofence by ID

**GET** `/api/geofences/{id}`

Example:

```bash
curl -u username:password \
  -X GET "http://your-server:8082/api/geofences/123"
```

### 3. Create geofence

**POST** `/api/geofences`

Example:

```bash
curl -u username:password \
  -H "Content-Type: application/json" \
  -X POST "http://your-server:8082/api/geofences" \
  -d '{
    "name": "School Main Gate",
    "description": "Main gate geofence",
    "area": "CIRCLE (10.5276 76.2144, 100)",
    "calendarId": 0,
    "attributes": {
      "type": "entry_zone"
    }
  }'
```

### 4. Update geofence

**PUT** `/api/geofences/{id}`

Example:

```bash
curl -u username:password \
  -H "Content-Type: application/json" \
  -X PUT "http://your-server:8082/api/geofences/123" \
  -d '{
    "id": 123,
    "name": "Updated School Main Gate",
    "description": "Updated geofence",
    "area": "CIRCLE (10.5276 76.2144, 150)",
    "calendarId": 0,
    "attributes": {
      "type": "entry_zone"
    }
  }'
```

### 5. Delete geofence

**DELETE** `/api/geofences/{id}`

Example:

```bash
curl -u username:password \
  -X DELETE "http://your-server:8082/api/geofences/123"
```

---

## Geofence Types and Examples

## 1. Circle Geofence

Format:

```text
CIRCLE (latitude longitude, radius_in_meters)
```

Example `area` value:

```text
CIRCLE (10.5276 76.2144, 100)
```

Example payload:

```json
{
  "name": "Circle Geofence Example",
  "description": "100 meter radius geofence",
  "area": "CIRCLE (10.5276 76.2144, 100)",
  "calendarId": 0,
  "attributes": {
    "type": "circle_zone"
  }
}
```

## 2. Polygon Geofence

Format:

```text
POLYGON ((lat1 lon1, lat2 lon2, lat3 lon3, ...))
```

Example `area` value:

```text
POLYGON ((10.5276 76.2144, 10.5282 76.2151, 10.5271 76.2160, 10.5265 76.2150, 10.5276 76.2144))
```

Example payload:

```json
{
  "name": "Polygon Geofence Example",
  "description": "Campus boundary geofence",
  "area": "POLYGON ((10.5276 76.2144, 10.5282 76.2151, 10.5271 76.2160, 10.5265 76.2150, 10.5276 76.2144))",
  "calendarId": 0,
  "attributes": {
    "type": "polygon_zone"
  }
}
```

Notes:

- Use at least 3 coordinate points
- Repeating the first point at the end is recommended for a properly closed polygon

## 3. Polyline Geofence

Format:

```text
LINESTRING (lat1 lon1, lat2 lon2, lat3 lon3, ...)
```

Example `area` value:

```text
LINESTRING (10.5276 76.2144, 10.5282 76.2151, 10.5290 76.2163)
```

Example payload:

```json
{
  "name": "Polyline Geofence Example",
  "description": "Route segment geofence",
  "area": "LINESTRING (10.5276 76.2144, 10.5282 76.2151, 10.5290 76.2163)",
  "calendarId": 0,
  "attributes": {
    "type": "route_zone",
    "polylineDistance": 30
  }
}
```

Notes:

- A polyline geofence works as a route/line corridor, not as a filled area
- `polylineDistance` defines how close a position must be to the line to be considered inside the geofence
- If `polylineDistance` is not provided in attributes, the server-wide default is used

---

## Linking Geofences with Devices or Users

Geofences are commonly linked using the permissions endpoint.

Endpoint:

**POST** `/api/permissions`

### Link a device to a geofence

```json
{
  "deviceId": 8,
  "geofenceId": 16
}
```

Example:

```bash
curl -u username:password \
  -H "Content-Type: application/json" \
  -X POST "http://your-server:8082/api/permissions" \
  -d '{
    "deviceId": 8,
    "geofenceId": 16
  }'
```

### Link a user to a geofence

```json
{
  "userId": 5,
  "geofenceId": 16
}
```

### Unlink a device or user from a geofence

**DELETE** `/api/permissions`

Example:

```json
{
  "deviceId": 8,
  "geofenceId": 16
}
```

---

## Quick Reference

### Circle

```json
{
  "area": "CIRCLE (10.5276 76.2144, 100)"
}
```

### Polygon

```json
{
  "area": "POLYGON ((10.5276 76.2144, 10.5282 76.2151, 10.5271 76.2160, 10.5265 76.2150, 10.5276 76.2144))"
}
```

### Polyline

```json
{
  "area": "LINESTRING (10.5276 76.2144, 10.5282 76.2151, 10.5290 76.2163)"
}
```
