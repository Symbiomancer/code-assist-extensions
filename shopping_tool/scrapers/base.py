"""Base retailer scraper — abstract interface for all retailer implementations."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductListing:
    """A product from a search result."""
    title: str
    price: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    rating: Optional[str] = None
    review_count: Optional[str] = None
    retailer: str = ""
    in_stock: bool = True


@dataclass
class ProductDetails:
    """Full details for a single product page."""
    title: str
    price: Optional[str] = None
    url: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    rating: Optional[str] = None
    review_count: Optional[str] = None
    availability: str = "Unknown"
    retailer: str = ""
    image_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "price": self.price,
            "url": self.url,
            "description": self.description or "",
            "features": self.features,
            "rating": self.rating,
            "review_count": self.review_count,
            "availability": self.availability,
            "retailer": self.retailer,
            "image_url": self.image_url,
        }


class BaseRetailerScraper(ABC):
    """Abstract base for retailer scrapers."""

    retailer_name: str = "unknown"

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[ProductListing]:
        """Search for products and return listings."""
        ...

    @abstractmethod
    async def get_details(self, url: str) -> Optional[ProductDetails]:
        """Get full product details from a product page URL."""
        ...
