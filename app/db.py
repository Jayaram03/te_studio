"""Database tables. PostgreSQL only (Supabase in production, a local or Docker PostgreSQL for development).

Rates are always stored with an explicit validity window (valid_from..valid_to, inclusive) and a
status (active / superseded). A newer rate sheet from the same supplier trims or supersedes the
overlapping part of older rates, so a lookup for any date returns one current rate. Nothing is deleted:
each new rate links to the rate it replaced (previous_rate_id, change_pct), which is the rate history.

Packages are versioned the same way: re-uploads of the same supplier package form one *family*
(family_id = id of the first version, version = 1, 2, 3 ...). Only versions whose validity the newer one
fully covers are superseded, so an off-season and a peak-season edition can both stay live.

Uploaded files are stored in the database itself (source_documents.content), so the app needs no
disk -- which is what serverless hosts like Vercel require.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, create_engine, false, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import NullPool

from .config import get_settings

Money = Numeric(12, 2)
Json = JSONB()


class Base(DeclarativeBase):
    pass


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(300))
    gst_number: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SourceDocument(Base):
    """Every uploaded file: the file itself, the raw parse, the AI extraction and the normalized preview."""
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    media_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary))      # loaded only when needed
    supplier_hint: Mapped[str | None] = mapped_column(String(200))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    # uploaded -> processing -> needs_review -> approved | rejected ; failed on errors
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    document_type: Mapped[str | None] = mapped_column(String(30))
    parsed_text: Mapped[str | None] = deferred(mapped_column(Text))
    extraction: Mapped[dict | None] = mapped_column(Json)
    normalized: Mapped[dict | None] = mapped_column(Json)
    issues: Mapped[list | None] = mapped_column(Json)
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    # what approving this file changes / changed in the library: new, price up/down, unchanged, replaced
    changes: Mapped[dict | None] = mapped_column(Json)


class Hotel(Base):
    """Every hotel we know of -- with rates (from rate sheets) or without (listed as package options)."""
    __tablename__ = "hotels"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    destination: Mapped[str | None] = mapped_column(String(100), index=True)
    category: Mapped[str | None] = mapped_column(String(50))     # Standard / Deluxe / Premium / Luxury ...
    property_type: Mapped[str | None] = mapped_column(String(30))  # hotel / resort / houseboat / homestay / camp
    star_rating: Mapped[float | None]
    address: Mapped[str | None] = mapped_column(Text)
    child_policy: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    room_types: Mapped[list[RoomType]] = relationship(back_populates="hotel")


class RoomType(Base):
    __tablename__ = "room_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    hotel: Mapped[Hotel] = relationship(back_populates="room_types")


class HotelRate(Base):
    __tablename__ = "hotel_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    meal_plan: Mapped[str] = mapped_column(String(10))          # EP CP MAP AP AI
    occupancy: Mapped[str] = mapped_column(String(20))          # single double triple extra_adult child_with_bed child_without_bed per_person
    basis: Mapped[str] = mapped_column(String(30))              # per_room_per_night | per_person_per_night
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    is_net: Mapped[bool | None] = mapped_column(Boolean)        # True = B2B / net
    taxes_included: Mapped[bool | None] = mapped_column(Boolean)
    valid_from: Mapped[date] = mapped_column(Date, index=True)
    valid_to: Mapped[date] = mapped_column(Date, index=True)
    weekdays: Mapped[str | None] = mapped_column(String(30))    # "fri,sat" ; null = every day
    min_nights: Mapped[int | None]
    season_name: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # history: the rate this one replaced (same room, meal plan, occupancy, days), and the change in %
    previous_rate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    replaced_by_document_id: Mapped[int | None] = mapped_column(Integer)   # set when superseded
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime)
    room_type: Mapped[RoomType] = relationship()
    hotel: Mapped[Hotel] = relationship()


class HotelSurcharge(Base):
    """Supplements (gala dinners, peak surcharges) and blackout / stop-sale dates."""
    __tablename__ = "hotel_surcharges"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    kind: Mapped[str] = mapped_column(String(20))               # supplement | blackout
    name: Mapped[str | None] = mapped_column(String(200))
    room_type: Mapped[str | None] = mapped_column(String(200))  # blackout for one room type only; null = whole hotel
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3))
    basis: Mapped[str | None] = mapped_column(String(30))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    replaced_by_document_id: Mapped[int | None] = mapped_column(Integer)


class Package(Base):
    __tablename__ = "packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    title: Mapped[str] = mapped_column(String(300))
    title_key: Mapped[str] = mapped_column(String(300), index=True)
    region: Mapped[str | None] = mapped_column(String(100), index=True)
    destinations: Mapped[list] = mapped_column(Json, default=list)
    nights: Mapped[int | None]
    days: Mapped[int | None]
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    inclusions: Mapped[list] = mapped_column(Json, default=list)
    exclusions: Mapped[list] = mapped_column(Json, default=list)
    terms: Mapped[list] = mapped_column(Json, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # versions: every re-upload of the same supplier package joins its family
    family_id: Mapped[int | None] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    base_name: Mapped[str | None] = mapped_column(String(300))     # title without season / year words
    edition: Mapped[str | None] = mapped_column(String(100))       # "Off Season 2026", "Summer 2027"
    previous_version_id: Mapped[int | None] = mapped_column(Integer)
    replaced_by_document_id: Mapped[int | None] = mapped_column(Integer)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    days_list: Mapped[list[PackageDay]] = relationship(order_by="PackageDay.day_number", cascade="all, delete-orphan",
                                                       back_populates="package")
    hotels: Mapped[list[PackageHotel]] = relationship(cascade="all, delete-orphan")
    prices: Mapped[list[PackagePrice]] = relationship(cascade="all, delete-orphan")
    supplier: Mapped[Supplier | None] = relationship()


class PackageDay(Base):
    """A day of a supplier package. Also the building block of the day library used by the trip builder."""
    __tablename__ = "package_days"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), index=True)
    day_number: Mapped[int]
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    overnight: Mapped[str | None] = mapped_column(String(100))
    meals: Mapped[str | None] = mapped_column(String(50))
    package: Mapped[Package] = relationship(back_populates="days_list")


class PackageHotel(Base):
    __tablename__ = "package_hotels"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    hotel_name: Mapped[str] = mapped_column(String(200))
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id"))   # linked to the hotel catalog
    category: Mapped[str | None] = mapped_column(String(50))
    nights: Mapped[int | None]
    room_type: Mapped[str | None] = mapped_column(String(200))
    meal_plan: Mapped[str | None] = mapped_column(String(10))


class PackagePrice(Base):
    __tablename__ = "package_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(50))
    pax_min: Mapped[int | None]
    pax_max: Mapped[int | None]
    occupancy: Mapped[str] = mapped_column(String(20))
    basis: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    is_net: Mapped[bool | None] = mapped_column(Boolean)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    season_name: Mapped[str | None] = mapped_column(String(100))


class ServiceRate(Base):
    """Transfers, sightseeing, activities, entry tickets, guides, vehicle hire, rentals."""
    __tablename__ = "service_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(300))
    name_key: Mapped[str] = mapped_column(String(300), index=True)
    destination: Mapped[str | None] = mapped_column(String(100), index=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(100))
    basis: Mapped[str] = mapped_column(String(20))
    pax_min: Mapped[int | None]
    pax_max: Mapped[int | None]                                    # for per-vehicle rates: seats per vehicle
    amount: Mapped[Decimal] = mapped_column(Money)                 # the price, or the low end of a range
    amount_max: Mapped[Decimal | None] = mapped_column(Money)      # high end when the sheet gives a range
    currency: Mapped[str] = mapped_column(String(3))
    is_net: Mapped[bool | None] = mapped_column(Boolean)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)  # add-on the guest pays for (package exclusions)
    valid_from: Mapped[date] = mapped_column(Date, index=True)
    valid_to: Mapped[date] = mapped_column(Date, index=True)
    season_name: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    previous_rate_id: Mapped[int | None] = mapped_column(Integer, index=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    replaced_by_document_id: Mapped[int | None] = mapped_column(Integer)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime)


class Place(Base):
    """Sightseeing places / attractions / offbeat destinations (descriptions, when they're open)."""
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    destination: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str | None] = mapped_column(String(30))      # attraction / offbeat / viewpoint / temple / garden ...
    description: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


# ----------------------------------------------------------------------- trip builder
TRIP_STATUSES = ("enquiry", "quoted", "confirmed", "completed", "lost")


class Trip(Base):
    """A trip being built for a customer: itinerary days + cost lines -> quote -> booking."""
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_phone: Mapped[str | None] = mapped_column(String(50))
    customer_email: Mapped[str | None] = mapped_column(String(200))
    lead_source: Mapped[str | None] = mapped_column(String(50), index=True)   # Instagram / Referral / Agilysis ...
    assigned_to: Mapped[str | None] = mapped_column(String(100), index=True)  # team member handling it
    follow_up_date: Mapped[date | None] = mapped_column(Date, index=True)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    share_prices: Mapped[bool] = mapped_column(Boolean, default=True)
    destination: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    adults: Mapped[int] = mapped_column(Integer, default=2)
    children_with_bed: Mapped[int] = mapped_column(Integer, default=0)
    children_without_bed: Mapped[int] = mapped_column(Integer, default=0)
    extra_beds: Mapped[int] = mapped_column(Integer, default=0)       # adults on an extra bed (e.g. 3rd adult)
    category: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    markup_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    gst_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="enquiry", index=True)   # see TRIP_STATUSES
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    inclusions: Mapped[list] = mapped_column(Json, default=list)
    exclusions: Mapped[list] = mapped_column(Json, default=list)
    terms: Mapped[list] = mapped_column(Json, default=list)
    # a template is a ready-made itinerary + costing of our own, re-used to start new trips
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), index=True)
    # with hotel options (A / B / C) the customer picks one; totals, payments and balance follow it
    chosen_option: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    days: Mapped[list[TripDay]] = relationship(order_by="TripDay.position", cascade="all, delete-orphan")
    items: Mapped[list[TripItem]] = relationship(order_by="TripItem.id", cascade="all, delete-orphan")
    notes_log: Mapped[list[TripNote]] = relationship(order_by="TripNote.id", cascade="all, delete-orphan")
    payments: Mapped[list[TripPayment]] = relationship(order_by="TripPayment.paid_on", cascade="all, delete-orphan")


class TripDay(Base):
    __tablename__ = "trip_days"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    position: Mapped[int]
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    overnight: Mapped[str | None] = mapped_column(String(100))
    meals: Mapped[str | None] = mapped_column(String(50))
    source_package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    source_day_id: Mapped[int | None] = mapped_column(ForeignKey("package_days.id"))


class TripItem(Base):
    """One cost line: a package price, a hotel stay, an activity / transfer, or a custom line."""
    __tablename__ = "trip_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))             # package | hotel | service | custom
    ref_id: Mapped[int | None]                                # package / hotel / service id
    day_position: Mapped[int | None]
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    unit_amount: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    optional: Mapped[bool] = mapped_column(Boolean, default=False)   # shown as an add-on, not in the total
    # hotel options: lines with a label ("Option A", "Deluxe") belong to that option only; blank = every option
    option_label: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict | None] = mapped_column(Json)               # breakdown, warnings, inputs used


class TripNote(Base):
    """Follow-up log: calls, WhatsApp messages, customer feedback, status changes."""
    __tablename__ = "trip_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    author: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TripPayment(Base):
    __tablename__ = "trip_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    mode: Mapped[str | None] = mapped_column(String(30))         # UPI / bank transfer / card / cash
    reference: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(300))


QUOTE_STATUSES = ("draft", "sent", "accepted", "declined", "expired")


class Quotation(Base):
    """A numbered quotation: a frozen copy of a trip (itinerary, costing, options, totals) at the time it
    was saved, so what the customer was sent never changes when the trip is edited later.
    Editing a quotation restores its copy into the trip (the working copy) and saves it back."""
    __tablename__ = "quotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)   # TE-Q-2026-0007
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)          # 1, 2, 3 ... per trip
    title: Mapped[str] = mapped_column(String(300))
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(50))
    customer_email: Mapped[str | None] = mapped_column(String(200))
    destination: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    travellers: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)   # see QUOTE_STATUSES
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    total: Mapped[Decimal | None] = mapped_column(Money)               # selling price (lowest option if several)
    per_person: Mapped[Decimal | None] = mapped_column(Money)
    options: Mapped[list | None] = mapped_column(Json)                 # [{label, sell, per_person}]
    snapshot: Mapped[dict] = mapped_column(Json)                       # the trip as quoted
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    share_prices: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)                     # internal note
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class AppSetting(Base):
    """Company profile, team, defaults -- editable from the Settings page."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(Json)


class AIUsage(Base):
    """One row per AI call: which provider/model, tokens in/out, estimated cost, how long it took."""
    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(30))              # extraction | test
    document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # in the currency the prices were entered in
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


class User(Base):
    """People who can sign in. Only admins exist today; `role` leaves room for staff / read-only later."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserSession(Base):
    """A signed-in browser. Only a hash of the cookie value is stored."""
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    user: Mapped[User] = relationship()


# ----------------------------------------------------------------------- engine
_engine = None
_Session = None


def normalize_url(url: str) -> str:
    """Hosted Postgres (Neon, Supabase, Vercel) hands out postgres:// URLs; SQLAlchemy needs the driver name."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    # psycopg doesn't understand PgBouncer's flag; the pooler is detected from the URL instead
    url = url.replace("?pgbouncer=true&", "?").replace("&pgbouncer=true", "").replace("?pgbouncer=true", "")
    if ("supabase.co" in url or "supabase.com" in url) and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def make_url_db(url: str) -> str:
    """Database name of a URL (used by the tests to tell databases apart)."""
    from sqlalchemy.engine import make_url
    return str(make_url(normalize_url(url)).database)


def is_transaction_pooler(url: str) -> bool:
    """Supabase's pooler on port 6543 (and PgBouncer-style poolers) run in transaction mode."""
    u = url.lower()
    return ":6543" in u or "pgbouncer=true" in u or "-pooler." in u


def init_db(url: str | None = None, drop: bool = False):
    """Create engine + tables. Call once at startup (tests pass their own URL)."""
    global _engine, _Session
    url = normalize_url(url or get_settings().database_url or "")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL URL, e.g. postgresql://user:password@host:5432/db "
                           "(Supabase: Connect -> Transaction pooler). See .env.example.")
    connect_args = {"connect_timeout": 10, "application_name": "rate-studio"}
    if is_transaction_pooler(url):
        # Supabase / Neon / PgBouncer transaction pooling can't keep prepared statements between queries
        connect_args["prepare_threshold"] = None
    if os.environ.get("VERCEL"):
        # serverless: don't hold connections between invocations; use the provider's pooled URL
        kwargs = {"poolclass": NullPool, "connect_args": connect_args}
    else:
        kwargs = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5, "pool_recycle": 300,
                  "connect_args": connect_args}
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, **kwargs)
    if drop:
        Base.metadata.drop_all(_engine)
        with _engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    migrate(_engine)
    lock_data_api(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def lock_data_api(engine) -> list[str]:
    """On Supabase, block its auto-generated Data API (REST/GraphQL) from reading the app's tables.

    Supabase publishes every table in the `public` schema through an API that anyone holding the project's
    public "anon" key can call. Turning on Row Level Security with no policies denies that API everything.
    The app itself connects as the table owner, which RLS doesn't apply to, so it keeps working.
    Runs on every start (cheap, idempotent), so tables added by later migrations are covered too.
    Returns the tables it changed. Does nothing on non-Supabase databases.
    """
    if engine.dialect.name != "postgresql":
        return []
    changed = []
    with engine.begin() as conn:
        if not conn.exec_driver_sql("select 1 from pg_roles where rolname = 'anon'").scalar():
            return []                                   # not Supabase (no Data API roles)
        rows = conn.exec_driver_sql(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and c.relkind = 'r' and not c.relrowsecurity").all()
        ours = set(Base.metadata.tables) | {"alembic_version"}
        for (name,) in rows:
            if name in ours:
                conn.exec_driver_sql(f'alter table "{name}" enable row level security')
                changed.append(name)
    return changed


def database_info(engine=None) -> dict:
    """What the Settings → System page shows about the database (no passwords)."""
    engine = engine or _engine
    url = engine.url
    info = {"dialect": engine.dialect.name, "host": url.host, "port": url.port, "database": url.database,
            "user": url.username, "kind": "PostgreSQL"}
    host = (url.host or "").lower()
    if "supabase" in host:
        info["kind"] = "Supabase · " + ("transaction pooler" if url.port == 6543 else
                                       "session pooler" if "pooler" in host else "direct connection")
    elif "neon.tech" in host:
        info["kind"] = "Neon" + (" · pooled" if "-pooler." in host else "")
    with engine.connect() as conn:
        try:
            info["schema_version"] = conn.exec_driver_sql("select version_num from alembic_version").scalar()
        except Exception:  # noqa: BLE001
            info["schema_version"] = None
        if engine.dialect.name == "postgresql":
            info["server_version"] = conn.exec_driver_sql("show server_version").scalar()
            supa = bool(conn.exec_driver_sql("select 1 from pg_roles where rolname = 'anon'").scalar())
            info["supabase_roles"] = supa
            if supa:
                open_ = conn.exec_driver_sql(
                    "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = current_schema() and c.relkind = 'r' and not c.relrowsecurity").scalar()
                info["data_api_locked"] = open_ == 0
            size = conn.exec_driver_sql("select pg_database_size(current_database())").scalar()
            info["size_mb"] = round(size / 1024 / 1024, 1)
    return info


def migrate(engine):
    """Bring the database schema up to date (Alembic migrations in app/migrations).

    - empty database            -> all migrations run, creating every table
    - tables made before
      migrations existed        -> missing tables added, then marked as current ("stamped")
    - older version             -> the missing migrations run
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "source_documents" in tables:
            # made by an early version: add the tables it is missing and record it as 0002 (the last
            # migration that only added tables); later migrations then add their columns. They check what
            # exists first, so tables create_all just made with the newest columns are left as they are.
            Base.metadata.create_all(conn, checkfirst=True)
            command.stamp(cfg, "0002")
            command.upgrade(cfg, "head")
        else:
            command.upgrade(cfg, "head")


def SessionLocal():
    if _Session is None:
        init_db()
    return _Session()
