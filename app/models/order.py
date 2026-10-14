"""
Pydantic schemas and dataclasses for Thrift Shoes orders.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, description="Customer's full name")
    phone_primary: str = Field(..., min_length=7, description="Primary mobile / WhatsApp number")
    phone_secondary: Optional[str] = Field(default="", description="Alternate phone number")
    address: str = Field(..., min_length=5, description="House/Flat/Street delivery address")
    area: str = Field(..., description="Area, Sector, or Colony")
    city: str = Field(..., description="City of delivery")
    nearest_landmark: Optional[str] = Field(default="", description="Prominent landmark nearby")
    shoe_brand_model: str = Field(..., description="Brand, Article, or Shoe Name (e.g. Nike Dunk Low)")
    shoe_size: str = Field(..., description="Shoe size (e.g. 42 / 8.5 US)")
    price: float = Field(..., ge=0, description="Agreed price in PKR")
    payment_method: str = Field(default="Cash on Delivery", description="Payment method: Cash on Delivery or Bank Transfer")
    notes: Optional[str] = Field(default="", description="Customer comments or packing notes")


class Order(BaseModel):
    id: int
    order_code: str
    created_at: str
    customer_name: str
    phone_primary: str
    phone_secondary: Optional[str] = ""
    address: str
    area: str
    city: str
    nearest_landmark: Optional[str] = ""
    shoe_brand_model: str
    shoe_size: str
    price: float
    payment_method: str = "Cash on Delivery"
    shoe_image_path: Optional[str] = ""
    invoice_path: Optional[str] = ""
    status: str = "Pending"  # Pending, Dispatched, Delivered, Cancelled
    notes: Optional[str] = ""
    sheets_synced: bool = False

    @property
    def full_address(self) -> str:
        parts = [self.address, self.area]
        if self.nearest_landmark:
            parts.append(f"(Near: {self.nearest_landmark})")
        parts.append(self.city)
        return ", ".join([p for p in parts if p])
