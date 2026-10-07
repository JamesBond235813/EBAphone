from datetime import datetime
from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .sms import normalize


def _category_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return {
        "case": "cases-accessories",
        "cases": "cases-accessories",
        "accessory": "cases-accessories",
        "accessories": "cases-accessories",
        "case-accessories": "cases-accessories",
        "case-and-accessories": "cases-accessories",
        "cases-and-accessories": "cases-accessories",
    }.get(slug, slug)


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; name: str; address: str; phone: str; open_hours: str; active: bool


class SKUOut(BaseModel):
    id: int; product_name: str; brand: str; category: str; variant: str; price: Decimal
    deposit_rate: Decimal; image: str; active: bool; store_stock: dict[int, int]


class OrderCreate(BaseModel):
    sku_id: int
    quantity: int = Field(default=1, ge=1, le=99)
    payment_plan: Literal["full", "deposit"]
    fulfillment_type: Literal["pickup", "shipping"] | None = None
    store_id: int | None = None
    # Delivery addresses are persisted on the order and passed to the
    # fulfilment team, so reject values that are too short to identify a
    # destination or too large to be a usable address.  Blank values remain
    # ``None`` so pickup requests can omit the field cleanly.
    shipping_address: str | None = Field(default=None, min_length=10, max_length=500)
    customer_name: str = Field(min_length=2, max_length=120)
    customer_phone: str = Field(min_length=7, max_length=40)

    @field_validator("customer_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter your full name")
        return value

    @field_validator("customer_phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return normalize(value)

    @field_validator("shipping_address", mode="before")
    @classmethod
    def clean_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Enter a valid shipping address")
        value = " ".join(value.split())
        return value or None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; sku_id: int; user_id: int | None = None; store_id: int | None; customer_name: str; customer_phone: str
    product_name: str; variant: str; quantity: int = 1; unit_price: Decimal; total_amount: Decimal = Decimal("0"); deposit_rate: Decimal
    deposit_amount: Decimal; remaining_amount: Decimal; paid_amount: Decimal = Decimal("0"); balance_due: Decimal = Decimal("0"); currency: str; payment_plan: str
    payment_status: str; order_status: str; fulfillment_type: str | None
    shipping_address: str | None; delivery_zone: str | None = None; pickup_code: str | None; tracking_number: str | None
    release_reason: str | None; stock_reserved: bool = False; reservation_expires_at: datetime | None = None; created_at: datetime; store_name: str | None = None


class ReleaseRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return " ".join(value.split())


class TrackingRequest(BaseModel):
    tracking_number: str = Field(min_length=3, max_length=100)

    @field_validator("tracking_number")
    @classmethod
    def clean_tracking_number(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a valid tracking number")
        return value


class CompleteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    pickup_code: str | None = Field(default=None, min_length=4, max_length=20)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None

    @field_validator("pickup_code")
    @classmethod
    def clean_pickup_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = "".join(value.split()).upper()
        return value or None


class SettlementRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    payment_method: str = Field(default="manual", min_length=2, max_length=80)
    reference: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("payment_method")
    @classmethod
    def clean_payment_method(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter a payment method")
        return value

    @field_validator("reference", "note")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None
class SKUUpdate(BaseModel):
    product_name: str | None = Field(default=None, min_length=2, max_length=160)
    brand: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    variant: str | None = Field(default=None, min_length=1, max_length=160)
    image: str | None = Field(default=None, max_length=500)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    deposit_rate: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)
    active: bool | None = None

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str | None) -> str | None:
        return _category_slug(value) if value is not None else None


class SKUCreate(BaseModel):
    """Fields required to publish a new catalog item.

    ``initial_stock`` is deliberately optional: a product can be created
    first and allocated to stores later from the stock matrix.  When present,
    keys are store ids and values are non-negative available units.
    """

    product_name: str = Field(min_length=2, max_length=160)
    brand: str = Field(min_length=1, max_length=80)
    category: str = Field(default="phones", min_length=1, max_length=50)
    variant: str = Field(min_length=1, max_length=160)
    image: str | None = Field(default=None, max_length=500)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    deposit_rate: Decimal = Field(default=100, gt=0, le=100, max_digits=5, decimal_places=2)
    active: bool = True
    initial_stock: dict[int, int] = Field(default_factory=dict)

    @field_validator("product_name", "brand", "variant", "category")
    @classmethod
    def clean_text(cls, value: str, info) -> str:
        value = " ".join(value.split())
        if info.field_name == "category":
            value = _category_slug(value)
        if not value:
            raise ValueError(f"{info.field_name} is required")
        return value

    @field_validator("image")
    @classmethod
    def clean_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("initial_stock")
    @classmethod
    def clean_initial_stock(cls, value: dict[int, int]) -> dict[int, int]:
        cleaned: dict[int, int] = {}
        for store_id, quantity in value.items():
            if int(store_id) <= 0 or int(quantity) < 0:
                raise ValueError("Initial stock must use positive store ids and non-negative quantities")
            cleaned[int(store_id)] = int(quantity)
        return cleaned


class StockUpdate(BaseModel): store_id:int; available:int=Field(ge=0)


class StoreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=3, max_length=255)
    phone: str = Field(min_length=3, max_length=40)
    open_hours: str = Field(min_length=3, max_length=120)
    active: bool = True

    @field_validator("name", "address", "phone", "open_hours")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("This field is required")
        return value


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, min_length=3, max_length=40)
    open_hours: str | None = Field(default=None, min_length=3, max_length=120)
    active: bool | None = None

    @field_validator("name", "address", "phone", "open_hours")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


AdminRole = Literal["operator", "manager", "super_admin"]


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    username: str
    role: str
    store_id: int | None = None
    active: bool
    created_at: datetime


class AdminUserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=100)
    role: AdminRole = "operator"
    store_id: int | None = Field(default=None, gt=0)
    active: bool = True

    @field_validator("name", "username")
    @classmethod
    def clean_identity(cls, value: str) -> str:
        value = " ".join(value.split()) if " " in value else value.strip()
        if not value:
            raise ValueError("This field is required")
        return value


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    username: str | None = Field(default=None, min_length=3, max_length=80)
    password: str | None = Field(default=None, min_length=8, max_length=100)
    role: AdminRole | None = None
    store_id: int | None = Field(default=None, gt=0)
    active: bool | None = None

    @field_validator("name", "username")
    @classmethod
    def clean_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()) if " " in value else value.strip()
        return value or None
class PaymentSessionOut(BaseModel):
    order_id: str; checkout_id: str; checkout_url: str | None; status: str
class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    password: str = Field(min_length=6, max_length=100)
    email: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter your full name")
        return value

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return normalize(value)


class LoginRequest(BaseModel):
    account: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("account")
    @classmethod
    def clean_account(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Account is required")
        return value
class SmsRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=40)

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return normalize(value)


class SmsVerifyRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=40)
    code: str = Field(pattern=r"^[0-9]{6}$")
    name: str | None = Field(default=None, max_length=120)

    @field_validator("phone")
    @classmethod
    def canonical_phone(cls, value: str) -> str:
        return normalize(value)

    @field_validator("name")
    @classmethod
    def clean_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if value and len(value) < 2:
            raise ValueError("Enter your full name")
        return value or None


class TokenOut(BaseModel): access_token:str; token_type:str="bearer"; user:dict
class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    email: str | None = None
    default_address: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    default_address: str | None = Field(default=None, max_length=500)

    @field_validator("name", "email", "default_address")
    @classmethod
    def clean_profile_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class AdminCustomerOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str | None = None
    default_address: str | None = None
    notes: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime | None = None
    order_count: int = 0
    order_value: Decimal = Decimal("0")
    paid_value: Decimal = Decimal("0")
    last_order_at: datetime | None = None
    stores: list[str] = Field(default_factory=list)


class AdminCustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    default_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    active: bool | None = None

    @field_validator("name", "email", "default_address", "notes")
    @classmethod
    def clean_customer_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class SupportMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a message")
        return value


class SupportMessageOut(BaseModel):
    id: int
    sender_type: str
    sender_id: int | None = None
    message: str
    created_at: datetime


class SupportConversationOut(BaseModel):
    id: str
    user_id: int
    customer_name: str
    customer_phone: str
    status: str
    subject: str
    assigned_admin_id: int | None = None
    last_message_at: datetime
    created_at: datetime
    last_message: str | None = None
    message_count: int = 0
    messages: list[SupportMessageOut] = Field(default_factory=list)


class SupportStatusUpdate(BaseModel):
    status: Literal["open", "waiting_customer", "resolved"]


class SupportAssistantConfigUpdate(BaseModel):
    enabled: bool
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    prompt: str = Field(min_length=1, max_length=8000)
    temperature: Decimal = Field(default=Decimal("0.3"), ge=0, le=2, max_digits=3, decimal_places=2)
    max_tokens: int = Field(default=300, ge=50, le=1000)
    max_input_chars: int = Field(default=1000, ge=50, le=1000)
    history_messages: int = Field(default=8, ge=0, le=20)
    per_user_cooldown_seconds: int = Field(default=3, ge=0, le=300)
    per_user_daily_limit: int = Field(default=20, ge=1, le=500)
    global_daily_limit: int = Field(default=1000, ge=1, le=100000)

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if "?" in value or "#" in value:
            raise ValueError("Base URL cannot include a query or fragment")
        return value

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("Enter a valid model name")
        return value


class SupportAssistantTestRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
class BannerOut(BaseModel): model_config=ConfigDict(from_attributes=True); id:int; title:str; subtitle:str; image:str|None=None; sort_order:int; active:bool
class BannerUpdate(BaseModel): title:str|None=None; subtitle:str|None=None; image:str|None=None; sort_order:int|None=None; active:bool|None=None


class StoreAvailabilityOut(BaseModel):
    store_id: int
    store_name: str
    address: str
    stock: int
    pickup_available: bool
    delivery_available: bool
    estimated_delivery: str


class DispatchRequest(BaseModel):
    store_id: int = Field(gt=0)
    # A normal dispatch must be received by a destination that has available
    # stock.  Global administrators may explicitly create an inter-store
    # transfer when the destination is empty; that reservation is kept in the
    # destination's locked bucket until the stock arrives.
    allow_in_transit: bool = False


class TransferReceiptRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class PaymentReviewFulfillRequest(BaseModel):
    """Explicit destination and audit note for resolving a paid review hold."""

    store_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class CancelRequest(BaseModel):
    reason: str = Field(default="Customer requested cancellation", min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return " ".join(value.split())
