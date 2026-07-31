"""Entry point for local development.

Usage: python main.py
Production: uvicorn src.app.main:app
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.app.main:app", host="127.0.0.1", port=8000, reload=True)
