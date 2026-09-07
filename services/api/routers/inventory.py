"""Inventory router: MedicalSupply, SupplyDelivery (inbound), SupplyConsumption
(outbound) — Milestone 5. Every route requires authentication, per the CTO's
explicit instruction in CONTEXT-healthcore.md ("access must be authenticated").
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.core.deps import get_current_user
from database import get_db
from inventory_models import MedicalSupply, SupplyConsumption, SupplyDelivery
from inventory_schemas import (
    InventoryOrderRead,
    MedicalSupplyCreate,
    MedicalSupplyRead,
    SupplyConsumptionCreate,
    SupplyConsumptionRead,
    SupplyDeliveryCreate,
    SupplyDeliveryRead,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


# --- Business logic --------------------------------------------------------

def compute_stock(session: Session, supply_id: int) -> int:
    """current_stock is always computed, never stored:
    SUM(deliveries.quantity) - SUM(consumptions.quantity) for this supply."""
    delivered = session.exec(
        select(func.coalesce(func.sum(SupplyDelivery.quantity), 0)).where(
            SupplyDelivery.supply_id == supply_id
        )
    ).one()
    consumed = session.exec(
        select(func.coalesce(func.sum(SupplyConsumption.quantity), 0)).where(
            SupplyConsumption.supply_id == supply_id
        )
    ).one()
    return delivered - consumed


def _to_supply_read(supply: MedicalSupply, stock: int) -> MedicalSupplyRead:
    return MedicalSupplyRead(
        id=supply.id,
        name=supply.name,
        sku=supply.sku,
        category=supply.category,
        unit=supply.unit,
        country=supply.country,
        current_stock=stock,
    )


# --- Endpoints ---------------------------------------------------------

@router.get("/products", response_model=list[MedicalSupplyRead])
def list_products(
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    supplies = session.exec(select(MedicalSupply)).all()
    return [_to_supply_read(s, compute_stock(session, s.id)) for s in supplies]


@router.post("/products", response_model=MedicalSupplyRead, status_code=201)
def create_product(
    payload: MedicalSupplyCreate,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    supply = MedicalSupply(**payload.model_dump())
    session.add(supply)
    session.commit()
    session.refresh(supply)
    # A brand-new supply has no deliveries/consumptions yet — stock starts at 0.
    return _to_supply_read(supply, 0)


@router.get("/products/{supply_id}", response_model=MedicalSupplyRead)
def get_product(
    supply_id: int,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    supply = session.get(MedicalSupply, supply_id)
    if supply is None:
        raise HTTPException(status_code=404, detail="Medical supply not found")
    return _to_supply_read(supply, compute_stock(session, supply_id))


@router.post("/orders/inbound", response_model=SupplyDeliveryRead, status_code=201)
def create_inbound_order(
    payload: SupplyDeliveryCreate,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    supply = session.get(MedicalSupply, payload.supply_id)
    if supply is None:
        raise HTTPException(status_code=404, detail="Medical supply not found")

    delivery = SupplyDelivery(
        **payload.model_dump(),
        user_uuid=str(current_user["id"]),
    )
    session.add(delivery)
    session.commit()
    session.refresh(delivery)
    return delivery


@router.post("/orders/outbound", response_model=SupplyConsumptionRead, status_code=201)
def create_outbound_order(
    payload: SupplyConsumptionCreate,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    supply = session.get(MedicalSupply, payload.supply_id)
    if supply is None:
        raise HTTPException(status_code=404, detail="Medical supply not found")

    # Reject BEFORE writing if this would push stock negative.
    available = compute_stock(session, payload.supply_id)
    if payload.quantity > available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient stock for supply '{supply.name}'. "
                f"Available: {available}, requested: {payload.quantity}."
            ),
        )

    consumption = SupplyConsumption(
        **payload.model_dump(),
        user_uuid=str(current_user["id"]),
    )
    session.add(consumption)
    session.commit()
    session.refresh(consumption)
    return consumption


@router.get("/orders", response_model=list[InventoryOrderRead])
def list_orders(
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Avoid N+1: fetch every supply once, then look it up in memory per order
    # instead of querying MedicalSupply inside the loop.
    supplies_by_id = {s.id: s for s in session.exec(select(MedicalSupply)).all()}

    deliveries = session.exec(select(SupplyDelivery)).all()
    consumptions = session.exec(select(SupplyConsumption)).all()

    orders: list[InventoryOrderRead] = []

    for d in deliveries:
        supply = supplies_by_id.get(d.supply_id)
        orders.append(
            InventoryOrderRead(
                id=d.id,
                order_type="inbound",
                supply_id=d.supply_id,
                supply_name=supply.name if supply else "Unknown",
                supply_sku=supply.sku if supply else "Unknown",
                quantity=d.quantity,
                clinic_id=d.clinic_id,
                user_uuid=d.user_uuid,
                created_at=d.created_at,
                vendor_name=d.vendor_name,
            )
        )

    for c in consumptions:
        supply = supplies_by_id.get(c.supply_id)
        orders.append(
            InventoryOrderRead(
                id=c.id,
                order_type="outbound",
                supply_id=c.supply_id,
                supply_name=supply.name if supply else "Unknown",
                supply_sku=supply.sku if supply else "Unknown",
                quantity=c.quantity,
                clinic_id=c.clinic_id,
                user_uuid=c.user_uuid,
                created_at=c.created_at,
                consumption_type=c.consumption_type,
            )
        )

    orders.sort(key=lambda o: o.created_at)
    return orders