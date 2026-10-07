import os

import uvicorn

if __name__ == "__main__":
    # Listen on the local network by default so phones and other LAN devices
    # can open the storefront and operations console. Override EBAPHONE_HOST
    # to 127.0.0.1 when a machine-local-only launch is preferred.
    host = os.getenv("EBAPHONE_HOST", "0.0.0.0")
    port = int(os.getenv("EBAPHONE_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port)
