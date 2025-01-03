# Installation

To use Labtasker, you need to deploy a server and install client on your worker machines.

The deployment of Labtasker is straightforward. Basically, you need to:

1. Deploy Labtasker server (e.g. on a cloud server).
2. Install Labtasker Python client on your local machine.

## Deploy server

You can deploy Labtasker server on a cloud server via docker-compose.

```bash
git clone https://github.com/fkcptlst/labtasker.git
cd labtasker
```

Copy the `server.example.env` file to `server.env` and change the environment variables to your own values.

```bash
cp server.example.env server.env

# Edit the server.env file
# ...
```

Then, run the following command to start the server:

```bash
docker-compose --env-file server.env up -d
```

## Install client

The client is a Python package that you can install on your local machine.

```bash
pip install labtasker
```
