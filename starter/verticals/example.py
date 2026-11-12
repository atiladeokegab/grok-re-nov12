"""An example vertical: copy this file to add one. A router, an optional seed, optional tools."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from starter.core.errors import ConflictError, NotFound
from starter.core.store import Store
from starter.runtime.deps import StoreDep, require_token

router = APIRouter(prefix="/api/example", tags=["example"])


class Item(BaseModel):
    id: str
    name: str


def seed(store: Store) -> None:
    if "items" not in store.snapshot():
        store.mutate(lambda d: d.setdefault("items", [{"id": "1", "name": "Example item"}]))


@router.get("/items")
def list_items(store: StoreDep) -> list[Item]:
    return store.snapshot().get("items", [])


@router.get("/items/{item_id}")
def get_item(item_id: str, store: StoreDep) -> Item:
    for item in store.snapshot().get("items", []):
        if item["id"] == item_id:
            return item
    raise NotFound(f"no item {item_id!r}")


@router.post("/items", status_code=201, dependencies=[Depends(require_token)])
def create_item(item: Item, store: StoreDep) -> Item:
    def add(data: dict) -> None:
        items = data.setdefault("items", [])
        if any(i["id"] == item.id for i in items):
            raise ConflictError(f"item {item.id!r} exists")
        items.append(item.model_dump())

    store.mutate(add)
    return item


def register_tools(gateway) -> None:
    @gateway.register
    def send_message(to: str, body: str) -> dict:
        """Send a message to a person about their case.

        Args:
            to: Who receives the message.
            body: The message text.
        """
        return {"to": to, "body": body}

    @gateway.register(effect=False)
    def list_items() -> list[dict]:
        """List the example items in the store."""
        return gateway.store.snapshot().get("items", [])
