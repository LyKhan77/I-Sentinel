from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.camera import Camera
from app.models.location_group import LocationGroup
from app.schemas.location_group import LocationGroupIn, LocationGroupOut, LocationGroupPatch


router = APIRouter(prefix="/api/v1/location-groups", tags=["location-groups"])


def _duplicate_name(db: Session, name: str, group_id: int | None = None) -> bool:
    query = db.query(LocationGroup).filter(LocationGroup.name == name)
    if group_id is not None:
        query = query.filter(LocationGroup.id != group_id)
    return query.first() is not None


@router.get("", response_model=list[LocationGroupOut])
def list_groups(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(LocationGroup).order_by(LocationGroup.sort_order, LocationGroup.name).all()


@router.post("", response_model=LocationGroupOut)
def create_group(
    body: LocationGroupIn,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "location group name is required")
    if _duplicate_name(db, name):
        raise HTTPException(409, "location group name already exists")
    group = LocationGroup(**body.model_dump(exclude={"name"}), name=name)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.patch("/{group_id}", response_model=LocationGroupOut)
def update_group(
    group_id: int,
    body: LocationGroupPatch,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = db.get(LocationGroup, group_id)
    if group is None:
        raise HTTPException(404, "location group not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(422, "location group name is required")
        if _duplicate_name(db, data["name"], group.id):
            raise HTTPException(409, "location group name already exists")
    for key, value in data.items():
        setattr(group, key, value)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}")
def delete_group(group_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(LocationGroup, group_id)
    if group is None:
        raise HTTPException(404, "location group not found")
    if db.query(Camera).filter(Camera.location_group_id == group.id).first():
        raise HTTPException(409, "location group has cameras; move them first")
    db.delete(group)
    db.commit()
    return {"ok": True}
