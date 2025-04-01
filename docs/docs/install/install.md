# Installation

!!! info "Installation"

    To use Labtasker, you need to:

    1. Have a deployed server. See [Deploy Server](./deployment.md) for more details.
    2. Install labtasker client tools via pip.

The client tools is a Python package that you can install on your local machine.

!!! note "System Requirements"

    Labtasker is unit tested on Windows, Linux and MacOS.
    Nevertheless, it is recommended to use a POSIX compliant system.

=== "From PyPI"

    ```bash
    pip install labtasker
    ```

    To install bundled plugins, run with optional dependency install:

    ```bash
    pip install 'labtasker[plugins]'
    ```

=== "From Github"

    ```bash
    pip install git+https://github.com/luocfprime/labtasker.git
    ```

    To install bundled plugins, run with optional dependency install:

    ```bash
    pip install 'labtasker[plugins] @ git+https://github.com/luocfprime/labtasker.git'
    ```
