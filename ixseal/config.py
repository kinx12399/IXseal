from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 IXSEAL_* 로 설정한다. 운영에서는 /etc/ixseal/ixseal.env."""

    model_config = SettingsConfigDict(env_prefix="IXSEAL_")

    database_url: str = "postgresql:///ixseal"
    kek_file: str = "/etc/ixseal/kek"
    # 고객용 링크의 앞부분. 개발 중에는 https://<VM 공인 IP>, 운영은 https://seal.ixcloud.net
    public_base_url: str = "https://localhost"
    helpdesk_email: str = "help_cloud@kinx.net"
    # 관리 화면 상단에 표시할 환경 이름 (예: DEV). 비우면 표시하지 않는다.
    env_label: str = ""
    cookie_secure: bool = True
    timezone: str = "Asia/Seoul"

    max_file_mb: int = 20
    max_files: int = 10
    max_total_mb: int = 50
    reveal_session_minutes: int = 10
    retention_days: int = 730

    # 개발 편의: 앱이 /static 을 직접 제공 (운영은 Nginx가 제공)
    serve_static: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
