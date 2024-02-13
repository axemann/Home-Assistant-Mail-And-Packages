"""Mail and Packages oAuth methods."""

import logging
import msal
from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_O365_CLIENT_ID,
    CONF_O365_SECRET,
    CONF_O365_TENANT,
    CONF_O365_SCOPE,
    CONF_TOKEN,
)

_LOGGER = logging.getLogger(__name__)


def generate_auth_string(user, token) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


class O365Auth:
    """Class for Mail and Packages OAuth handling."""

    def __init__(self, config: ConfigEntry) -> None:
        """Initialize."""
        self.token = None
        self.config = config
        self._scope = CONF_O365_SCOPE
        self._authority = None
        self.token = None
        self._set_authority()

    def _set_authority(self) -> None:
        """Setup the authority URL."""
        if self.config[CONF_O365_TENANT] is None:
            _LOGGER.error("No tenant ID configured.")
            raise MissingTenantID
        self._authority = (
            f"https://login.microsoftonline.com/{self.config[CONF_O365_TENANT]}"
        )

    def client(self) -> None:
        """Setup client oauth."""
        app = msal.ConfidentialClientApplication(
            self.config[CONF_O365_CLIENT_ID],
            self._authority,
            self.config[CONF_O365_SECRET],
        )

        result = app.acquire_token_silent(self._scope, account=None)

        if not result:
            _LOGGER.debug("No token cached, getting new token.")
            result = app.acquire_token_for_client(self._scope)

        if CONF_TOKEN in result:
            self.token = result[CONF_TOKEN]
        else:
            _LOGGER.error(
                "An error occured: %s\nDescription: %s\nID: %s",
                result["error"],
                result["error_description"],
                result["correlation_id"],
            )
            raise TokenError


class MissingTenantID(Exception):
    """Exception for missing tenant ID."""


class TokenError(Exception):
    """Exception for missing tenant ID."""
