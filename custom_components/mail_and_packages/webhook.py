"""Webhoook handler."""
import logging
from uuid import uuid4

from homeassistant.components import cloud, webhook
from homeassistant.const import CONF_WEBHOOK_ID, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_O365_TENANT, CONF_METHOD, CONF_CLIENT_ID, CONF_O365_SCOPE, CONF_SECRET, DOMAIN, CONF_CLOUDHOOK_URL

_LOGGER = logging.getLogger(__name__)


class oAuthHandler():
    """Class for handling oAuth requests."""
    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.config = config


def validate_webhook_requirements(hass: HomeAssistant) -> bool:
    """Ensure Home Assistant is setup properly to receive webhooks."""
    if cloud.async_active_subscription(hass):
        return True
    if hass.data[DOMAIN][CONF_CLOUDHOOK_URL] is not None:
        return True
    return get_webhook_url(hass).lower().startswith("https://")


def get_webhook_url(hass: HomeAssistant) -> str:
    """Get the URL of the webhook.

    Return the cloudhook if available, otherwise local webhook.
    """
    cloudhook_url = hass.data[DOMAIN][CONF_CLOUDHOOK_URL]
    if cloud.async_active_subscription(hass) and cloudhook_url is not None:
        return cloudhook_url
    return webhook.async_generate_url(hass, hass.data[DOMAIN][CONF_WEBHOOK_ID])        



    async def webhook_handler(self, webhook_id: str, request):
        """Handle a webhook event."""
        data = await request.json()

        if "code" not in request:
            _LOGGER.error("Authorization code missing from reply.")
            return
        _LOGGER.debug("Attempting to aquire token.")
        await self.get_refresh_token(self.hass, request["code"])

    async def get_refresh_token(self, code: str):
        """Obtain refresh token."""
        session = async_get_clientsession(self.hass)
        method = "post"
        params = None
        headers = None

        if self.config[CONF_METHOD] == "o365":
            url = f"https://login.microsoftonline.com/{self.config[CONF_O365_TENANT]}/oauth2/v2.0/token"
            data = {
                CONF_CLIENT_ID: self.config[CONF_CLIENT_ID],
                "scope": CONF_O365_SCOPE,
                "code": code,
                "redirect_uri": "https://localhost",
                "grant_type": "authorization_code",
                CONF_SECRET: self.config[CONF_SECRET],
                }
        
        async with session.request(method, url, params=params, json=data, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            
            if resp.status in (400,422,429, 500):
                _LOGGER.error("Problem getting token.")



