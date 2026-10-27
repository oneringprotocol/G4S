#!/usr/bin/env python3
"""
Totalsecure tracking API Authentication Token Example

This script demonstrates how to:
1. Create a session using email/password
2. Generate an authorization token using the session cookies
"""

import requests


# Configuration - Replace with your actual values
BASE_URL = "https://tracking.totalsecureme.com/api"
EMAIL = "YOUR_LOGIN"
PASSWORD = "YOUR_PASSWORD"


class TraccarClient:
    """Traccar API client with session and token-based authentication."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.user_info = None
        self.token = None

    def login(self, email: str, password: str) -> dict | None:
        """
        Create a session using email and password.

        Args:
            email: User email
            password: User password

        Returns:
            Session data dict on success, None on failure
        """
        url = f"{self.base_url}/session"

        response = self.session.post(
            url,
            data={"email": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        if response.status_code == 200:
            self.user_info = response.json()
            print("Session created successfully!")
            return self.user_info
        else:
            print(f"Failed to create session: {response.status_code}")
            print(response.text)
            return None

    def get_auth_token(self, expiration: str | None = None) -> str | None:
        """
        Generate an authorization token using existing session cookies.

        Args:
            expiration: Optional expiration datetime (ISO 8601 format)

        Returns:
            Token string on success, None on failure
        """
        url = f"{self.base_url}/session/token"

        data = {}
        if expiration:
            data["expiration"] = expiration

        response = self.session.post(
            url,
            data=data if data else None,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        if response.status_code == 200:
            self.token = response.text
            print("Token generated successfully!")
            return self.token
        else:
            print(f"Failed to generate token: {response.status_code}")
            print(response.text)
            return None

    def _get_headers(self) -> dict:
        """Get authorization headers using stored token."""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def get_devices(self) -> list | None:
        """
        Fetch devices using token authentication.

        Returns:
            List of devices on success, None on failure
        """
        url = f"{self.base_url}/devices"
        response = requests.get(url, headers=self._get_headers())

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch devices: {response.status_code}")
            return None

    def get_positions(self, device_id: int | None = None) -> list | None:
        """
        Fetch positions using token authentication.

        Args:
            device_id: Optional device ID to filter positions

        Returns:
            List of positions on success, None on failure
        """
        url = f"{self.base_url}/positions"
        params = {"deviceId": device_id} if device_id else {}
        response = requests.get(url, headers=self._get_headers(), params=params)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch positions: {response.status_code}")
            return None

    def get_geofences(self) -> list | None:
        """Fetch geofences using token authentication."""
        url = f"{self.base_url}/geofences"
        response = requests.get(url, headers=self._get_headers())

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch geofences: {response.status_code}")
            return None

    def logout(self) -> bool:
        """Delete the current session and clear token."""
        url = f"{self.base_url}/session"
        response = self.session.delete(url)
        self.token = None
        return response.status_code == 204


def main():
    # Create client and login
    client = TraccarClient(BASE_URL)

    print("=" * 50)
    print("Step 1: Login with Email/Password")
    print("=" * 50)
    user_info = client.login(EMAIL, PASSWORD)
    if not user_info:
        print("Login failed. Exiting.")
        return

    print(f"Logged in as: {user_info.get('name')} ({user_info.get('email')})")
    print(f"Administrator: {user_info.get('administrator')}")

    # Generate token using session cookies
    print("\n" + "=" * 50)
    print("Step 2: Generate Auth Token (using session)")
    print("=" * 50)
    token = client.get_auth_token()
    if not token:
        print("Failed to get token. Exiting.")
        return

    print(f"Token: {token[:50]}..." if len(token) > 50 else f"Token: {token}")

    # All subsequent requests use the token
    print("\n" + "=" * 50)
    print("Step 3: Fetch Devices (using token)")
    print("=" * 50)
    devices = client.get_devices()
    if devices:
        print(f"Found {len(devices)} device(s):")
        for device in devices:
            print(f"  - {device.get('name')} (ID: {device.get('uniqueId')})")

    print("\n" + "=" * 50)
    print("Step 4: Fetch Positions (using token)")
    print("=" * 50)
    positions = client.get_positions()
    if positions:
        print(f"Found {len(positions)} position(s)")
    else:
        print("No positions found")

    print("\n" + "=" * 50)
    print("Step 5: Fetch Geofences (using token)")
    print("=" * 50)
    geofences = client.get_geofences()
    if geofences:
        print(f"Found {len(geofences)} geofence(s):")
        for gf in geofences:
            print(f"  - {gf.get('name')}")
    else:
        print("No geofences found")


if __name__ == "__main__":
    main()
