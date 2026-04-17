import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    campaign_id: str
    base_url: str
    mechanics_folder: str
    overview_folder: str
    history_folder: str


def load_config() -> Config:
    api_key = os.getenv("ARCHIVIST_API_KEY", "").strip()
    campaign_id = os.getenv("ARCHIVIST_CAMPAIGN_ID", "").strip()
    missing = [
        name
        for name, value in [
            ("ARCHIVIST_API_KEY", api_key),
            ("ARCHIVIST_CAMPAIGN_ID", campaign_id),
        ]
        if not value
    ]
    if missing:
        raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

    return Config(
        api_key=api_key,
        campaign_id=campaign_id,
        base_url=os.getenv("ARCHIVIST_BASE_URL", "https://api.myarchivist.ai").rstrip("/"),
        mechanics_folder=os.getenv("ARCHIVIST_MECHANICS_FOLDER", "Items/Mechanics"),
        overview_folder=os.getenv("ARCHIVIST_OVERVIEW_FOLDER", "Campaign Overview"),
        history_folder=os.getenv("ARCHIVIST_HISTORY_FOLDER", "Summary History"),
    )
