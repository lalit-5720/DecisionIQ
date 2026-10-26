from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth as auth_routes, platform as platform_routes, reports, dashboard, data, explain, forecast, health, pipeline, recommendations, risk, simulate
from app.auth.deps import get_current_user
from app.auth.seed import ensure_users
from app.core.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_users()  # creates the users table and demo accounts on first start
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
secured = [Depends(get_current_user)]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth_routes.router, prefix="/api")
app.include_router(data.router, prefix="/api", dependencies=secured)
app.include_router(pipeline.router, prefix="/api", dependencies=secured)
app.include_router(forecast.router, prefix="/api", dependencies=secured)
app.include_router(risk.router, prefix="/api", dependencies=secured)
app.include_router(recommendations.router, prefix="/api", dependencies=secured)
app.include_router(explain.router, prefix="/api", dependencies=secured)
app.include_router(simulate.router, prefix="/api", dependencies=secured)
app.include_router(dashboard.router, prefix="/api", dependencies=secured)
app.include_router(reports.router, prefix="/api", dependencies=secured)
app.include_router(platform_routes.router, prefix="/api", dependencies=secured)
