"""
Real road distance computation using OSRM (Open Source Routing Machine).

Uses the public OSRM demo server to compute actual driving distances
between GPS coordinates. Falls back to Haversine if OSRM is unavailable.

OSRM Table API docs: http://project-osrm.org/docs/v5.24.0/api/#table-service
"""

import logging
import math
import time as _time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# OSRM public demo server
OSRM_BASE_URL = "https://router.project-osrm.org"
OSRM_MAX_COORDS_PER_REQUEST = 100  # Safe limit for public server
OSRM_REQUEST_TIMEOUT = 60  # seconds
OSRM_RETRY_DELAY = 2.0     # seconds between retries
OSRM_MAX_RETRIES = 3


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance between two GPS points in km."""
    R = 6371.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _haversine_matrix(coords_gps: np.ndarray) -> np.ndarray:
    """Compute distance matrix using Haversine (fallback)."""
    N = coords_gps.shape[0]
    dist = np.zeros((N, N))
    for i in range(N):
        for j in range(i + 1, N):
            d = _haversine_km(
                coords_gps[i, 0], coords_gps[i, 1],
                coords_gps[j, 0], coords_gps[j, 1],
            )
            dist[i, j] = d
            dist[j, i] = d
    return dist


def _coords_to_osrm_string(coords_gps: np.ndarray) -> str:
    """Convert (N,2) GPS array [lon,lat] to OSRM semicolon-delimited string."""
    parts = []
    for i in range(coords_gps.shape[0]):
        parts.append(f"{coords_gps[i, 0]:.6f},{coords_gps[i, 1]:.6f}")
    return ";".join(parts)


def compute_osrm_distance_matrix(
    coords_gps: np.ndarray,
    base_url: str = OSRM_BASE_URL,
    timeout: float = OSRM_REQUEST_TIMEOUT,
) -> Tuple[np.ndarray, bool]:
    """
    Compute road distance matrix using OSRM Table API.

    Parameters
    ----------
    coords_gps : np.ndarray
        Shape (N, 2) with columns [longitude, latitude] in decimal degrees.
    base_url : str
        OSRM server URL.
    timeout : float
        Request timeout in seconds.

    Returns
    -------
    dist_matrix : np.ndarray
        Shape (N, N) distance matrix in km.
    used_osrm : bool
        True if OSRM was used, False if fell back to Haversine.
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed. Falling back to Haversine distance.")
        return _haversine_matrix(coords_gps), False

    N = coords_gps.shape[0]

    if N <= OSRM_MAX_COORDS_PER_REQUEST:
        return _osrm_table_request(coords_gps, base_url, timeout)
    else:
        return _osrm_table_batched(coords_gps, base_url, timeout)


def _osrm_table_request(
    coords_gps: np.ndarray,
    base_url: str,
    timeout: float,
) -> Tuple[np.ndarray, bool]:
    """Single OSRM table request for all coordinates."""
    import requests

    coord_str = _coords_to_osrm_string(coords_gps)
    url = f"{base_url}/table/v1/driving/{coord_str}?annotations=distance"

    for attempt in range(OSRM_MAX_RETRIES):
        try:
            logger.info(f"OSRM table request ({coords_gps.shape[0]} points), attempt {attempt + 1}...")
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok":
                msg = data.get("message", data.get("code", "unknown"))
                logger.warning(f"OSRM error: {msg}")
                if attempt < OSRM_MAX_RETRIES - 1:
                    _time.sleep(OSRM_RETRY_DELAY)
                    continue
                break

            # OSRM returns distances in meters
            distances_m = np.array(data["distances"], dtype=float)
            distances_km = distances_m / 1000.0

            # Ensure symmetric and zero diagonal
            distances_km = (distances_km + distances_km.T) / 2.0
            np.fill_diagonal(distances_km, 0.0)

            # Replace any null/None with Haversine fallback
            null_mask = np.isnan(distances_km) | (distances_km < 0)
            if np.any(null_mask):
                haversine = _haversine_matrix(coords_gps)
                distances_km[null_mask] = haversine[null_mask]
                logger.warning(f"Replaced {null_mask.sum()} null OSRM entries with Haversine")

            logger.info(f"OSRM distance matrix computed: {distances_km.shape}, "
                        f"range [{distances_km[distances_km > 0].min():.2f}, "
                        f"{distances_km.max():.2f}] km")
            return distances_km, True

        except requests.exceptions.Timeout:
            logger.warning(f"OSRM request timed out (attempt {attempt + 1})")
            if attempt < OSRM_MAX_RETRIES - 1:
                _time.sleep(OSRM_RETRY_DELAY)
        except requests.exceptions.RequestException as e:
            logger.warning(f"OSRM request failed: {e}")
            if attempt < OSRM_MAX_RETRIES - 1:
                _time.sleep(OSRM_RETRY_DELAY)

    logger.warning("All OSRM attempts failed. Falling back to Haversine distance.")
    return _haversine_matrix(coords_gps), False


def _osrm_sub_table(
    sub_coords: np.ndarray,
    sources: Optional[list],
    destinations: Optional[list],
    base_url: str,
    timeout: float,
) -> Optional[np.ndarray]:
    """
    Query OSRM Table API for a sub-matrix.

    Parameters
    ----------
    sub_coords : np.ndarray
        Shape (M, 2) subset of coordinates [lon, lat].
    sources : list or None
        Indices into sub_coords to use as origins (None = all).
    destinations : list or None
        Indices into sub_coords to use as destinations (None = all).

    Returns
    -------
    np.ndarray or None
        (len(sources), len(destinations)) distances in km, or None on failure.
    """
    import requests

    coord_str = _coords_to_osrm_string(sub_coords)
    params = "annotations=distance"
    if sources is not None:
        params += "&sources=" + ";".join(str(i) for i in sources)
    if destinations is not None:
        params += "&destinations=" + ";".join(str(i) for i in destinations)

    url = f"{base_url}/table/v1/driving/{coord_str}?{params}"

    for attempt in range(OSRM_MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok":
                logger.warning(f"OSRM sub-table error: {data.get('message', 'unknown')}")
                if attempt < OSRM_MAX_RETRIES - 1:
                    _time.sleep(OSRM_RETRY_DELAY)
                    continue
                return None
            return np.array(data["distances"], dtype=float) / 1000.0
        except Exception as e:
            logger.warning(f"OSRM sub-table request failed: {e}")
            if attempt < OSRM_MAX_RETRIES - 1:
                _time.sleep(OSRM_RETRY_DELAY)
    return None


def _osrm_table_batched(
    coords_gps: np.ndarray,
    base_url: str,
    timeout: float,
) -> Tuple[np.ndarray, bool]:
    """
    Batched OSRM table requests for large coordinate sets (N > 100).

    Splits coordinates into chunks of ≤50, then queries each pair of chunks
    so every OSRM request has at most 100 coordinates in the URL path.
    Assembles the full N×N distance matrix from sub-matrices.
    """
    N = coords_gps.shape[0]
    chunk_size = 50  # Each chunk ≤50, so pair ≤100 (within OSRM limit)

    # Split indices into chunks
    chunks = []
    for start in range(0, N, chunk_size):
        end = min(start + chunk_size, N)
        chunks.append(list(range(start, end)))

    dist_matrix = np.zeros((N, N))
    used_osrm = True
    haversine = None  # Lazily computed if needed

    n_chunks = len(chunks)
    total_pairs = n_chunks * n_chunks
    pair_idx = 0

    for i in range(n_chunks):
        for j in range(n_chunks):
            pair_idx += 1
            chunk_i = chunks[i]  # source rows
            chunk_j = chunks[j]  # destination columns

            if i == j:
                # Same chunk: query all-to-all within chunk
                if len(chunk_i) == 1:
                    # Single point self-distance is trivially 0
                    dist_matrix[chunk_i[0], chunk_i[0]] = 0.0
                    _time.sleep(0.1)
                    continue
                sub_coords = coords_gps[chunk_i]
                logger.info(f"OSRM chunk ({pair_idx}/{total_pairs}): "
                            f"[{chunk_i[0]}:{chunk_i[-1]+1}] self ({len(chunk_i)} pts)")
                sub_dist = _osrm_sub_table(sub_coords, None, None, base_url, timeout)
            else:
                # Different chunks: combine coordinates, specify sources/destinations
                combined_indices = chunk_i + chunk_j
                sub_coords = coords_gps[combined_indices]
                sources_local = list(range(len(chunk_i)))
                dests_local = list(range(len(chunk_i), len(combined_indices)))
                logger.info(f"OSRM chunk ({pair_idx}/{total_pairs}): "
                            f"[{chunk_i[0]}:{chunk_i[-1]+1}] → [{chunk_j[0]}:{chunk_j[-1]+1}] "
                            f"({len(combined_indices)} pts)")
                sub_dist = _osrm_sub_table(sub_coords, sources_local, dests_local,
                                           base_url, timeout)

            if sub_dist is not None:
                # Place sub-matrix into full matrix
                for ri, src_idx in enumerate(chunk_i):
                    for ci, dst_idx in enumerate(chunk_j):
                        dist_matrix[src_idx, dst_idx] = sub_dist[ri, ci]
            else:
                # Fallback to Haversine for this chunk pair
                logger.warning(f"Chunk pair ({i},{j}) failed, using Haversine fallback")
                if haversine is None:
                    haversine = _haversine_matrix(coords_gps)
                used_osrm = False
                for src_idx in chunk_i:
                    for dst_idx in chunk_j:
                        dist_matrix[src_idx, dst_idx] = haversine[src_idx, dst_idx]

            _time.sleep(1.0)  # Rate limiting between requests

    # Symmetrize and zero diagonal
    dist_matrix = (dist_matrix + dist_matrix.T) / 2.0
    np.fill_diagonal(dist_matrix, 0.0)

    if used_osrm:
        logger.info(f"OSRM batched distance matrix computed: ({N},{N}), "
                    f"range [{dist_matrix[dist_matrix > 0].min():.2f}, "
                    f"{dist_matrix.max():.2f}] km")

    return dist_matrix, used_osrm


def get_osrm_route_geometry(
    coords_gps: np.ndarray,
    waypoint_indices: list,
    base_url: str = OSRM_BASE_URL,
    timeout: float = OSRM_REQUEST_TIMEOUT,
) -> Optional[list]:
    """
    Get the actual road geometry for a sequence of waypoints using OSRM Route API.

    Parameters
    ----------
    coords_gps : np.ndarray
        Shape (N, 2) with [longitude, latitude]. Full coordinate set.
    waypoint_indices : list
        Ordered list of indices into coords_gps to visit (e.g. [0, 3, 7, 0]).
    base_url : str
    timeout : float

    Returns
    -------
    list or None
        List of [lat, lon] pairs forming the road geometry, or None on failure.
    """
    try:
        import requests
        import json
    except ImportError:
        return None

    if len(waypoint_indices) < 2:
        return None

    # Build coordinate string for the waypoints
    parts = []
    for idx in waypoint_indices:
        lon, lat = coords_gps[idx]
        parts.append(f"{lon:.6f},{lat:.6f}")
    coord_str = ";".join(parts)

    url = f"{base_url}/route/v1/driving/{coord_str}?overview=full&geometries=geojson"

    for attempt in range(OSRM_MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok":
                if attempt < OSRM_MAX_RETRIES - 1:
                    _time.sleep(OSRM_RETRY_DELAY)
                    continue
                return None

            # GeoJSON coordinates are [lon, lat], convert to [lat, lon] for folium
            geojson_coords = data["routes"][0]["geometry"]["coordinates"]
            return [[c[1], c[0]] for c in geojson_coords]

        except Exception:
            if attempt < OSRM_MAX_RETRIES - 1:
                _time.sleep(OSRM_RETRY_DELAY)

    return None
