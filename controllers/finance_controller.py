"""Finance Pack controller — typed endpoints for structured financial data."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_finance_service
from models.schemas import FinanceRequest, FinanceMacroRequest, FinanceErpRequest
from services.finance_service import FinanceService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/consensus")
async def finance_consensus(
    request: FinanceRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.consensus(request.symbol, request.market)
    except Exception as exc:
        logger.error("finance_consensus_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/insider")
async def finance_insider(
    request: FinanceRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.insider(request.symbol, request.market)
    except Exception as exc:
        logger.error("finance_insider_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/corp_actions")
async def finance_corp_actions(
    request: FinanceRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.corp_actions(request.symbol, request.market)
    except Exception as exc:
        logger.error("finance_corp_actions_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/macro")
async def finance_macro(
    request: FinanceMacroRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.macro(request.country)
    except Exception as exc:
        logger.error("finance_macro_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/erp")
async def finance_erp(
    request: FinanceErpRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.erp(request.home, request.foreign)
    except Exception as exc:
        logger.error("finance_erp_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/snapshot_us")
async def finance_snapshot_us(
    request: FinanceRequest,
    finance_service: FinanceService = Depends(get_finance_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await finance_service.snapshot_us(request.symbol)
    except Exception as exc:
        logger.error("finance_snapshot_us_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
