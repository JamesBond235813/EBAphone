from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Return a naive UTC timestamp for existing MySQL DATETIME columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(40))
    open_hours: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    default_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=True)
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="operator")
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Banner(Base):
    __tablename__ = "banners"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(500))
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SKU(Base):
    __tablename__ = "skus"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_name: Mapped[str] = mapped_column(String(160))
    brand: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(50), default="phones", index=True)
    variant: Mapped[str] = mapped_column(String(160))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    image: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    inventories: Mapped[list["Inventory"]] = relationship(back_populates="sku")


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (UniqueConstraint("sku_id", "store_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    available: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[int] = mapped_column(Integer, default=0)
    sold: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[SKU] = relationship(back_populates="inventories")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_phone: Mapped[str] = mapped_column(String(40), index=True)
    product_name: Mapped[str] = mapped_column(String(160))
    variant: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    deposit_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    payment_plan: Mapped[str] = mapped_column(String(20))
    payment_status: Mapped[str] = mapped_column(String(40), default="pending")
    order_status: Mapped[str] = mapped_column(String(40), default="awaiting_payment")
    fulfillment_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canonical service area captured at checkout.  Keeping the resolved zone
    # on the order prevents later fulfilment staff from having to infer
    # coverage from a free-form address again.
    delivery_zone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    pickup_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock_reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When a payment checkout is active, remember which provider attempt owns
    # the order's inventory reservation.  Without this link a late callback
    # from an older attempt could release stock held by a newer checkout.
    reservation_payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    customer: Mapped[User | None] = relationship(back_populates="orders")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="hubtel")
    provider_reference: Mapped[str] = mapped_column(String(120), unique=True)
    purpose: Mapped[str] = mapped_column(String(30), default="initial")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    checkout_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payer_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SmsChallenge(Base):
    """Persistent, single-use OTP state keyed by canonical phone number."""

    __tablename__ = "sms_challenges"
    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    reservation_id: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    send_history: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SupportConversation(Base):
    __tablename__ = "support_conversations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    subject: Mapped[str] = mapped_column(String(160), default="General support")
    assigned_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    messages: Mapped[list["SupportMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("support_conversations.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(30))
    sender_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[SupportConversation] = relationship(back_populates="messages")


class SupportAssistantConfig(Base):
    __tablename__ = "support_assistant_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(500), default="https://api.openai.com/v1")
    model: Mapped[str] = mapped_column(String(120), default="gpt-4o-mini")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="Answer briefly and helpfully. Use the catalog, store, and FAQ information provided below.")
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.30"))
    max_tokens: Mapped[int] = mapped_column(Integer, default=300)
    max_input_chars: Mapped[int] = mapped_column(Integer, default=1000)
    history_messages: Mapped[int] = mapped_column(Integer, default=8)
    per_user_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3)
    per_user_daily_limit: Mapped[int] = mapped_column(Integer, default=20)
    global_daily_limit: Mapped[int] = mapped_column(Integer, default=1000)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SupportAssistantUsage(Base):
    __tablename__ = "support_assistant_usage"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
