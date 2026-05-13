import logging

from fastapi import FastAPI

from db.schema import init_db, migrate_db
from routers.transactions import router as transactions_router
from routers.wiki import router as wiki_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PerfictAI", version="0.1.0")

app.include_router(transactions_router)
app.include_router(wiki_router)


@app.on_event("startup")
def startup() -> None:
    logger.info("Initialising local database …")
    init_db()
    migrate_db()
    logger.info("Database ready.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Nightly wiki refresh — add to system crontab for each user:
#   0 2 * * * curl -s -H "X-User-ID: alice" -X POST http://localhost:8000/wiki/refresh
#   0 2 * * * curl -s -H "X-User-ID: bob" -X POST http://localhost:8000/wiki/refresh
