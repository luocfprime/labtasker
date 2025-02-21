import argparse

import uvicorn

from labtasker.server.config import get_server_config, init_server_config
from labtasker.server.endpoints import app
from labtasker.server.logging import log_config


def parse_args():
    parser = argparse.ArgumentParser(description="Start the LabTasker server.")
    parser.add_argument("--env-file", type=str, help="Path to the environment file")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    init_server_config(args.env_file)

    config = get_server_config()
    uvicorn.run(app, host=config.api_host, port=config.api_port, log_config=log_config)
