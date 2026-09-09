import time

import ee
from google.auth.exceptions import TransportError
from requests.exceptions import RequestException


def initialize(project: str) -> None:
    """Initialize EE with the caller's standard Earth Engine credentials."""
    for attempt in range(4):
        try:
            ee.Initialize(project=project)
            ee.data.setDeadline(120000)
            return
        except (TransportError, RequestException) as error:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
