"""The fixed extraction contract.

Every document -- hotel rate sheet, DMC rate sheet, package PDF, Excel -- is turned into ONE
`Extraction` object. Claude is forced to answer by calling a tool whose input schema is this
model, so field names and structure never drift between documents.

Values are kept close to what the sheet says (raw meal plan codes, raw date strings, raw amounts)
and cleaned up afterwards by `normalize.py`. That keeps the AI step simple and makes the cleanup
deterministic and testable.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: str = Field(description="Start date as YYYY-MM-DD, or as written. A month alone ('Aug 2026') is fine")
    end: str = Field(description="End date as YYYY-MM-DD, or as written. A month alone ('Oct 2026') means its last day")


class Season(BaseModel):
    key: str = Field(description="Short unique key used by rate lines, e.g. 'regular', 'peak', 'festive'")
    name: str | None = None
    periods: list[DateRange] = Field(default_factory=list, description="A season can have several date ranges")


class SupplierInfo(BaseModel):
    name: str | None = Field(None, description="Company that issued the sheet (hotel, DMC, transporter)")
    type: Literal["hotel", "dmc", "transport", "activity", "other"] | None = None
    city: str | None = None
    country: str | None = None
    contact_person: str | None = None
    email: str | None = Field(None, description="All emails, comma separated")
    phone: str | None = Field(None, description="All phone numbers, comma separated")
    address: str | None = None
    website: str | None = None
    gst_number: str | None = None


class HotelRateLine(BaseModel):
    room_type: str = Field(description="Room category exactly as named, e.g. 'Deluxe Room', 'Premium Valley View'")
    meal_plan: str | None = Field(None, description="As written: EP/CP/MAP/AP/AI, CPAI, BB, HB, 'with breakfast'...")
    occupancy: str = Field(description="As written: single, double, twin, triple, extra adult / extra bed, CWB, CNB, per person")
    amount: float | None = Field(None, description="Number only. null if 'on request'")
    season_key: str | None = Field(None, description="Key of a season in `seasons`, if the rate is season based")
    valid_from: str | None = Field(None, description="Only if this line has its own dates")
    valid_to: str | None = None
    days: str | None = Field(None, description="Day restriction as written, e.g. 'Fri-Sat', 'weekend', 'Sun-Thu'")
    basis: Literal["per_room_per_night", "per_person_per_night", "unknown"] = "per_room_per_night"
    rate_type: Literal["net", "rack", "unknown"] = Field("unknown", description="net = B2B/agent/contracted; rack = public/published")
    currency: str | None = None
    taxes: Literal["included", "excluded", "unknown"] = "unknown"
    min_nights: int | None = None
    notes: str | None = None


class Supplement(BaseModel):
    name: str = Field(description="e.g. 'Christmas Gala Dinner', 'New Year Eve surcharge'")
    date_from: str | None = None
    date_to: str | None = None
    amount: float | None = None
    currency: str | None = None
    basis: Literal["per_person", "per_adult", "per_child", "per_room", "per_room_per_night", "per_booking", "unknown"] = "unknown"
    mandatory: bool = True
    notes: str | None = None


class Blackout(BaseModel):
    start: str
    end: str
    room_type: str | None = Field(None, description="Only if the stop sale is for one room type")


class HotelBlock(BaseModel):
    name: str
    city: str | None = None
    category: str | None = Field(None, description="Standard / Deluxe / Premium / Luxury, if stated")
    property_type: Literal["hotel", "resort", "houseboat", "homestay", "camp", "villa", "other"] | None = None
    destination: str | None = Field(None, description="Wider destination / region, e.g. 'Kerala', 'Phuket'")
    star_rating: float | None = None
    address: str | None = None
    rates: list[HotelRateLine] = Field(default_factory=list)
    supplements: list[Supplement] = Field(default_factory=list)
    blackout_dates: list[Blackout] = Field(default_factory=list, description="Dates rates are not valid / stop sale")
    child_policy: str | None = None
    notes: str | None = None


class ItineraryDay(BaseModel):
    day: int
    title: str | None = None
    description: str | None = None
    overnight: str | None = Field(None, description="City where the guest stays that night")
    meals: str | None = Field(None, description="e.g. 'B', 'B/D', 'Breakfast & Dinner'")


class PackageHotel(BaseModel):
    """One row per hotel. When the sheet lists several options for a city/category ("any of these or
    similar"), add one row per listed hotel with the same city, category and nights."""
    city: str | None = None
    hotel_name: str
    category: str | None = Field(None, description="Package tier this hotel belongs to, e.g. 'Standard', 'Deluxe', '4 Star'")
    property_type: Literal["hotel", "resort", "houseboat", "homestay", "camp", "villa", "other"] | None = None
    nights: int | None = None
    room_type: str | None = None
    meal_plan: str | None = None


class PackagePrice(BaseModel):
    category: str | None = Field(None, description="Tier, e.g. 'Standard', 'Deluxe', '3 Star'")
    pax_min: int | None = Field(None, description="Group size this price applies to (min travellers)")
    pax_max: int | None = None
    occupancy: str = Field("double", description="As written: per person twin sharing, single, triple, CWB, CNB ...")
    basis: Literal["per_person", "per_package", "unknown"] = "per_person"
    amount: float | None = None
    currency: str | None = None
    season_key: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    rate_type: Literal["net", "rack", "unknown"] = "unknown"


class PackageBlock(BaseModel):
    title: str = Field(description="Package name exactly as the document writes it")
    base_name: str | None = Field(None, description="The name without season, year, edition or revision words, "
                                  "e.g. 'Kashmir 5N/6D' for 'Off Season 2026 Kashmir Package 5N/6D (Revised)'. "
                                  "Used to recognise a re-sent or updated version of the same package")
    edition: str | None = Field(None, description="The season / year / edition words removed from base_name, "
                                "e.g. 'Off Season 2026', 'Summer 2027', 'Revised Oct 2026'")
    region: str | None = Field(None, description="Region / state the package covers, e.g. 'Kashmir', 'Kerala', 'Bali'")
    destinations: list[str] = Field(default_factory=list, description="Cities / places visited, in order")
    nights: int | None = None
    days: int | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    hotels: list[PackageHotel] = Field(default_factory=list)
    prices: list[PackagePrice] = Field(default_factory=list)
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)


class ServiceRateLine(BaseModel):
    kind: Literal["transfer", "sightseeing", "activity", "entry_ticket", "guide", "vehicle_hire", "rental", "meal", "other"]
    name: str = Field(description="e.g. 'Cochin Airport to Munnar', 'Phi Phi island tour by speedboat'")
    destination: str | None = None
    vehicle_type: str | None = Field(None, description="e.g. Sedan, Innova, Tempo Traveller 12 seater, SIC, Private")
    basis: Literal["per_vehicle", "per_person", "per_adult", "per_child", "per_group", "unknown"] = "unknown"
    pax_min: int | None = None
    pax_max: int | None = Field(None, description="For per-vehicle prices: seats per vehicle ('per cab for 6 pax' -> 6)")
    amount: float | None = Field(None, description="The price; for a range like 1200-1500 the LOW end")
    amount_max: float | None = Field(None, description="High end of a price range, else null")
    optional: bool = Field(False, description="True for add-ons NOT included in a package (listed under exclusions / 'on your own expense')")
    currency: str | None = None
    season_key: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    rate_type: Literal["net", "rack", "unknown"] = "unknown"
    notes: str | None = Field(None, description="e.g. 'negotiable', 'required only in heavy snow', 'Phase 1'")


class PlaceInfo(BaseModel):
    """A sightseeing place, attraction or offbeat destination described in the document (with or without a price)."""
    name: str
    destination: str | None = Field(None, description="Region / state, e.g. 'Kashmir'")
    region: str | None = Field(None, description="District / nearest town, e.g. 'Kupwara'")
    kind: Literal["attraction", "offbeat", "viewpoint", "religious", "garden", "lake", "valley", "market", "other"] | None = None
    description: str | None = Field(None, description="Short summary in your own words (1-2 sentences)")
    availability: str | None = Field(None, description="When it can be visited, e.g. '15 Apr - 15 Oct'")


class Extraction(BaseModel):
    document_type: Literal["hotel_rate_sheet", "dmc_rate_sheet", "package", "mixed", "unknown"]
    supplier: SupplierInfo = Field(default_factory=SupplierInfo)
    currency: str | None = Field(None, description="Default currency for the whole document")
    validity: DateRange | None = Field(None, description="Overall validity of the document, if stated")
    issued_on: str | None = Field(None, description="Date the sheet was issued / revised, if printed on it")
    is_revision: bool = Field(False, description="True if the document says it revises, updates or replaces earlier rates")
    taxes: Literal["included", "excluded", "unknown"] = "unknown"
    rate_type: Literal["net", "rack", "unknown"] = Field("unknown", description="Document-wide: are these B2B/net rates?")
    seasons: list[Season] = Field(default_factory=list)
    hotels: list[HotelBlock] = Field(default_factory=list)
    packages: list[PackageBlock] = Field(default_factory=list)
    services: list[ServiceRateLine] = Field(default_factory=list)
    places: list[PlaceInfo] = Field(default_factory=list)
    general_terms: list[str] = Field(default_factory=list, description="Cancellation, payment, child policy etc.")
    warnings: list[str] = Field(default_factory=list, description="Anything unclear, ambiguous or unreadable")


def tool_schema() -> dict:
    """JSON schema handed to Claude as the tool input schema."""
    return Extraction.model_json_schema()
