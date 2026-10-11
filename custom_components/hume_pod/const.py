"""Constants for the Hume Body Pod integration."""

from __future__ import annotations

DOMAIN = "hume_pod"
MANUFACTURER = "Hume Health"
MODEL = "Body Pod"

CONF_SEX = "sex"
CONF_BIRTHDATE = "birthdate"
CONF_HEIGHT = "height"
CONF_ACTIVITY = "activity"

SEX_MALE = "male"
SEX_FEMALE = "female"

ACTIVITY_LEVELS = ["sedentary", "moderate", "active"]

# Seconds
SESSION_TIMEOUT = 120
POST_IMPEDANCE_GRACE = 5
COOLDOWN_AFTER_SESSION = 45

EVENT_MEASUREMENT = f"{DOMAIN}_measurement"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
