"""Geolocation utilities for hospital discovery.

Uses Haversine formula for distance calculations between coordinates.
Works with OpenStreetMap Nominatim for geocoding and Overpass for raw location data.
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class Coordinates:
    """Latitude and longitude pair."""
    latitude: float
    longitude: float

    def distance_to(self, other: "Coordinates", unit: str = "km") -> float:
        """Calculate distance to another point using Haversine formula."""
        return haversine_distance(
            self.latitude, self.longitude,
            other.latitude, other.longitude,
            unit=unit
        )


def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    unit: str = "km"
) -> float:
    """
    Calculate the great circle distance between two points on Earth.

    Args:
        lat1, lon1: Latitude and longitude of point 1 in degrees
        lat2, lon2: Latitude and longitude of point 2 in degrees
        unit: "km" for kilometers, "mi" for miles

    Returns:
        Distance between the points in the specified unit
    """
    R = 6371.0 if unit == "km" else 3958.8  # Earth radius

    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def parse_coordinates(
    latitude: Optional[float],
    longitude: Optional[float]
) -> Optional[Coordinates]:
    """Create Coordinates from optional lat/lon values."""
    if latitude is None or longitude is None:
        return None
    return Coordinates(latitude=latitude, longitude=longitude)


def find_nearby_hospitals(
    hospitals: list[dict],
    patient_lat: float,
    patient_lon: float,
    max_distance_km: float = 50.0
) -> list[dict]:
    """
    Filter hospitals within a given distance of the patient's location.

    Args:
        hospitals: List of hospital dicts with 'latitude' and 'longitude' keys
        patient_lat: Patient's latitude
        patient_lon: Patient's longitude
        max_distance_km: Maximum distance in kilometers

    Returns:
        Hospitals sorted by distance, each with 'distance_km' added
    """
    patient_coords = Coordinates(latitude=patient_lat, longitude=patient_lon)
    results = []

    for hospital in hospitals:
        h_lat = hospital.get("latitude")
        h_lon = hospital.get("longitude")
        if h_lat is None or h_lon is None:
            continue  # Skip hospitals without location data

        dist = patient_coords.distance_to(Coordinates(latitude=h_lat, longitude=h_lon))
        if dist <= max_distance_km:
            hospital_with_dist = dict(hospital)
            hospital_with_dist["distance_km"] = round(dist, 2)
            results.append(hospital_with_dist)

    return sorted(results, key=lambda h: h["distance_km"])


def degrees_to_dms(deg: float) -> tuple[int, int, int]:
    """Convert decimal degrees to degrees, minutes, seconds."""
    sign = -1 if deg < 0 else 1
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = int((deg - d - m / 60) * 3600)
    return (sign * d, m, s)