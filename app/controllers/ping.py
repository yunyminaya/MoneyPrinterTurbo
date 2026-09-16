from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="Verificar la disponibilidad del servicio",
    response_description="pong",
)
def ping(request: Request) -> str:
    return "pong"
