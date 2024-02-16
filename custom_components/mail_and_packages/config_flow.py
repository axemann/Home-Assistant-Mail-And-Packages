"""Adds config flow for Mail and Packages."""

from collections.abc import Mapping
import logging
from os import path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import config_entry_oauth2_flow
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RESOURCES,
    CONF_USERNAME,
)
from homeassistant.core import callback

from .oauth import O365Auth, TokenError, MissingTenantID, generate_auth_string

from .const import (
    CONF_ALLOW_EXTERNAL,
    CONF_AMAZON_DAYS,
    CONF_AMAZON_FWDS,
    CONF_CUSTOM_IMG,
    CONF_CUSTOM_IMG_FILE,
    CONF_DURATION,
    CONF_FOLDER,
    CONF_GENERATE_MP4,
    CONF_IMAGE_SECURITY,
    CONF_IMAP_TIMEOUT,
    CONF_PATH,
    CONF_SCAN_INTERVAL,
    CONF_CLIENT_ID,
    CONF_SECRET,
    CONF_O365_TENANT,
    CONF_OUTLOOK_DEFAULTS,
    CONF_METHOD,
    CONF_GMAIL_DEFAULTS,
    CONF_GMAIL_SCOPE,
    CONF_TOKEN,
    DEFAULT_ALLOW_EXTERNAL,
    DEFAULT_AMAZON_DAYS,
    DEFAULT_AMAZON_FWDS,
    DEFAULT_CUSTOM_IMG,
    DEFAULT_CUSTOM_IMG_FILE,
    DEFAULT_FOLDER,
    DEFAULT_GIF_DURATION,
    DEFAULT_IMAGE_SECURITY,
    DEFAULT_IMAP_TIMEOUT,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .helpers import check_ffmpeg, test_login, get_resources, login

_LOGGER = logging.getLogger(__name__)
MENU_OPTIONS = ["manual", "o365"]


async def _check_amazon_forwards(forwards: str) -> tuple:
    """Validate and format amazon forward emails for user input.

    Returns tuple: dict of errors, list of email addresses
    """
    amazon_forwards_list = []
    errors = []

    # Check for amazon domains
    if "@amazon" in forwards:
        errors.append("amazon_domain")

    # Check for commas
    if "," in forwards:
        amazon_forwards_list = forwards.split(",")

    # No forwards
    elif forwards in ["", "(none)", ""]:
        amazon_forwards_list = []

    # If only one address append it to the list
    elif forwards:
        amazon_forwards_list.append(forwards)

    if len(errors) == 0:
        errors.append("ok")

    return errors, amazon_forwards_list


async def _validate_user_input(user_input: dict) -> tuple:
    """Valididate user input from config flow.

    Returns tuple with error messages and modified user_input
    """
    errors = {}

    # Validate amazon forwarding email addresses
    if isinstance(user_input[CONF_AMAZON_FWDS], str):
        status, amazon_list = await _check_amazon_forwards(user_input[CONF_AMAZON_FWDS])
        if status[0] == "ok":
            user_input[CONF_AMAZON_FWDS] = amazon_list
        else:
            user_input[CONF_AMAZON_FWDS] = amazon_list
            errors[CONF_AMAZON_FWDS] = status[0]

    # Check for ffmpeg if option enabled
    if user_input[CONF_GENERATE_MP4]:
        valid = await check_ffmpeg()
    else:
        valid = True

    if not valid:
        errors[CONF_GENERATE_MP4] = "ffmpeg_not_found"

    # validate custom file exists
    if user_input[CONF_CUSTOM_IMG] and CONF_CUSTOM_IMG_FILE in user_input:
        valid = path.isfile(user_input[CONF_CUSTOM_IMG_FILE])
    else:
        valid = True

    if not valid:
        errors[CONF_CUSTOM_IMG_FILE] = "file_not_found"

    # validate scan interval
    if user_input[CONF_SCAN_INTERVAL] < 5:
        errors[CONF_SCAN_INTERVAL] = "scan_too_low"

    # validate imap timeout
    if user_input[CONF_IMAP_TIMEOUT] < 10:
        errors[CONF_IMAP_TIMEOUT] = "timeout_too_low"

    return errors, user_input


def _get_mailboxes(
    host: str, port: int, user: str, pwd: str | None, token: str | None
) -> list:
    """Get list of mailbox folders from mail server."""
    if token:
        account = login(host, port, user, None, token)
    else:
        account = login(host, port, user, pwd, None)

    status, folderlist = account.list()
    mailboxes = []
    if status != "OK":
        _LOGGER.error("Error listing mailboxes ... using default")
        mailboxes.append(DEFAULT_FOLDER)
    else:
        try:
            for i in folderlist:
                mailboxes.append(i.decode().split(' "/" ')[1])
        except IndexError:
            _LOGGER.error("Error creating folder array trying period")
            try:
                for i in folderlist:
                    mailboxes.append(i.decode().split(' "." ')[1])
            except IndexError:
                _LOGGER.error("Error creating folder array, using INBOX")
                mailboxes.append(DEFAULT_FOLDER)

    return mailboxes


def _get_schema_step_o365(user_input: list, default_dict: list) -> Any:
    """Get a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> None:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=_get_default(CONF_USERNAME)): cv.string,
            vol.Required(
                CONF_O365_TENANT, default=_get_default(CONF_O365_TENANT)
            ): cv.string,
            vol.Required(
                CONF_CLIENT_ID, default=_get_default(CONF_CLIENT_ID)
            ): cv.string,
            vol.Required(CONF_SECRET, default=_get_default(CONF_SECRET)): cv.string,
        }
    )


def _get_schema_step_1(user_input: list, default_dict: list) -> Any:
    """Get a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> None:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=_get_default(CONF_HOST)): cv.string,
            vol.Required(CONF_PORT, default=_get_default(CONF_PORT)): vol.Coerce(int),
            vol.Required(CONF_USERNAME, default=_get_default(CONF_USERNAME)): cv.string,
            vol.Required(CONF_PASSWORD, default=_get_default(CONF_PASSWORD)): cv.string,
        }
    )


async def _get_schema_step_2(
    data: list, user_input: list, default_dict: list, hass: HomeAssistant | None = None
) -> Any:
    """Get a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> None:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    # No password, likely oAuth login
    if data[CONF_METHOD] == "o365":
        app = O365Auth(hass, data)
        await app.client()
        mailboxes = _get_mailboxes(
            data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], None, app.token
        )

    else:
        mailboxes = _get_mailboxes(
            data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], data[CONF_PASSWORD]
        )

    return vol.Schema(
        {
            vol.Required(CONF_FOLDER, default=_get_default(CONF_FOLDER)): vol.In(
                mailboxes
            ),
            vol.Required(
                CONF_RESOURCES, default=_get_default(CONF_RESOURCES)
            ): cv.multi_select(get_resources()),
            vol.Optional(
                CONF_AMAZON_FWDS, default=_get_default(CONF_AMAZON_FWDS)
            ): cv.string,
            vol.Optional(CONF_AMAZON_DAYS, default=_get_default(CONF_AMAZON_DAYS)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=_get_default(CONF_SCAN_INTERVAL)
            ): vol.All(vol.Coerce(int)),
            vol.Optional(
                CONF_IMAP_TIMEOUT, default=_get_default(CONF_IMAP_TIMEOUT)
            ): vol.All(vol.Coerce(int)),
            vol.Optional(
                CONF_DURATION, default=_get_default(CONF_DURATION)
            ): vol.Coerce(int),
            vol.Optional(
                CONF_GENERATE_MP4, default=_get_default(CONF_GENERATE_MP4)
            ): cv.boolean,
            vol.Optional(
                CONF_ALLOW_EXTERNAL, default=_get_default(CONF_ALLOW_EXTERNAL)
            ): cv.boolean,
            vol.Optional(
                CONF_CUSTOM_IMG, default=_get_default(CONF_CUSTOM_IMG)
            ): cv.boolean,
        }
    )


def _get_schema_step_3(user_input: list, default_dict: list) -> Any:
    """Get a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str, fallback_default: Any = None) -> None:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    return vol.Schema(
        {
            vol.Optional(
                CONF_CUSTOM_IMG_FILE,
                default=_get_default(CONF_CUSTOM_IMG_FILE, DEFAULT_CUSTOM_IMG_FILE),
            ): cv.string,
        }
    )


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Google Mail OAuth2 authentication."""

    DOMAIN = DOMAIN
    reauth_entry: ConfigEntry | None = None
    _data = {}

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {
            "scope": CONF_GMAIL_SCOPE,
            # Add params to ensure we get back a refresh token
            "access_type": "offline",
            "prompt": "consent",
        }

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create an entry for the flow, or update existing entry."""

        _LOGGER.debug("oAuth config entry called.")

        if self.reauth_entry:
            # update the tokens
            data = self.reauth_entry.data.update(data)
            self.hass.config_entries.async_update_entry(self.reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        def _get_profile() -> str:
            """Get profile from inside the executor."""
            users = build("gmail", "v1", credentials=credentials).users()
            return users.getProfile(userId="me").execute()["emailAddress"]

        credentials = Credentials(data["token"][CONF_TOKEN])
        email = await self.hass.async_add_executor_job(_get_profile)

        self._data[CONF_USERNAME] = email
        self._data[CONF_METHOD] = "gmail"

        return await self._show_config_2(None)

    async def async_step_config_2(self, user_input=None):
        """Configure form step 2."""
        self._errors = {}
        if user_input is not None:
            self._errors, user_input = await _validate_user_input(user_input)
            self._data.update(user_input)
            if len(self._errors) == 0:
                if self._data[CONF_CUSTOM_IMG]:
                    return await self.async_step_config_3()
                return self.async_create_entry(
                    title=self._data[CONF_HOST], data=self._data
                )
            return await self._show_config_2(user_input)

        return await self._show_config_2(user_input)

    async def _show_config_2(self, user_input):
        """Step 2 setup."""
        # Defaults
        defaults = {
            CONF_FOLDER: DEFAULT_FOLDER,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_PATH: self.hass.config.path() + DEFAULT_PATH,
            CONF_DURATION: DEFAULT_GIF_DURATION,
            CONF_IMAGE_SECURITY: DEFAULT_IMAGE_SECURITY,
            CONF_IMAP_TIMEOUT: DEFAULT_IMAP_TIMEOUT,
            CONF_AMAZON_FWDS: DEFAULT_AMAZON_FWDS,
            CONF_AMAZON_DAYS: DEFAULT_AMAZON_DAYS,
            CONF_GENERATE_MP4: False,
            CONF_ALLOW_EXTERNAL: DEFAULT_ALLOW_EXTERNAL,
            CONF_CUSTOM_IMG: DEFAULT_CUSTOM_IMG,
        }

        return self.async_show_form(
            step_id="config_2",
            data_schema=await _get_schema_step_2(
                self._data, user_input, defaults, self.hass
            ),
            errors=self._errors,
        )

    async def async_step_config_3(self, user_input=None):
        """Configure form step 2."""
        self._errors = {}
        if user_input is not None:
            self._data.update(user_input)
            self._errors, user_input = await _validate_user_input(self._data)
            if len(self._errors) == 0:
                return self.async_create_entry(
                    title=self._data[CONF_HOST], data=self._data
                )
            return await self._show_config_3(user_input)

        return await self._show_config_3(user_input)

    async def _show_config_3(self, user_input):
        """Step 3 setup."""
        # Defaults
        defaults = {
            CONF_CUSTOM_IMG_FILE: DEFAULT_CUSTOM_IMG_FILE,
        }

        return self.async_show_form(
            step_id="config_3",
            data_schema=_get_schema_step_3(user_input, defaults),
            errors=self._errors,
        )


@config_entries.HANDLERS.register(DOMAIN)
class MailAndPackagesFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Mail and Packages."""

    VERSION = 4
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    reauth_entry: ConfigEntry | None = None

    def __init__(self):
        """Initialize."""
        self._data = {}
        self._errors = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow initialized by the user."""
        return self.async_show_menu(step_id="user", menu_options=MENU_OPTIONS)

    async def async_step_o365(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Office 365 config flow."""
        self._errors = {}

        if user_input is not None:
            user_input[CONF_METHOD] = "o365"
            user_input.update(CONF_OUTLOOK_DEFAULTS)
            self._data.update(user_input)
            app = O365Auth(self.hass, user_input)
            self._problem = None
            valid = False

            try:
                await app.client()
                valid = test_login(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_USERNAME],
                    None,
                    app.token,
                )
            except TokenError:
                _LOGGER.error("Problems obtaining oAuth token.")
                self._errors["base"] = "token"
            except MissingTenantID:
                _LOGGER.error("Missing tenant ID.")
                self._errors["base"] = "tenant"

            if not valid:
                self._errors["base"] = "communication"

            if not self._errors:
                return await self.async_step_config_2()

            return await self._show_config_o365(user_input)

        return await self._show_config_o365(user_input)

    async def _show_config_o365(self, user_input):
        """Show the configuration form to edit configuration data."""
        # Defaults
        defaults = {}

        return self.async_show_form(
            step_id="o365",
            data_schema=_get_schema_step_o365(user_input, defaults),
            errors=self._errors,
        )

    async def async_step_manual(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            user_input[CONF_METHOD] = "standard"
            self._data.update(user_input)
            valid = await test_login(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if not valid:
                self._errors["base"] = "communication"
            else:
                return await self.async_step_config_2()

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def _show_config_form(self, user_input):
        """Show the configuration form to edit configuration data."""
        # Defaults
        defaults = {
            CONF_PORT: DEFAULT_PORT,
        }

        return self.async_show_form(
            step_id="manual",
            data_schema=_get_schema_step_1(user_input, defaults),
            errors=self._errors,
        )

    async def async_step_config_2(self, user_input=None):
        """Configure form step 2."""
        self._errors = {}
        if user_input is not None:
            self._errors, user_input = await _validate_user_input(user_input)
            self._data.update(user_input)
            if len(self._errors) == 0:
                if self._data[CONF_CUSTOM_IMG]:
                    return await self.async_step_config_3()
                return self.async_create_entry(
                    title=self._data[CONF_HOST], data=self._data
                )
            return await self._show_config_2(user_input)

        return await self._show_config_2(user_input)

    async def _show_config_2(self, user_input):
        """Step 2 setup."""
        # Defaults
        defaults = {
            CONF_FOLDER: DEFAULT_FOLDER,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_PATH: self.hass.config.path() + DEFAULT_PATH,
            CONF_DURATION: DEFAULT_GIF_DURATION,
            CONF_IMAGE_SECURITY: DEFAULT_IMAGE_SECURITY,
            CONF_IMAP_TIMEOUT: DEFAULT_IMAP_TIMEOUT,
            CONF_AMAZON_FWDS: DEFAULT_AMAZON_FWDS,
            CONF_AMAZON_DAYS: DEFAULT_AMAZON_DAYS,
            CONF_GENERATE_MP4: False,
            CONF_ALLOW_EXTERNAL: DEFAULT_ALLOW_EXTERNAL,
            CONF_CUSTOM_IMG: DEFAULT_CUSTOM_IMG,
        }

        return self.async_show_form(
            step_id="config_2",
            data_schema=await _get_schema_step_2(
                self._data, user_input, defaults, self.hass
            ),
            errors=self._errors,
        )

    async def async_step_config_3(self, user_input=None):
        """Configure form step 2."""
        self._errors = {}
        if user_input is not None:
            self._data.update(user_input)
            self._errors, user_input = await _validate_user_input(self._data)
            if len(self._errors) == 0:
                return self.async_create_entry(
                    title=self._data[CONF_HOST], data=self._data
                )
            return await self._show_config_3(user_input)

        return await self._show_config_3(user_input)

    async def _show_config_3(self, user_input):
        """Step 3 setup."""
        # Defaults
        defaults = {
            CONF_CUSTOM_IMG_FILE: DEFAULT_CUSTOM_IMG_FILE,
        }

        return self.async_show_form(
            step_id="config_3",
            data_schema=_get_schema_step_3(user_input, defaults),
            errors=self._errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Redirect to options flow."""
        return MailAndPackagesOptionsFlow(config_entry)


class MailAndPackagesOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Mail and Packages."""

    def __init__(self, config_entry):
        """Initialize."""
        self.config = config_entry
        self._data = dict(config_entry.options)
        self._errors = {}

    async def async_step_init(self, user_input=None):
        """Manage Mail and Packages options."""
        if user_input is not None:
            self._data.update(user_input)

            valid = await test_login(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if not valid:
                self._errors["base"] = "communication"
            else:
                return await self.async_step_options_2()

            return await self._show_options_form(user_input)

        return await self._show_options_form(user_input)

    async def _show_options_form(self, user_input):
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="init",
            data_schema=_get_schema_step_1(user_input, self._data),
            errors=self._errors,
        )

    async def async_step_options_2(self, user_input=None):
        """Configure form step 2."""
        self._errors = {}
        if user_input is not None:
            self._errors, user_input = await _validate_user_input(user_input)
            self._data.update(user_input)
            if len(self._errors) == 0:
                if self._data[CONF_CUSTOM_IMG]:
                    return await self.async_step_options_3()
                return self.async_create_entry(title="", data=self._data)
            return await self._show_step_options_2(user_input)
        return await self._show_step_options_2(user_input)

    async def _show_step_options_2(self, user_input):
        """Step 2 of options."""
        # Defaults
        defaults = {
            CONF_FOLDER: self._data.get(CONF_FOLDER),
            CONF_SCAN_INTERVAL: self._data.get(CONF_SCAN_INTERVAL),
            CONF_PATH: self._data.get(CONF_PATH),
            CONF_DURATION: self._data.get(CONF_DURATION),
            CONF_IMAGE_SECURITY: self._data.get(CONF_IMAGE_SECURITY),
            CONF_IMAP_TIMEOUT: self._data.get(CONF_IMAP_TIMEOUT)
            or DEFAULT_IMAP_TIMEOUT,
            CONF_AMAZON_FWDS: self._data.get(CONF_AMAZON_FWDS) or DEFAULT_AMAZON_FWDS,
            CONF_AMAZON_DAYS: self._data.get(CONF_AMAZON_DAYS) or DEFAULT_AMAZON_DAYS,
            CONF_GENERATE_MP4: self._data.get(CONF_GENERATE_MP4),
            CONF_ALLOW_EXTERNAL: self._data.get(CONF_ALLOW_EXTERNAL),
            CONF_RESOURCES: self._data.get(CONF_RESOURCES),
            CONF_CUSTOM_IMG: self._data.get(CONF_CUSTOM_IMG) or DEFAULT_CUSTOM_IMG,
        }

        return self.async_show_form(
            step_id="options_2",
            data_schema=await _get_schema_step_2(self._data, user_input, defaults),
            errors=self._errors,
        )

    async def async_step_options_3(self, user_input=None):
        """Configure form step 3."""
        self._errors = {}
        if user_input is not None:
            self._data.update(user_input)
            self._errors, user_input = await _validate_user_input(self._data)
            if len(self._errors) == 0:
                return self.async_create_entry(title="", data=self._data)
            return await self._show_step_options_3(user_input)

        return await self._show_step_options_3(user_input)

    async def _show_step_options_3(self, user_input):
        """Step 3 setup."""
        # Defaults
        defaults = {
            CONF_CUSTOM_IMG_FILE: self._data.get(CONF_CUSTOM_IMG_FILE)
            or DEFAULT_CUSTOM_IMG_FILE,
        }

        return self.async_show_form(
            step_id="options_3",
            data_schema=_get_schema_step_3(user_input, defaults),
            errors=self._errors,
        )
