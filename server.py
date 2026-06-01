"""Entry point compatível com os scripts do desktop e com execução direta via Python."""

from backend.main import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
