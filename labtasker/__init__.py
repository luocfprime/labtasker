from labtasker.client.client_api import *
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import *
from labtasker.client.core.paths import get_labtasker_client_config_path
from labtasker.filtering import install_traceback_filter, set_traceback_filter_hook

__version__ = "0.1.2"

install_traceback_filter()

# by default, traceback filter is enabled.
# you may disable it via client config
if get_labtasker_client_config_path().exists():
    set_traceback_filter_hook(enabled=get_client_config().enable_traceback_filter)
