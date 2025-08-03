__version__ = "0.2.11"

from labtasker.client.client_api import *
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import *
from labtasker.client.core.paths import get_labtasker_client_config_path
from labtasker.client.core.version_checker import check_package_version
from labtasker.filtering import install_traceback_filter, set_traceback_filter_hook

check_package_version()

# by default, traceback filter is enabled.
# you may disable it via client config
if get_labtasker_client_config_path().exists():
    if get_client_config().enable_traceback_filter:
        install_traceback_filter()
        set_traceback_filter_hook(enabled=True)
