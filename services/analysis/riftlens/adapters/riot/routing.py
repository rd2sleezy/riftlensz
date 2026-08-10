from __future__ import annotations

from enum import StrEnum

PLATFORM_TO_REGION: dict[str, str] = {
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "na1": "americas",
    "eun1": "europe",
    "euw1": "europe",
    "ru": "europe",
    "tr1": "europe",
    "jp1": "asia",
    "kr": "asia",
    "oc1": "sea",
    "ph2": "sea",
    "sg2": "sea",
    "th2": "sea",
    "tw2": "sea",
    "vn2": "sea",
}

PLATFORM_HOSTS: dict[str, str] = {
    platform: f"https://{platform}.api.riotgames.com" for platform in PLATFORM_TO_REGION
}

REGION_HOSTS: dict[str, str] = {
    "americas": "https://americas.api.riotgames.com",
    "europe": "https://europe.api.riotgames.com",
    "asia": "https://asia.api.riotgames.com",
    "sea": "https://sea.api.riotgames.com",
}


class Platform(StrEnum):
    BR1 = "br1"
    EUN1 = "eun1"
    EUW1 = "euw1"
    JP1 = "jp1"
    KR = "kr"
    LA1 = "la1"
    LA2 = "la2"
    NA1 = "na1"
    OC1 = "oc1"
    PH2 = "ph2"
    RU = "ru"
    SG2 = "sg2"
    TH2 = "th2"
    TR1 = "tr1"
    TW2 = "tw2"
    VN2 = "vn2"


class Region(StrEnum):
    AMERICAS = "americas"
    EUROPE = "europe"
    ASIA = "asia"
    SEA = "sea"


def region_for(platform: str) -> str:
    """Return the regional routing value for a platform id. Assumes a known shard."""
    key = platform.lower()
    try:
        return PLATFORM_TO_REGION[key]
    except KeyError as exc:
        raise ValueError(f"unknown riot platform: {platform}") from exc


def platform_host(platform: str) -> str:
    """Return the platform API origin. Assumes a known shard."""
    key = platform.lower()
    try:
        return PLATFORM_HOSTS[key]
    except KeyError as exc:
        raise ValueError(f"unknown riot platform: {platform}") from exc


def region_host(region: str) -> str:
    """Return the regional API origin. Assumes americas|europe|asia|sea."""
    key = region.lower()
    try:
        return REGION_HOSTS[key]
    except KeyError as exc:
        raise ValueError(f"unknown riot region: {region}") from exc
