from django.urls import path

from .views import (
    CatalogItemDetailView,
    CatalogItemListCreateView,
    CatalogPriceCreateView,
    EventTypeDetailView,
    EventTypeListCreateView,
)

app_name = "catalog"

urlpatterns = [
    path("event-types/", EventTypeListCreateView.as_view(), name="event-types"),
    path(
        "event-types/<uuid:event_type_id>/",
        EventTypeDetailView.as_view(),
        name="event-type-detail",
    ),
    path("catalog/items/", CatalogItemListCreateView.as_view(), name="items"),
    path("catalog/items/<uuid:item_id>/", CatalogItemDetailView.as_view(), name="item-detail"),
    path(
        "catalog/items/<uuid:item_id>/prices/",
        CatalogPriceCreateView.as_view(),
        name="price-create",
    ),
]
