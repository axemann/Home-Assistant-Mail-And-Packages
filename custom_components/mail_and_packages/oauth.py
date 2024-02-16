"""Mail and Packages oAuth methods."""

import logging
import msal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIENT_ID,
    CONF_SECRET,
    CONF_O365_TENANT,
    CONF_O365_SCOPE,
    CONF_TOKEN,
)

_LOGGER = logging.getLogger(__name__)


def generate_auth_string(user, token) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


class O365Auth:
    """Class for Mail and Packages Office365 handling."""

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
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

    async def client(self) -> None:
        """Setup client oauth."""
        if not self._authority:
            self._authority = (
                f"https://login.microsoftonline.com/{self.config[CONF_O365_TENANT]}"
            )
        _LOGGER.debug("Authority: %s", self._authority)
        app = await self.hass.async_add_executor_job(
            msal.ConfidentialClientApplication,
            self.config[CONF_CLIENT_ID],
            self.config[CONF_SECRET],
            self._authority,
        )

        result = await self.hass.async_add_executor_job(
                app.acquire_token_silent,
                self._scope, 
                None,
            )

        if not result:
            _LOGGER.debug("No token cached, getting new token.")
            result = await self.hass.async_add_executor_job(
                    app.acquire_token_for_client,
                    self._scope,
                )

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
