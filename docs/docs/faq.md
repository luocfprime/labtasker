# Frequently Asked Questions

## Installation

### Do I need to deploy the Labtasker server?

!!! info ""

    It depends:

    1. **If you’re using Labtasker on your own**, you need to deploy the Labtasker server for the client tools to work.
    2. **If you’re working with others** or trust someone who has already deployed the Labtasker server, you don’t need to—just connect to their server. **(Make sure you trust the provider, as your task information is not encrypted.)**

### Do I need to deploy Labtasker server on the cloud? With a domain name?

!!! info ""

    No and no. You can run Labtasker server at localhost (could be your GPU server or your laptop). The only requirement is that the workers can access the server.

### Do I need to use `docker compose` to deploy Labtasker server?

!!! info ""

    No. It is recommended but not mandatory.

    You can set up your own MongoDB service, and use `python -m labtasker.server.run --env-file server.env` to run the server.

    Note: MongoDB requires replica set enabled for DB transactions. You can see how it is done in [docker/mongodb/post-init.d/init-mongo.sh](https://github.com/fkcptlst/labtasker/blob/main/docker/mongodb/post-init.d/init-mongo.sh).


## Usage

### How to run job command with environment variables using `labtasker loop`?

!!! info ""

    ❌ The wrong way:

    ```bash
    labtasker loop -- CUDA_VISIBLE_DEVICES=0 python '%(script)' --dataset '%(dataset)'
    ```

    ✅ The right way:

    ```bash
    CUDA_VISIBLE_DEVICES=0 labtasker loop -- python '%(script)' --dataset '%(dataset)'
    ```

    or else, you may get an error like this:

    ```bash
    FileNotFoundError: [Errno 2] No such file or directory: 'CUDA_VISIBLE_DEVICES=0'
    ```

### What does the "traceback hook" option do in `labtasker init`?

!!! info ""

    The "traceback hook" replaces Python’s default exception handler (`sys.excepthook`) to format error messages and hide
    sensitive information like passwords.

    If you disable this option, Labtasker won’t modify `sys.excepthook`, which can help avoid conflicts with other libraries
    that also use it.
