"""Import-string target lets Uvicorn spawn independent Core web processes."""
import os
from .settings import ServiceSettings
from .app import create_service_app
app=create_service_app(ServiceSettings.load(os.environ['OFFERPATH_SERVICE_ROLE']))
